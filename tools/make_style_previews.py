"""Draws every look option from styles.py under the real quiz overlay -> bg_options/styles_sheet.png (+ one png each).
Run:  python3 tools/make_style_previews.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so the app's modules import from here
import subprocess

import imageio_ffmpeg
from PIL import Image, ImageDraw

import render
import styles
from config import BASE, OUTPUT_DIR

OUT = BASE / "bg_options"
OUT.mkdir(exist_ok=True)
vids = sorted(OUTPUT_DIR.glob("quiz_*.mp4"), key=lambda p: p.stat().st_mtime)
sample = None
if vids:
    tmp = OUT / "_sample.jpg"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error", "-ss", "12", "-i", str(vids[-1]),
                    "-frames:v", "1", str(tmp)])
    if tmp.exists():
        sample = Image.open(tmp).convert("RGB").crop(render.CLIP)

orig = (dict(render.THEMES["purple"]), dict(render.BAR_STYLES["purple"]), render.HOT)
shots = []
for key, (title, fn, sk) in styles.STYLES.items():
    render.THEMES["purple"] = sk["theme"]
    render.BAR_STYLES["purple"] = sk["bar"]
    render.HOT = sk["accent"]
    overlay = render.draw_scene(theme="purple", header="Which animal is known as the king of the jungle?",
                                label="QUESTION 1/5", choices=["Tiger", "Lion", "Leopard", "Cheetah"],
                                visible=4, anim=1.0, q_num=1, num_label="1")
    bg = Image.fromarray(fn(0.3, sample)).resize((1080, 1920), Image.BICUBIC).convert("RGBA")
    if sample:
        bg.paste(sample, render.CLIP[:2])
    bg.alpha_composite(overlay)
    bg = bg.convert("RGB")
    bg.save(OUT / f"style_{key}.png")
    shots.append((title, bg))
    print("made", key, flush=True)
render.THEMES["purple"], render.BAR_STYLES["purple"], render.HOT = orig

tw, th, pad, lab, cols = 360, 640, 24, 56, 4
rows = (len(shots) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw + (cols + 1) * pad, rows * (th + lab) + (rows + 1) * pad), (24, 24, 30))
d = ImageDraw.Draw(sheet)
for i, (title, im) in enumerate(shots):
    x, y = pad + (i % cols) * (tw + pad), pad + (i // cols) * (th + lab + pad)
    sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y + lab))
    d.text((x, y + 16), f"{i + 1}. {title}", font=render.font(26), fill=(255, 255, 255))
sheet.save(OUT / "styles_sheet.png")
print("done")
