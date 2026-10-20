"""Makes the preview pictures of every look used on the website and in the app.
Each look shows its own question (see preview_data.py) with a stock video clip in the picture box.

Run:    python3 tools/make_look_thumbs.py --clips     (first time: downloads one short Pixabay clip per look, needs PIXABAY_API_KEY)
Later:  python3 tools/make_look_thumbs.py              (re-draws the pictures with the clips it already has)

Writes:
  static/looks/<key>.jpg          270x480, for the look picker in the app
  static/looks/hd/<key>.webp      1080x1920, for the big phone
  static/looks/strip/<key>.webp   444x790, for the scrolling strip
  static/looks/clips/<key>.mp4    short silent loop that plays inside the big phone's picture box on the home page
  static/looks/clips/<key>.jpg    one frame of that clip, drawn into the pictures above
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so the app's modules import from here
import math
import sys

from PIL import Image, ImageDraw, ImageFilter

import looks
import preview_data
import render
from config import BASE, run_ffmpeg

OUT = BASE / "static" / "looks"
OUT.mkdir(parents=True, exist_ok=True)
HD = OUT / "hd"          # full-size pictures for the big phone on the home page (shown one at a time)
HD.mkdir(exist_ok=True)
STRIP = OUT / "strip"    # 3x the size of the tiles in the scrolling strip: sharp, and not shrunk so far that it shimmers
STRIP.mkdir(exist_ok=True)
CLIPS = OUT / "clips"    # the stock-video loops and one frame of each
CLIPS.mkdir(exist_ok=True)

cw, ch = render.CLIP[2] - render.CLIP[0], render.CLIP[3] - render.CLIP[1]
VW, VH = 520, 280        # size of the loop that plays on the home page (the picture box is 650x350 in the 1080x1920 picture)


def placeholder_clip(w, h):
    """A neutral landscape standing in for the stock footage when a look has no clip yet."""
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=(int(250 - 90 * k), int(170 - 40 * k), int(120 + 60 * k)))
    d.ellipse([w * 0.62, h * 0.18, w * 0.62 + 90, h * 0.18 + 90], fill=(255, 238, 190))
    for col, base, amp, f, ph in (((86, 80, 130), 0.62, 38, 1.3, 0.5), ((52, 52, 100), 0.78, 30, 2.1, 2.2),
                                  ((28, 30, 70), 0.92, 18, 3.0, 4.0)):
        pts = [(x, int(h * base + amp * math.sin(2 * math.pi * x / w * f + ph))) for x in range(0, w + 8, 8)]
        d.polygon(pts + [(w, h), (0, h)], fill=col)
    return im.filter(ImageFilter.GaussianBlur(0.6))


def fetch_clips():
    """One stock clip per look, found the same way the app finds footage for a question."""
    import videos
    used = set()
    for key, p in preview_data.PREVIEWS.items():
        mp4, still = CLIPS / f"{key}.mp4", CLIPS / f"{key}.jpg"
        if mp4.exists() and still.exists():
            print("clip already there:", key, flush=True)
            continue
        try:
            src, found = videos.find_background(list(p["search"]), used, p["q"])
        except Exception as e:
            print(f"no clip for {key}: {str(e)[:120]}", flush=True)
            continue
        fit = "force_original_aspect_ratio=increase"
        run_ffmpeg(["-i", src, "-t", "4", "-vf", f"scale={VW}:{VH}:{fit},crop={VW}:{VH},fps=24", "-an",
                    "-c:v", "libx264", "-crf", "27", "-preset", "slow", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(mp4)])
        run_ffmpeg(["-ss", "1", "-i", src, "-frames:v", "1", "-vf", f"scale={cw}:{ch}:{fit},crop={cw}:{ch}",
                    "-q:v", "2", str(still)])
        print(f"clip {key}: {found}", flush=True)


if "--clips" in sys.argv:
    fetch_clips()

fallback = placeholder_clip(cw, ch)
render.BORDER_RADIUS = render.PREVIEW_RADIUS   # rounded border: these pictures sit in the phone preview
for key, look in looks.LOOKS.items():
    p = preview_data.PREVIEWS[key]
    still = CLIPS / f"{key}.jpg"
    clip = Image.open(still).convert("RGB").resize((cw, ch), Image.LANCZOS) if still.exists() else fallback
    render.apply_skin(look["skin"])
    overlay = render.draw_scene(theme="purple", header=p["q"], label="QUESTION 1/5", choices=list(p["a"]),
                                visible=4, anim=1.0, q_num=1, num_label="1")
    bg = Image.fromarray(look["bg"](0.3, clip)).resize((1080, 1920), Image.BICUBIC).convert("RGBA")
    bg.paste(clip, render.CLIP[:2])
    bg.alpha_composite(overlay)
    full = bg.convert("RGB")
    full.resize((270, 480), Image.LANCZOS).save(OUT / f"{key}.jpg", quality=88)      # look picker in the app
    full.save(HD / f"{key}.webp", quality=95, method=6)                               # 1080x1920
    full.resize((444, 790), Image.LANCZOS).save(STRIP / f"{key}.webp", quality=95, method=6)
    print("thumb", key, "(with clip)" if still.exists() else "(placeholder picture)", flush=True)
render.reset_skin()
