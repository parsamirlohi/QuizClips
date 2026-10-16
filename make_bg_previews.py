"""Draws every background option from backgrounds.py under the real quiz overlay -> bg_options/*.png + sheet.png.
Run:  python3 make_bg_previews.py"""
import subprocess

import imageio_ffmpeg
from PIL import Image, ImageDraw

import backgrounds
import render
from config import BASE, OUTPUT_DIR

OUT = BASE / "bg_options"
OUT.mkdir(exist_ok=True)

# a real stock-clip picture for the clip window: a frame from your newest video
vids = sorted(OUTPUT_DIR.glob("quiz_*.mp4"), key=lambda p: p.stat().st_mtime)
sample = None
if vids:
    tmp = OUT / "_sample.jpg"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error", "-ss", "12", "-i", str(vids[-1]),
                    "-frames:v", "1", str(tmp)])
    if tmp.exists():
        sample = Image.open(tmp).convert("RGB").crop(render.CLIP)

overlay = render.draw_scene(theme="purple", header="Which animal is known as the king of the jungle?",
                            label="QUESTION 1/5", choices=["Tiger", "Lion", "Leopard", "Cheetah"],
                            visible=4, anim=1.0, q_num=1, num_label="1")

shots = []
for key, (title, fn) in backgrounds.OPTIONS.items():
    bg = Image.fromarray(fn(0.3)).resize((1080, 1920), Image.BICUBIC).convert("RGBA")
    if sample:
        bg.paste(sample, render.CLIP[:2])
    bg.alpha_composite(overlay)
    bg = bg.convert("RGB")
    bg.save(OUT / f"{key}.png")
    shots.append((title, bg))
    print("made", key, flush=True)

tw, th, pad, lab = 360, 640, 24, 56
cols = 4
for sheet_no in range(0, len(shots), 8):
    chunk = shots[sheet_no:sheet_no + 8]
    rows = (len(chunk) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * pad, rows * (th + lab) + (rows + 1) * pad), (24, 24, 30))
    d = ImageDraw.Draw(sheet)
    for i, (title, im) in enumerate(chunk):
        x = pad + (i % cols) * (tw + pad)
        y = pad + (i // cols) * (th + lab + pad)
        sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y + lab))
        d.text((x, y + 16), f"{sheet_no + i + 1}. {title}", font=render.font(30), fill=(255, 255, 255))
    sheet.save(OUT / ("sheet.png" if sheet_no == 0 else f"sheet{sheet_no // 8 + 1}.png"))
print("done")
