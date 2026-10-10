"""Finds and downloads background stock videos from Pixabay (default) or Pexels."""
import random
import time

import requests

from config import CACHE_DIR, env, is_mock, run_ffmpeg

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


def _find_pixabay(queries: list, used: set):
    key = env("PIXABAY_API_KEY")
    if not key:
        raise RuntimeError("PIXABAY_API_KEY is missing. Get a free key at pixabay.com/api/docs and put it in .env")
    for q in queries:
        hits = [h for h in _pixabay_hits(q, key) if h["id"] not in used and h.get("duration", 0) >= 4]
        print(f"[footage] searched '{q}': {len(hits)} usable results", flush=True)
        if not hits:
            continue
        h = random.choice(hits[:12])
        sizes = h.get("videos", {})
        f = next((sizes[k] for k in ("medium", "large", "small") if sizes.get(k, {}).get("url")), None)
        if not f:
            continue
        dest = CACHE_DIR / f"pixabay_{h['id']}.mp4"
        if not dest.exists():
            _download(f["url"], dest)
        used.add(h["id"])
        print(f"[footage]   -> picked video tagged: {h.get('tags', '')}", flush=True)
        return dest, f"{q}  ->  video tags: {h.get('tags', '')[:60]}"
    raise RuntimeError(f"No Pixabay videos found for any of: {queries}")


def find_background(queries: list, used: set):
    """Return a local path to a video matching the first query that has results."""
    if is_mock():
        return _mock_clip(), queries[0] if queries else "mock"
    src = _source()
    if src is None:
        raise RuntimeError("No video API key found. Add PEXELS_API_KEY or PIXABAY_API_KEY to the .env file.")
    if src == "pixabay":
        return _find_pixabay(queries, used)
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
