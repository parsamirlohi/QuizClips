"""Local web app: open http://localhost:8000 and click Generate."""
import re
import threading
import time
import uuid
import webbrowser

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import BASE, ENV_STATUS, OUTPUT_DIR, env, is_mock
from videos import has_video_key
from pipeline import build_quiz
import content
import formats
import gemini
import looks
import pipeline
import site_routes
from questions import CATEGORY_LABELS
import tts

app = FastAPI(title="Quizclips")
jobs: dict = {}
current = {"id": None}
lock = threading.Lock()


class GenerateRequest(BaseModel):
    kind: str = Field(default="trivia", pattern="^(trivia|personality|wyr|toplist|facts)$")
    topic: str = Field(default="", max_length=80)  # for every type except trivia
    questions: int = Field(default=5, ge=3, le=10)
    voice: str = Field(default="en-US-AriaNeural", max_length=60)
    categories: list[int] = Field(default_factory=list, max_length=24)  # empty = mix of all
    style: str = Field(default=looks.DEFAULT, max_length=40)  # a look key from /api/config, or "random"
    watermark_on: bool = True
    watermark_platform: str = Field(default="tiktok", max_length=20)
    watermark_handle: str = Field(default="", max_length=60)
    think_seconds: int | None = Field(default=None, ge=5, le=15)  # seconds viewers get to answer; None = the type's default


# the timer each video type uses unless the person picks another (read once, before any job changes them)
THINK_DEFAULTS = {"trivia": pipeline.THINK, "personality": formats.THINK_PERSONALITY, "wyr": formats.THINK_WYR}
THINK_CHOICES = [5, 8, 12, 15]

FORMATS = [
    {"key": "trivia", "title": "Trivia quiz", "desc": "Multiple-choice questions with a reveal.", "noun": "questions",
     "min": 3, "max": 10, "default": 5, "needs_topic": False},
] + [
    {"key": k, "title": v["title"], "desc": d, "noun": v["noun"], "min": v["min"], "max": v["max"],
     "default": v["default"], "needs_topic": True, "hint": v["hint"], "examples": content.EXAMPLES[k]}
    for (k, v), d in zip(content.KINDS.items(), [
        "Answers add up to a result, like Which house are you?",
        "Two tempting options, a countdown, then what each pick says.",
        "A countdown from the last place to number one.",
        "Short, surprising facts with a clip for each.",
    ])
]

for _f in FORMATS:
    _f["think_default"] = THINK_DEFAULTS.get(_f["key"])   # None = this type has no countdown
    _f["think_choices"] = THINK_CHOICES if _f["key"] in THINK_DEFAULTS else []

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
        if req.kind == "trivia":
            result = build_quiz(req.questions, req.voice, progress, cats, watermark_text(req), req.style)
        else:
            result = formats.build_video(req.kind, req.topic, req.questions, req.voice, progress, watermark_text(req),
                                         req.style)
        timing_report()
        job.update(status="done", progress=1.0, message="Done!", video_url=f"/output/{result['file']}",
                   questions=result["questions"], duration=result["duration"])
    except Exception as e:
        job.update(status="error", error=str(e), message="Failed")
    finally:
        pipeline.THINK = THINK_DEFAULTS["trivia"]
        formats.THINK_PERSONALITY = THINK_DEFAULTS["personality"]
        formats.THINK_WYR = THINK_DEFAULTS["wyr"]
        with lock:
            current["id"] = None


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
        "default_voice": tts.DEFAULT_VOICE,
        "categories": [{"id": i, "label": label} for i, label in CATEGORY_LABELS.items()],
        "looks": looks.listing(),
        "groups": looks.GROUPS,
        "default_look": looks.DEFAULT,
    }


@app.get("/api/voice-preview")
def voice_preview(voice: str):
    """A short audio sample of one narrator voice, for the Preview buttons."""
    if not re.fullmatch(r"[A-Za-z]{2,3}-[A-Za-z]{2,4}-[A-Za-z0-9\-]{2,60}", voice):
        raise HTTPException(400, "Unknown voice.")
    try:
        path, media = tts.preview_file(voice)
    except Exception as e:
        raise HTTPException(502, f"Could not make a sample ({str(e)[:100]}). Check your internet connection.")
    return FileResponse(path, media_type=media, headers={"Cache-Control": "no-cache"})


@app.post("/api/generate")
def generate(req: GenerateRequest):
    if not has_video_key():
        raise HTTPException(400, "Add PIXABAY_API_KEY to the .env file first.")
    with lock:
        if current["id"]:
            raise HTTPException(409, "A video is already being made. Wait for it to finish.")
        job_id = uuid.uuid4().hex[:10]
        jobs[job_id] = {"id": job_id, "status": "running", "progress": 0.0, "message": "Starting...",
                        "created": time.time()}
        current["id"] = job_id
    threading.Thread(target=run_job, args=(job_id, req), daemon=True).start()
    return jobs[job_id]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]


@app.get("/api/videos")
def videos():
    files = sorted(OUTPUT_DIR.glob("quiz_*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)[:24]
    return [{"file": p.name, "url": f"/output/{p.name}"} for p in files]


app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


app.include_router(site_routes.router)


if __name__ == "__main__":
    import uvicorn

    print("Settings file:", ENV_STATUS["loaded_from"] or f"NOT FOUND (expected at {ENV_STATUS['path']})")
    print("Video API key:", "found" if has_video_key() else "MISSING")
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()
    uvicorn.run(app, host="127.0.0.1", port=8000)
