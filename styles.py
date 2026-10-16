"""Calmer, more premium look options: each = background + matching colours for header, answer bars and border.
make_style_previews.py draws them under the real quiz overlay. A background is bg(t, sample) -> RGB uint8 array
(540x960, scaled up later); `sample` is a PIL picture of the question's own clip, used by the blurred-clip styles."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 540, 960


def _vgrad(top, bot, power=1.0):
    y = (np.linspace(0, 1, H, dtype=np.float32) ** power)[:, None, None]
    t, b = np.array(top, np.float32), np.array(bot, np.float32)
    return (t + (b - t) * y) * np.ones((1, W, 1), np.float32)


def _glow(img, cx, cy, rx, ry, col, strength):
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    g = np.exp(-(((xs / W - cx) / rx) ** 2 + ((ys / H - cy) / ry) ** 2))
    return img + g[..., None] * np.array(col, np.float32) * strength


def _u8(a):
    return np.clip(a, 0, 255).astype(np.uint8)


def _vignette(img, amount=0.35):
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xs / W - 0.5) * 1.2) ** 2 + ((ys / H - 0.5) * 0.9) ** 2)
    return img * (1 - amount * np.clip(r * 1.4 - 0.2, 0, 1))[..., None]


# ------------------------------------------------------------------------------------------------ backgrounds
def soft_cream(t, sample=None):
    img = _vgrad((252, 247, 239), (233, 222, 207))
    ph = 2 * math.pi * t
    img = _glow(img, 0.5 + 0.08 * math.sin(ph), 0.42, 0.6, 0.35, (255, 255, 255), 0.30)
    return _u8(img)


def slate_gradient(t, sample=None):
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    ph = 2 * math.pi * t
    d = (xs / W * 0.45 + ys / H * 0.9 + 0.08 * math.sin(ph))
    d = np.clip(d / 1.35, 0, 1)[..., None]
    a, b = np.array([22, 34, 64], np.float32), np.array([84, 108, 158], np.float32)
    return _u8(a + (b - a) * d)


def midnight_gold(t, sample=None):
    img = _vgrad((6, 9, 22), (18, 26, 58), 1.2)
    ph = 2 * math.pi * t
    img = _glow(img, 0.5, 0.42, 0.55, 0.28, (255, 196, 90), 0.22 + 0.05 * math.sin(ph))
    return _u8(_vignette(img, 0.4))


def obsidian_pink(t, sample=None):
    img = _vgrad((9, 6, 16), (30, 11, 44), 1.3)
    ph = 2 * math.pi * t
    img = _glow(img, 0.2 + 0.05 * math.sin(ph), 0.08, 0.7, 0.3, (255, 70, 170), 0.30)
    img = _glow(img, 0.85, 0.95, 0.7, 0.3, (150, 80, 255), 0.30 + 0.05 * math.cos(ph))
    return _u8(_vignette(img, 0.3))


def flat_hills(t, sample=None):
    img = _vgrad((255, 218, 196), (205, 176, 226), 0.9)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    sx, sy, sr = W * 0.3, H * 0.27, 70
    for r, a in ((sr * 2.6, 40), (sr * 1.9, 70), (sr * 1.35, 120)):
        d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(255, 236, 205, a))
    d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(255, 245, 224, 255))
    rng = np.random.RandomState(5)
    for _ in range(6):  # clouds drifting right, wrapping seamlessly
        cx0, cy, s = rng.uniform(0, W), rng.uniform(0.08, 0.42) * H, rng.uniform(34, 62)
        cx = (cx0 + t * (W + 240)) % (W + 240) - 120
        for dx, dy, k in ((-1.0, 0.1, 0.8), (-0.35, -0.25, 1.0), (0.35, -0.1, 1.05), (1.0, 0.1, 0.75)):
            d.ellipse([cx + dx * s - s * k * 0.8, cy + dy * s - s * k * 0.55,
                       cx + dx * s + s * k * 0.8, cy + dy * s + s * k * 0.55], fill=(255, 255, 255, 215))
    base = Image.fromarray(_u8(img)).convert("RGBA")
    base.alpha_composite(layer)
    d2 = ImageDraw.Draw(base)
    xs = np.arange(0, W + 1, 4)
    for i, (col, y0, amp, f, ph) in enumerate([((178, 146, 206), 0.62, 38, 1.1, 0.4), ((140, 112, 188), 0.72, 34, 1.5, 2.0),
                                              ((104, 84, 162), 0.83, 30, 1.9, 4.1), ((74, 62, 138), 0.93, 22, 2.4, 1.2)]):
        pts = [(int(x), int(H * y0 + amp * math.sin(2 * math.pi * (x / W * f) + ph))) for x in xs]
        d2.polygon(pts + [(W, H), (0, H)], fill=col + (255,))
    return np.array(base.convert("RGB"))


def night_skyline(t, sample=None):
    img = _vgrad((10, 14, 40), (70, 46, 120), 1.4)
    im = Image.fromarray(_u8(img)).convert("RGB")
    d = ImageDraw.Draw(im)
    rng = np.random.RandomState(9)
    for _ in range(90):
        x, y = rng.uniform(0, W), rng.uniform(0, H * 0.7)
        tw = 0.5 + 0.5 * math.sin(2 * math.pi * (t * int(rng.randint(1, 3)) + rng.uniform()))
        c = int(120 + 135 * tw)
        d.ellipse([x - 1.3, y - 1.3, x + 1.3, y + 1.3], fill=(c, c, min(255, c + 20)))
    mx, my = W * 0.8, H * 0.13
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r, a in ((90, 22), (62, 40), (44, 70)):
        gd.ellipse([mx - r, my - r, mx + r, my + r], fill=(255, 236, 190, a))
    gd.ellipse([mx - 30, my - 30, mx + 30, my + 30], fill=(255, 246, 222, 255))
    gd.ellipse([mx - 12, my - 6, mx + 6, my + 12], fill=(238, 224, 196, 120))
    im = Image.alpha_composite(im.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(1.2)))
    d = ImageDraw.Draw(im)
    x = -10
    while x < W:
        bw = int(rng.randint(30, 62))
        bh = int(rng.randint(60, 190))
        d.rectangle([x, H - bh, x + bw, H], fill=(9, 11, 30, 255))
        for wy in range(H - bh + 12, H - 12, 22):
            for wx in range(x + 7, x + bw - 8, 14):
                if rng.rand() < 0.5:
                    blink = math.sin(2 * math.pi * (t * int(rng.randint(1, 3)) + rng.uniform())) > 0.8
                    if not blink:
                        d.rectangle([wx, wy, wx + 5, wy + 8], fill=(255, 214, 120, 235))
        x += bw + int(rng.randint(2, 8))
    return np.array(im.convert("RGB"))


def _blurred_clip(t, sample, tint=None, dark=0.45):
    if sample is None:
        return _u8(_vgrad((30, 30, 40), (10, 10, 16)))
    im = sample.convert("RGB")
    sw, sh = im.size
    s = max(W / sw, H / sh) * 1.12
    im = im.resize((int(sw * s), int(sh * s)), Image.BICUBIC)
    drift = 0.5 + 0.5 * math.sin(2 * math.pi * t)  # slow pan, loops
    ox = int((im.width - W) * (0.35 + 0.3 * drift))
    oy = (im.height - H) // 2
    im = im.crop((ox, oy, ox + W, oy + H)).filter(ImageFilter.GaussianBlur(26))
    a = np.array(im, np.float32) * dark
    if tint:
        a = a * 0.62 + np.array(tint, np.float32) * 0.38
    return _u8(_vignette(a, 0.3))


def blurred_clip_dark(t, sample=None):
    return _blurred_clip(t, sample)


def blurred_clip_tint(t, sample=None):
    return _blurred_clip(t, sample, tint=(110, 50, 190), dark=0.55)


# ------------------------------------------------------------------------------------------------ colour skins
# header fill/line, answer-bar fill/line/text, letter circle, border/timer colour, number accent
def skin(hfill, hline, bfill, bline, btext, circ, circ_line, letter, border, accent):
    return dict(theme=dict(fill=hfill, line=hline, border=border),
                bar=dict(fill=bfill, line=bline, text=btext, circ=circ, circ_line=circ_line, letter=letter),
                accent=accent)


GOLD, NAVY = (201, 162, 74), (24, 34, 62)
STYLES = {
    "1_soft_cream": ("Soft Cream (minimal)", soft_cream,
                     skin(NAVY, GOLD, (255, 255, 255), GOLD, NAVY, GOLD, (255, 255, 255), (255, 255, 255), GOLD, GOLD)),
    "2_slate": ("Slate Gradient (minimal)", slate_gradient,
                skin((12, 20, 42), (125, 211, 252), (243, 247, 252), (125, 211, 252), (12, 20, 42),
                     (56, 189, 248), (255, 255, 255), (255, 255, 255), (125, 211, 252), (56, 189, 248))),
    "3_midnight_gold": ("Midnight Gold (dark)", midnight_gold,
                        skin((10, 15, 36), (230, 184, 92), (12, 18, 40), (230, 184, 92), (255, 236, 184),
                             (230, 184, 92), (255, 236, 184), (12, 18, 40), (230, 184, 92), (230, 184, 92))),
    "4_obsidian_pink": ("Obsidian + Pink (dark)", obsidian_pink,
                        skin((34, 16, 58), (255, 78, 178), (255, 255, 255), (255, 78, 178), (246, 36, 140),
                             (255, 78, 178), (255, 255, 255), (255, 255, 255), (255, 78, 178), (246, 36, 140))),
    "5_flat_hills": ("Flat Hills (illustrated)", flat_hills,
                     skin((62, 50, 120), (255, 196, 150), (255, 251, 246), (255, 196, 150), (62, 50, 120),
                          (255, 170, 120), (255, 255, 255), (255, 255, 255), (255, 196, 150), (255, 170, 120))),
    "6_night_skyline": ("Night Skyline (illustrated)", night_skyline,
                        skin((16, 24, 60), (255, 214, 120), (20, 30, 68), (255, 214, 120), (255, 255, 255),
                             (255, 214, 120), (255, 255, 255), (20, 30, 68), (255, 214, 120), (255, 214, 120))),
    "7_blurred_dark": ("Blurred Clip, dark (footage)", blurred_clip_dark,
                       skin((18, 18, 26), (235, 235, 240), (255, 255, 255), (255, 255, 255), (18, 18, 26),
                            (18, 18, 26), (255, 255, 255), (255, 255, 255), (255, 255, 255), (235, 235, 240))),
    "8_blurred_tint": ("Blurred Clip, purple glow (footage)", blurred_clip_tint,
                       skin((98, 74, 220), (255, 78, 178), (255, 255, 255), (255, 78, 178), (246, 36, 140),
                            (255, 78, 178), (255, 255, 255), (255, 255, 255), (255, 78, 178), (246, 36, 140))),
}
