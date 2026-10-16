"""Paths, settings loaded from .env, and ffmpeg helpers."""
import os
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUTPUT_DIR = BASE / "output"
CACHE_DIR = BASE / "cache"
WORK_DIR = BASE / "work"
ASSETS_DIR = BASE / "assets"
for _d in (OUTPUT_DIR, CACHE_DIR, WORK_DIR, ASSETS_DIR):
    _d.mkdir(exist_ok=True)


ENV_STATUS = {"path": str(BASE / ".env"), "loaded_from": None}


def _load_env_file():
    # Also accept ".env.txt": Notepad adds .txt unless the file type is set to "All files".
    for name in (".env", ".env.txt"):
        f = BASE / name
        if f.exists():
            break
    else:
        return
    ENV_STATUS["loaded_from"] = str(f)
    for line in f.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().lstrip("﻿")
        if k.lower().startswith("export "):
            k = k[7:].strip()
        v = v.strip().strip('"').strip("'")
        if v and not os.environ.get(k):
            os.environ[k] = v


_load_env_file()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def is_mock() -> bool:
    """MOCK=1 runs everything offline with fake questions, backgrounds and voice."""
    return env("MOCK") == "1"


def ffmpeg_exe() -> str:
    custom = env("FFMPEG_PATH")
    if custom:
        return custom
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
    raise RuntimeError("ffmpeg not found. Run: pip install imageio-ffmpeg")


def run_ffmpeg(args: list) -> None:
    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error"] + [str(a) for a in args]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + (p.stderr or "")[-1500:])


def flog(msg: str) -> None:
    """Print a footage decision and also append it to footage.log (so it can be reviewed after the fact)."""
    print(msg, flush=True)
    try:
        import time as _t
        with open(BASE / "footage.log", "a", encoding="utf-8") as f:
            f.write(f"{_t.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass
