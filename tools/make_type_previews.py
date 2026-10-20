"""Makes the Studio phone previews for the video types other than trivia and Story.

Every look already has a looping video of its moving background and stock clip (static/looks/loops/hd/<key>.mp4, see
make_look_loops.py). Each video type lays its own graphics over that video:

  static/looks/overlay/<type>/<key>.webp   the graphics of that type in that look's colors (personality, wyr, toplist, facts)
  static/looks/hdbg/<key>.jpg              the first frame of the look's loop, without graphics (shown while the video loads)

Trivia uses static/looks/overlay/<key>.webp and Story uses static/looks/story/ (make_story_preview.py).

Run:  python3 tools/make_type_previews.py          (needs the files from make_look_loops.py first)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import looks
import preview_data
import render
from config import BASE, run_ffmpeg

LOOKS_DIR = BASE / "static" / "looks"

def scenes(key):
    """This look's example for each type: (how to draw it, arguments). The text matches the look's stock clip."""
    t = preview_data.TYPE_PREVIEWS[key]
    q, answers = t["personality"]
    a, b = t["wyr"]
    name, rank, line = t["toplist"]
    head, fact = t["facts"]
    return {
        "personality": ("scene", dict(header=q, label="QUESTION 1/5", visible=4, anim=1.0, num_label="1", choices=answers)),
        "wyr": ("scene", dict(header="WOULD YOU RATHER...", label="ROUND 1/5", visible=2, anim=1.0, num_label="1", letters="AB",
                              bar_dy=150, choices=[a, b])),
        "toplist": ("card", dict(header=name, label=f"#{rank}", badge=str(rank), caption=line)),
        "facts": ("card", dict(header=head, label="FACT 1", badge="1", caption=fact)),
    }


if __name__ == "__main__":
    render.WATERMARK = ""
    (LOOKS_DIR / "hdbg").mkdir(exist_ok=True)
    for kind in ('personality', 'wyr', 'toplist', 'facts'):
        (LOOKS_DIR / "overlay" / kind).mkdir(parents=True, exist_ok=True)
    for key, look in looks.LOOKS.items():
        video = LOOKS_DIR / "loops" / "hd" / f"{key}.mp4"
        if video.exists():
            run_ffmpeg(["-i", str(video), "-frames:v", "1", "-q:v", "3", str(LOOKS_DIR / "hdbg" / f"{key}.jpg")])
        render.apply_skin(look["skin"])
        for kind, (how, args) in scenes(key).items():
            img = render.draw_scene(theme="purple", **args) if how == "scene" else render.draw_card(theme="purple", **args)
            img.save(LOOKS_DIR / "overlay" / kind / f"{key}.webp", lossless=True, method=6)
        print("made", key, flush=True)
    render.reset_skin()
