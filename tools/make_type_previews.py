"""Makes the Studio phone previews for the video types other than trivia and Story.

Every look already has a looping video of its moving background and stock clip (static/looks/loops/hd/<key>.mp4, see
make_look_loops.py). Each video type lays its own graphics over that video:

  static/looks/overlay/<type>/<key>.webp   the graphics of that type in that look's colors (personality, wyr, toplist, facts)
  static/looks/loops/bg/<key>.mp4          the look's moving background alone (What's missing); bgstill/<key>.jpg is its first frame
  static/looks/hdbg/<key>.jpg              the first frame of the look's loop, without graphics (shown while the video loads)

Trivia uses static/looks/overlay/<key>.webp and Story uses static/looks/story/ (make_story_preview.py).

Run:  python3 tools/make_type_previews.py          (needs the files from make_look_loops.py first)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import looks
import previews
import render
from config import BASE, run_ffmpeg

LOOKS_DIR = BASE / "static" / "looks"

if __name__ == "__main__":
    render.WATERMARK = ""
    (LOOKS_DIR / "hdbg").mkdir(exist_ok=True)
    (LOOKS_DIR / "bgstill").mkdir(exist_ok=True)
    (LOOKS_DIR / "loops" / "bg").mkdir(parents=True, exist_ok=True)
    for kind in ('odd', 'personality', 'wyr', 'toplist', 'facts', 'clip', 'missing'):
        (LOOKS_DIR / "overlay" / kind).mkdir(parents=True, exist_ok=True)
    for key, look in looks.LOOKS.items():
        video = LOOKS_DIR / "loops" / "hd" / f"{key}.mp4"
        if video.exists():
            run_ffmpeg(["-i", str(video), "-frames:v", "1", "-q:v", "3", str(LOOKS_DIR / "hdbg" / f"{key}.jpg")])
        for kind in ("odd", "personality", "wyr", "toplist", "facts", "clip", "missing"):
            previews.draw(kind, key).save(LOOKS_DIR / "overlay" / kind / f"{key}.webp", lossless=True, method=6)
        bgv = LOOKS_DIR / "loops" / "bg" / f"{key}.mp4"
        run_ffmpeg(["-stream_loop", "-1", "-i", str(looks.ensure_background(key)), "-t", "6", "-an", "-vf",
                    "scale=720:1280:flags=bicubic,fps=24", "-c:v", "libx264", "-crf", "27", "-preset", "slow",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(bgv)])
        run_ffmpeg(["-i", str(bgv), "-frames:v", "1", "-q:v", "3", str(LOOKS_DIR / "bgstill" / f"{key}.jpg")])
        print("made", key, flush=True)
