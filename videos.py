"""Finds and downloads background stock videos from Pixabay (default) or Pexels."""
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import vision
from config import flog, BASE, CACHE_DIR, DATA_DIR, env, is_mock, run_ffmpeg

API = "https://api.pexels.com/videos/search"


def _pick_file(video: dict):
    files = [f for f in video.get("video_files", [])
             if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
    if not files:
        return None
    portrait = [f for f in files if f["height"] >= f["width"]]
    pool = portrait or files
    good = [f for f in pool if f["width"] >= 720]
    if good:
        return min(good, key=lambda f: f["width"] * f["height"])
    return max(pool, key=lambda f: f["width"] * f["height"])


def _download(url: str, dest):
    part = dest.with_suffix(".part")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    part.replace(dest)


def _mock_clip():
    dest = CACHE_DIR / f"mock_{random.randrange(10**6)}.mp4"
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)]
    try:
        run_ffmpeg(["-f", "lavfi", "-i", "gradients=s=720x1280:d=6:r=30"] + enc)
    except RuntimeError:
        run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=720x1280:d=6:r=30"] + enc)
    return dest


PIXABAY_API = "https://pixabay.com/api/videos/"
_PIXABAY_CACHE: dict = {}  # Pixabay asks that API responses are cached for 24 hours


def _source():
    """Which video site to use: VIDEO_SOURCE if set, otherwise whichever key is available."""
    s = env("VIDEO_SOURCE").lower()
    if s in ("pexels", "pixabay"):
        return s
    if env("PEXELS_API_KEY"):
        return "pexels"
    if env("PIXABAY_API_KEY"):
        return "pixabay"
    return None


def has_video_key() -> bool:
    return is_mock() or _source() is not None


# Tags that mark YouTube intros, overlays and templates rather than real footage.
JUNK_TAGS = ("subscribe", "youtube", "subscriber", "button", "channel", "intro", "template", "logo", "lower third",
             "green screen", "greenscreen", "social media", "countdown", "like button", "notification", "overlay",
             "transition", "alpha", "text", "title")


def _is_junk(hit: dict) -> bool:
    tags = hit.get("tags", "").lower()
    return any(j in tags for j in JUNK_TAGS)


def _words(query: str) -> list:
    return [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 3]


def tag_score(hit: dict, query: str) -> int:
    """How many words of the search appear as whole words in the clip's own tags (Pixabay's search is loose)."""
    tokens = set(re.findall(r"[a-z0-9]+", hit.get("tags", "").lower()))
    score = 0
    for w in _words(query):
        if w in tokens or w + "s" in tokens or (w.endswith("s") and w[:-1] in tokens):
            score += 1
    return score


def need_score(query: str) -> int:
    """How many search words a clip's tags must match. Short searches need every word ('airplane runway' needs both);
    longer ones need about half, so 'Universal Serial Bus' never passes on 'bus' alone."""
    n = len(_words(query))
    return max(1, n if n <= 2 else (n + 1) // 2)


BLOCKLIST_FILE = DATA_DIR / "blocked_clips.json"


def _blocked() -> set:
    """Clip ids you never want again: add Pixabay ids (numbers) to blocked_clips.json, e.g. [12345, 67890]."""
    try:
        return {str(x) for x in json.loads(BLOCKLIST_FILE.read_text(encoding="utf-8"))}
    except Exception:
        return set()


def _pick_best(hits: list, query: str):
    """Best-matching clip first (most search words in its tags, then the more popular), with a little variety
    among the top three so repeated topics don't always give the same clip."""
    ranked = sorted(hits, key=lambda h: (tag_score(h, query), h.get("likes", 0) + h.get("downloads", 0) / 50),
                    reverse=True)
    return random.choice(ranked[:3])


def _pixabay_hits(q: str, key: str) -> list:
    cached = _PIXABAY_CACHE.get(q)
    if cached and time.time() - cached[0] < 86400:
        return cached[1]
    r = requests.get(
        PIXABAY_API,
        params={"key": key, "q": q[:100], "video_type": "film", "per_page": 20,
                "safesearch": "true", "min_width": 1280},
        timeout=30,
    )
    if r.status_code == 429:
        raise RuntimeError("Pixabay rate limit reached (100 requests/minute). Wait a minute and try again.")
    if r.status_code != 200:
        raise RuntimeError(f"Pixabay error {r.status_code}: {r.text[:150]}. Check PIXABAY_API_KEY in .env")
    hits = r.json().get("hits", [])
    _PIXABAY_CACHE[q] = (time.time(), hits)
    return hits


def _thumb(h: dict, kind: str) -> bytes:
    """A small JPEG of the candidate: a frame from its smallest video file, or the photo itself."""
    if kind == "photo":
        r = requests.get(h.get("webformatURL") or h["previewURL"], timeout=30)
        r.raise_for_status()
        return r.content
    sizes = h.get("videos", {})
    f = next((sizes[k] for k in ("tiny", "small", "medium") if sizes.get(k, {}).get("url")), None)
    if not f:
        raise RuntimeError("no video file")
    clip = CACHE_DIR / f"thumb_{h['id']}.mp4"
    jpg = CACHE_DIR / f"thumb_{h['id']}.jpg"
    try:
        _download(f["url"], clip)
        run_ffmpeg(["-ss", "1", "-i", clip, "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", jpg])
        return jpg.read_bytes()
    finally:
        for x in (clip, jpg):
            try:
                x.unlink()
            except OSError:
                pass


def _vision_check(hits: list, q: str, question: str, kind: str):
    """Ask Gemini which of the best-matching candidates really shows the topic. ("skip", None) = no check done."""
    if not question or not vision.enabled():
        return ("skip", None)
    ranked = sorted(hits, key=lambda h: (tag_score(h, q), h.get("likes", 0) + h.get("downloads", 0) / 50),
                    reverse=True)[:3]
    cands = []
    for h in ranked:
        try:
            cands.append((h, _thumb(h, kind)))
        except Exception as e:
            flog(f"[footage]   could not preview a candidate ({str(e)[:60]})")
    if not cands:
        return ("skip", None)
    verdict, h, _ = vision.choose(cands, question, q)
    return (verdict, h)


PIXABAY_PHOTO_API = "https://pixabay.com/api/"
_PHOTO_CACHE: dict = {}


def _pixabay_photo_hits(q: str, key: str) -> list:
    cached = _PHOTO_CACHE.get(q)
    if cached and time.time() - cached[0] < 86400:
        return cached[1]
    r = requests.get(
        PIXABAY_PHOTO_API,
        params={"key": key, "q": q[:100], "image_type": "photo", "orientation": "horizontal", "per_page": 20,
                "safesearch": "true", "min_width": 900},
        timeout=30,
    )
    if r.status_code != 200:
        return []
    hits = r.json().get("hits", [])
    _PHOTO_CACHE[q] = (time.time(), hits)
    return hits


def _find_pixabay_photo(q: str, key: str, used: set, question: str = ""):
    """Photos have far more coverage than videos for specific topics; the renderer adds a slow zoom."""
    blocked = _blocked()
    hits = [h for h in _pixabay_photo_hits(q, key)
            if ("p%s" % h["id"]) not in used and str(h["id"]) not in blocked and not _is_junk(h)]
    scored = [(tag_score(h, q), h) for h in hits]
    best = max((sc for sc, _ in scored), default=0)
    hits = [h for sc, h in scored if best >= need_score(q) and sc >= best]
    flog(f"[footage] photo search '{q}': {len(hits)} matching results")
    if not hits:
        return None
    verdict, h = _vision_check(hits, q, question, "photo")
    if verdict == "reject":
        return None
    h = h or _pick_best(hits, q)
    url = h.get("largeImageURL") or h.get("webformatURL")
    if not url:
        return None
    dest = CACHE_DIR / f"pixabay_photo_{h['id']}.jpg"
    if not dest.exists():
        _download(url, dest)
    used.add("p%s" % h["id"])
    flog(f"[footage]   -> picked photo tagged: {h.get('tags', '')}")
    return dest, f"{q}  ->  photo tags: {h.get('tags', '')[:60]}"


def _find_pixabay(queries: list, used: set, question: str = ""):
    key = env("PIXABAY_API_KEY")
    if not key:
        raise RuntimeError("PIXABAY_API_KEY is missing. Get a free key at pixabay.com/api/docs and put it in .env")
    for q in queries:
        blocked = _blocked()
        hits = [h for h in _pixabay_hits(q, key)
                if h["id"] not in used and str(h["id"]) not in blocked and h.get("duration", 0) >= 4
                and not _is_junk(h)]
        generic = q == "abstract colorful background"
        if not generic:  # only accept videos whose own tags actually match the search
            scored = [(tag_score(h, q), h) for h in hits]
            best = max((sc for sc, _ in scored), default=0)
            hits = [h for sc, h in scored if sc >= max(need_score(q), best)] if best >= need_score(q) else []
        flog(f"[footage] searched '{q}': {len(hits)} matching results")
        if not hits and not generic:
            try:
                photo = _find_pixabay_photo(q, key, used, question)
            except Exception as e:  # keep going with the next query
                flog(f"[footage] photo search failed: {e}")
                photo = None
            if photo:
                return photo
        if not hits:
            continue
        if generic:
            h = random.choice(hits[:8])
        else:
            verdict, h = _vision_check(hits, q, question, "video")
            if verdict == "reject":
                continue
            h = h or _pick_best(hits, q)
        sizes = h.get("videos", {})
        f = next((sizes[k] for k in ("medium", "large", "small") if sizes.get(k, {}).get("url")), None)
        if not f:
            continue
        dest = CACHE_DIR / f"pixabay_{h['id']}.mp4"
        if not dest.exists():
            _download(f["url"], dest)
        used.add(h["id"])
        flog(f"[footage]   -> picked video tagged: {h.get('tags', '')}")
        return dest, f"{q}  ->  video tags: {h.get('tags', '')[:60]}"
    raise RuntimeError(f"No Pixabay videos found for any of: {queries}")


def find_background(queries: list, used: set, question: str = ""):
    """Return a local path to a video matching the first query that has results."""
    if is_mock():
        return _mock_clip(), queries[0] if queries else "mock"
    src = _source()
    if src is None:
        raise RuntimeError("No video API key found. Add PEXELS_API_KEY or PIXABAY_API_KEY to the .env file.")
    if src == "pixabay":
        return _find_pixabay(queries, used, question)
    key = env("PEXELS_API_KEY")
    if not key:
        raise RuntimeError("PEXELS_API_KEY is missing. Add it to .env, or use PIXABAY_API_KEY instead.")
    for q in queries:
        r = requests.get(
            API,
            headers={"Authorization": key},
            params={"query": q, "orientation": "portrait", "size": "medium", "per_page": 15},
            timeout=30,
        )
        if r.status_code == 401:
            raise RuntimeError("Pexels rejected your API key (401). Check PEXELS_API_KEY in .env")
        if r.status_code == 429:
            raise RuntimeError("Pexels rate limit reached (200 requests/hour). Try again later.")
        r.raise_for_status()
        vids = [v for v in r.json().get("videos", []) if v["id"] not in used and v.get("duration", 0) >= 4]
        if not vids:
            continue
        v = random.choice(vids[:10])
        f = _pick_file(v)
        if not f:
            continue
        dest = CACHE_DIR / f"pexels_{v['id']}.mp4"
        if not dest.exists():
            _download(f["link"], dest)
        used.add(v["id"])
        return dest, q
    raise RuntimeError(f"No Pexels videos found for any of: {queries}")


class UsedSet(set):
    """The clips already chosen for this video. Safe to share between the footage searches that run side by side."""
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()

    def add(self, x):
        with self._lock:
            super().add(x)


def find_many(jobs: list, workers: int = 4, on_done=lambda done, total: None) -> list:
    """Run several footage searches at once. jobs = [callable returning (path, matched)]. Results keep the same order;
    an error in one search is raised after the others finish (the callers already catch their own failures)."""
    out, done = [None] * len(jobs), [0]
    lock = threading.Lock()

    def run(i):
        try:
            out[i] = jobs[i]()
        finally:
            with lock:
                done[0] += 1
                on_done(done[0], len(jobs))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(run, i) for i in range(len(jobs))]
        for f in futs:
            f.result()
    return out
