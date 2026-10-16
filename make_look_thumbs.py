"""Makes the little preview pictures shown in the page's Look selector -> static/looks/<key>.jpg.
Run:  python3 make_look_thumbs.py   (only needed again if you add or change a look)"""
import math

from PIL import Image, ImageDraw, ImageFilter

import looks
import render
from config import BASE

OUT = BASE / "static" / "looks"
OUT.mkdir(parents=True, exist_ok=True)


def placeholder_clip(w, h):
    """A neutral landscape standing in for the stock footage."""
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


cw, ch = render.CLIP[2] - render.CLIP[0], render.CLIP[3] - render.CLIP[1]
clip = placeholder_clip(cw, ch)
for key, look in looks.LOOKS.items():
    render.apply_skin(look["skin"])
    overlay = render.draw_scene(theme="purple", header="Which animal is known as the king of the jungle?",
                                label="QUESTION 1/5", choices=["Tiger", "Lion", "Leopard", "Cheetah"],
                                visible=4, anim=1.0, q_num=1, num_label="1")
    bg = Image.fromarray(look["bg"](0.3, clip)).resize((1080, 1920), Image.BICUBIC).convert("RGBA")
    bg.paste(clip, render.CLIP[:2])
    bg.alpha_composite(overlay)
    bg.convert("RGB").resize((270, 480), Image.LANCZOS).save(OUT / f"{key}.jpg", quality=88)
    print("thumb", key, flush=True)
render.reset_skin()
