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
from questions import CATEGORY_LABELS
from tts import VOICES

app = FastAPI(title="Quiz Video Maker")
jobs: dict = {}
current = {"id": None}
lock = threading.Lock()


class GenerateRequest(BaseModel):
    questions: int = Field(default=5, ge=3, le=10)
    voice: str = Field(default="en-US-AriaNeural", max_length=60)
    categories: list[int] = Field(default_factory=list, max_length=24)  # empty = mix of all
    watermark_on: bool = True
    watermark_platform: str = Field(default="tiktok", max_length=20)
    watermark_handle: str = Field(default="", max_length=60)


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

    def progress(msg: str, frac: float):
        job["message"] = msg
        job["progress"] = round(frac, 3)

    try:
        cats = [c for c in req.categories if c in CATEGORY_LABELS]
        result = build_quiz(req.questions, req.voice, progress, cats, watermark_text(req))
        job.update(status="done", progress=1.0, message="Done!", video_url=f"/output/{result['file']}",
                   questions=result["questions"], duration=result["duration"])
    except Exception as e:
        job.update(status="error", error=str(e), message="Failed")
    finally:
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
        "voices": [{"id": v, "label": label} for v, label in VOICES],
        "categories": [{"id": i, "label": label} for i, label in CATEGORY_LABELS.items()],
    }


@app.post("/api/generate")
def generate(req: GenerateRequest):
    if not has_video_key():
        raise HTTPException(400, "Add PEXELS_API_KEY or PIXABAY_API_KEY to the .env file first.")
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


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    import uvicorn

    print("Settings file:", ENV_STATUS["loaded_from"] or f"NOT FOUND (expected at {ENV_STATUS['path']})")
    print("Video API key:", "found" if has_video_key() else "MISSING")
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()
    uvicorn.run(app, host="127.0.0.1", port=8000)
