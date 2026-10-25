"""Local web app: open http://localhost:8000 and click Generate."""
import json
import re
import threading
import time
import uuid
import webbrowser

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import BASE, ENV_STATUS, OUTPUT_DIR, env, is_mock
from videos import has_video_key
from pipeline import build_quiz
import audio
import content
import emojis
import formats
import gemini
import looks
import io
from PIL import Image
import pipeline
import previews
import safety
import site_routes
from questions import CATEGORY_LABELS
import tts

app = FastAPI(title="Quizclips")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Standard browser protections on every response."""
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return resp


def _limited(e: "safety.Limited") -> HTTPException:
    return HTTPException(e.status, e.message, headers={"Retry-After": str(e.retry_after)})
jobs: dict = {}
current = {"id": None}
lock = threading.Lock()


class GenerateRequest(BaseModel):
    kind: str = Field(default="trivia", pattern="^(trivia|personality|wyr|toplist|facts|story|odd|clip|missing)$")
    topic: str = Field(default="", max_length=80)  # for every type except trivia
    questions: int = Field(default=5, ge=3, le=10)
    voice: str = Field(default="en-US-AriaNeural", max_length=60)
    timer_sound: str = Field(default="ticks", max_length=20)   # one of the ids in /api/config "timer_sounds"
    pop_sound: str = Field(default="pop", max_length=20)         # one of the ids in /api/config "pop_sounds"
    categories: list[int] = Field(default_factory=list, max_length=24)  # empty = mix of all
    style: str = Field(default=looks.DEFAULT, max_length=40)  # a look key from /api/config, or "random"
    watermark_on: bool = True
    watermark_platform: str = Field(default="tiktok", max_length=20)
    watermark_handle: str = Field(default="", max_length=60)
    story_mode: str = Field(default="path", pattern="^(path|survive)$")   # Story type: choose your path / would you survive
    custom: dict | None = None   # "I'll write it": the person's own content (see content.clean_custom for the shape)
    colors: dict[str, str] = Field(default_factory=dict, max_length=12)   # question_box, question_outline, answer_box, answer_outline, frame, highlight
    think_seconds: int | None = Field(default=None, ge=5, le=15)  # seconds viewers get to answer; None = the type's default


# the timer each video type uses unless the person picks another (read once, before any job changes them)
THINK_DEFAULTS = {"trivia": pipeline.THINK, "personality": formats.THINK_PERSONALITY, "wyr": formats.THINK_WYR, "story": formats.THINK_WYR, "odd": formats.THINK_WYR, "clip": formats.THINK_WYR, "missing": formats.THINK_WYR}
THINK_CHOICES = [5, 8, 12, 15]

FORMAT_DESC = {
    "personality": "Answers add up to a result that tells viewers who they are.",
    "story": "You are the hero: pick a path, or try not to fall for a trap.",
    "odd": "Four things, one doesn't belong. Can viewers spot it?",
    "clip": "A blocky video gets sharper every second. Can viewers guess what it is?",
    "missing": "Memorize the pictures. One disappears. Can viewers say which?",
    "wyr": "Two tempting options, a countdown, then what each pick says.",
    "toplist": "A countdown from the last place to number one.",
    "facts": "Short, surprising facts with a clip for each.",
}

FORMATS = [
    {"key": "trivia", "title": "Trivia quiz", "desc": "Multiple-choice questions with a reveal.", "noun": "questions",
     "min": 3, "max": 10, "default": 5, "needs_topic": False, "hint": "Space and planets",
     "examples": ["Space and planets", "Ocean animals", "90s cartoons", "World capitals", "Famous inventions", "Pizza", "Ancient Egypt", "The human body"]},
] + [
    {"key": k, "title": v["title"], "desc": d, "noun": v["noun"], "min": v["min"], "max": v["max"],
     "default": v["default"], "needs_topic": True, "hint": v["hint"], "examples": content.EXAMPLES[k]}
    for k, v in content.KINDS.items() for d in [FORMAT_DESC[k]]
]

_ORDER = ["trivia", "personality", "clip", "story", "wyr", "toplist", "facts", "missing", "odd"]
FORMATS.sort(key=lambda f: _ORDER.index(f["key"]) if f["key"] in _ORDER else 99)

for _f in FORMATS:
    _f["think_default"] = THINK_DEFAULTS.get(_f["key"])   # None = this type has no countdown
    _f["think_choices"] = THINK_CHOICES if _f["key"] in THINK_DEFAULTS else []
    _f["custom"] = True   # every type has an "I'll write it" editor
    _f["build_min"] = 1 if _f["key"] == "trivia" else _f["min"]   # fewest / most items when the person writes their own
    _f["build_max"] = 10 if _f["key"] == "trivia" else _f["max"]

PLATFORMS = {
    "tiktok": "tiktok.com/@{}",
    "youtube": "youtube.com/@{}",
    "instagram": "instagram.com/{}",
    "x": "x.com/{}",
    "facebook": "facebook.com/{}",
    "custom": "{}",
}


def watermark_text(req: GenerateRequest) -> str:
    """The text drawn at the bottom of the video ('' = no watermark)."""
    if not req.watermark_on:
        return ""
    handle = req.watermark_handle.strip()
    if req.watermark_platform != "custom":
        handle = re.sub(r"[^\w.\-]", "", handle.lstrip("@"))
    if not handle:
        return ""
    return PLATFORMS.get(req.watermark_platform, "{}").format(handle)[:60]


def run_job(job_id: str, req: GenerateRequest):
    job = jobs[job_id]

    t0 = time.time()
    phases = {}      # how long each step took, printed when the video is done (shows what is slow)
    last = [t0, ""]

    def progress(msg: str, frac: float):
        now = time.time()
        if last[1]:
            phases[last[1]] = phases.get(last[1], 0.0) + now - last[0]
        last[0], last[1] = now, re.sub(r"\s*\d+ of \d+|\.\.\.|\d+", "", msg).strip() or msg
        job["message"] = msg
        job["progress"] = round(frac, 3)

    def timing_report():
        if last[1]:
            phases[last[1]] = phases.get(last[1], 0.0) + time.time() - last[0]
        parts = ", ".join(f"{k} {v:.0f}s" for k, v in phases.items() if v >= 0.5)
        print(f"[timing] total {time.time() - t0:.0f}s: {parts}", flush=True)

    try:
        if req.think_seconds and req.kind in THINK_DEFAULTS:   # one job runs at a time, so module-level timers are safe
            if req.kind == "trivia":
                pipeline.THINK = req.think_seconds
            elif req.kind == "personality":
                formats.THINK_PERSONALITY = req.think_seconds
            else:
                formats.THINK_WYR = req.think_seconds
        cats = [c for c in req.categories if c in CATEGORY_LABELS]
        custom = content.clean_custom(req.kind, req.custom, req.story_mode) if req.custom else None
        if req.kind == "trivia" and not custom and req.topic.strip():   # trivia about a topic the person typed
            progress("Writing the questions...", 0.02)
            custom = content.trivia_questions(req.topic, req.questions)
        colors = req.colors   # the person's own colours apply to every video
        if req.kind == "trivia":
            result = build_quiz(req.questions, req.voice, progress, cats, watermark_text(req), req.style, custom, colors,
                                req.timer_sound, req.pop_sound)
        else:
            result = formats.build_video(req.kind, req.topic, req.questions, req.voice, progress, watermark_text(req),
                                         req.style, colors, custom, req.story_mode, req.timer_sound, req.pop_sound)
        timing_report()
        job.update(status="done", progress=1.0, message="Done!", video_url=f"/output/{result['file']}",
                   questions=result["questions"], duration=result["duration"])
        try:
            prune_videos()
        except Exception as e:   # tidying up must never turn a finished video into an error
            print(f"[cleanup] skipped: {e}", flush=True)
    except Exception as e:
        job.update(status="error", error=str(e), message="Failed")
        safety.refund_video(job.get("ip", ""))   # a video that failed does not count against the visitor's day
    finally:
        pipeline.THINK = THINK_DEFAULTS["trivia"]
        formats.THINK_PERSONALITY = THINK_DEFAULTS["personality"]
        formats.THINK_WYR = THINK_DEFAULTS["wyr"]
        with lock:
            current["id"] = None


@app.get("/api/preview")
def preview(request: Request, kind: str, look: str, colors: str = ""):
    """The graphics of the Studio phone preview, drawn with the person's own colors (see previews.py)."""
    if kind not in previews.KINDS or look not in looks.LOOKS:
        raise HTTPException(404, "Unknown preview.")
    try:
        safety.rate_limit("preview", safety.client_ip(request), 1500, 60, "Slow down a little: too many preview updates.")   # dragging a color picker asks for several a second
    except safety.Limited as e:
        raise _limited(e)
    try:
        picked = json.loads(colors) if colors else {}
    except ValueError:
        picked = {}
    with lock:
        if current["id"] is not None:   # a video is being made: drawing now would swap the colors it is using
            raise HTTPException(409, "A video is being made right now.")
        img = previews.draw(kind, look, picked if isinstance(picked, dict) else {})
    buf = io.BytesIO()
    img.resize((900, 1600), Image.LANCZOS).save(buf, "PNG", compress_level=1)   # the phone is small: half size is plenty, and quicker to send
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/config")
def config():
    return {
        "mock": is_mock(),
        "video_key": has_video_key(),
        "env_path": ENV_STATUS["path"],
        "env_loaded_from": ENV_STATUS["loaded_from"],
        "claude_key": bool(env("ANTHROPIC_API_KEY")),
        "gemini": gemini.available(),
        "formats": FORMATS,
        "voices": tts.available_voices(),
        "default_voice": tts.default_voice(),
        "timer_sounds": [{"id": t[0], "name": t[1], "desc": t[2]} for t in audio.TIMER_SOUNDS],
        "pop_sounds": [{"id": p[0], "name": p[1], "desc": p[2]} for p in audio.POP_SOUNDS],
        "categories": [{"id": i, "label": label} for i, label in CATEGORY_LABELS.items()],
        "looks": looks.listing(),
        "groups": looks.GROUPS,
        "default_look": looks.DEFAULT,
        "emoji": [{"theme": t, "items": [[c, n] for c, n in group.items()]} for t, group in emojis.THEMES.items()],
    }


@app.get("/api/voice-preview")
def voice_preview(voice: str):
    """A short audio sample of one narrator voice, for the Preview buttons."""
    if not re.fullmatch(r"[A-Za-z]{2,3}-[A-Za-z]{2,4}-[A-Za-z0-9\-]{2,60}|gemini:[A-Za-z]{3,20}", voice):
        raise HTTPException(400, "Unknown voice.")
    try:
        path, media = tts.preview_file(voice)
    except Exception as e:
        raise HTTPException(502, f"Could not make a sample ({str(e)[:100]}). Check your internet connection.")
    return FileResponse(path, media_type=media, headers={"Cache-Control": "no-cache"})


@app.get("/api/sound-preview")
def sound_preview(kind: str, id: str):
    """A short sample of a timer sound or an answer-choice sound, for the Preview buttons."""
    try:
        path = audio.sound_preview(kind, id)
    except ValueError:
        raise HTTPException(400, "Unknown sound.")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-cache"})


KEEP_VIDEOS = int(env("MAX_KEEP_VIDEOS", "10") or 0)   # how many of the newest videos stay in the output folder; 0 keeps them all (all video types)


def prune_videos():
    """Delete all but the newest KEEP_VIDEOS finished videos, so the output folder doesn't fill the disk."""
    if KEEP_VIDEOS <= 0:
        return
    files = sorted(OUTPUT_DIR.glob("quiz_*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP_VIDEOS:]:
        try:
            old.unlink()
            print(f"[cleanup] removed old video {old.name} (keeping the newest {KEEP_VIDEOS})", flush=True)
        except OSError as e:
            print(f"[cleanup] could not remove {old.name}: {e}", flush=True)


@app.post("/api/generate")
def generate(req: GenerateRequest, request: Request):
    ip = safety.client_ip(request)
    try:
        safety.check_paused(ip)
    except safety.Limited as e:
        raise _limited(e)
    # 1. size and content checks, before anything is started or counted
    if req.custom and len(json.dumps(req.custom)) > 60000:
        raise HTTPException(400, "That's more text than one video can hold.")
    try:
        safety.check_user_text([req.topic.strip()], "topic", ip)
        if req.watermark_on and req.watermark_handle.strip():   # drawn on the video, so it follows the rules too (a link is fine here)
            safety.check(req.watermark_handle.strip(), "watermark", ip, personal=False)
        if req.custom:
            cleaned = content.clean_custom(req.kind, req.custom, req.story_mode)   # the rules run on every field
            if isinstance(cleaned, list):
                cleaned = {"questions": cleaned}
            content.review_custom(cleaned, ip)                                      # one AI review of all of it
    except ValueError as e:   # safety.Blocked is a ValueError too
        raise HTTPException(400, str(e))
    if not has_video_key():
        raise HTTPException(400, "Add PIXABAY_API_KEY to the .env file first.")
    # 2. limits: only now does this count as a video for this visitor and for the site
    try:
        safety.start_video(ip)
    except safety.Limited as e:
        raise _limited(e)
    with lock:
        if current["id"]:
            safety.refund_video(ip)
            raise HTTPException(409, "A video is already being made. Wait for it to finish.")
        job_id = uuid.uuid4().hex[:10]
        jobs[job_id] = {"id": job_id, "status": "running", "progress": 0.0, "message": "Starting...",
                        "created": time.time(), "ip": ip}
        current["id"] = job_id
    threading.Thread(target=run_job, args=(job_id, req), daemon=True).start()
    return {k: v for k, v in jobs[job_id].items() if k != "ip"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return {k: v for k, v in jobs[job_id].items() if k != "ip"}


@app.get("/api/videos")
def videos():
    files = [p for p in OUTPUT_DIR.glob("quiz_*.mp4") if p.exists() and p.stat().st_size > 0]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return JSONResponse([{"file": p.name, "url": f"/output/{p.name}"} for p in files[:24]],
                        headers={"Cache-Control": "no-store"})   # always the videos that are on disk right now


app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/emoji", StaticFiles(directory=BASE / "assets" / "emoji"), name="emoji")   # the pictures of What's missing, shown in the editor
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


app.include_router(site_routes.router)


if __name__ == "__main__":
    import uvicorn

    print("Settings file:", ENV_STATUS["loaded_from"] or f"NOT FOUND (expected at {ENV_STATUS['path']})")
    print("Video API key:", "found" if has_video_key() else "MISSING")
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()
    threading.Thread(target=tts.prewarm_previews, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8000)
