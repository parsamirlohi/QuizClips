"""Animated background options for the question scenes. Each one is a function frame(t) -> RGB uint8 array,
t in [0,1) is the phase of a seamless loop. make_bg_previews.py draws them under the real quiz overlay."""
import math

import numpy as np

W, H = 406, 720  # generated small, scaled up to 1080x1920 by ffmpeg / the preview script

PALETTES = {
    "bubblegum": [(176, 124, 255), (255, 92, 192), (252, 236, 255), (150, 100, 245), (214, 160, 255), (176, 124, 255)],
    "ocean": [(0, 119, 182), (0, 180, 216), (144, 224, 239), (240, 252, 255), (72, 149, 239), (0, 119, 182)],
    "sunset": [(255, 94, 98), (255, 153, 102), (255, 214, 102), (255, 232, 205), (255, 120, 150), (255, 94, 98)],
    "neon_night": [(20, 10, 60), (90, 30, 200), (0, 220, 255), (255, 60, 200), (40, 20, 120), (20, 10, 60)],
    "mint": [(40, 200, 140), (170, 240, 200), (250, 255, 235), (255, 236, 120), (90, 220, 170), (40, 200, 140)],
    "gold_black": [(15, 15, 15), (70, 56, 20), (212, 175, 55), (255, 236, 160), (40, 32, 12), (15, 15, 15)],
}


def _palette(stops, v):
    s = np.array(stops, dtype=np.float32)
    v = np.clip(v, 0, 0.9999) * (len(s) - 1)
    i = v.astype(int)
    f = (v - i)[..., None]
    f = f * f * (3 - 2 * f)
    return s[i] * (1 - f) + s[i + 1] * f


def marble(stops):
    """The liquid-paint look (same maths as marble.py) in any colours."""
    def frame(t):
        ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
        x, y = xs / W * 3.2, ys / H * 5.6
        ph = 2 * math.pi * t
        for k in range(3):
            x2 = x + 0.9 * np.sin(1.3 * y + ph + k * 1.7)
            y2 = y + 0.9 * np.cos(1.1 * x + ph * (1 if k % 2 == 0 else -1) + k)
            x, y = x2, y2
        v = 0.5 + 0.25 * np.sin(1.7 * x + 0.8 * y + ph) + 0.25 * np.sin(1.2 * y - 0.6 * x - ph)
        return _palette(stops, v).astype(np.uint8)
    return frame


def sunburst(t):
    """Game-show stage: blue rays slowly turning around a golden glow behind the clip."""
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy = W / 2, H * 0.42
    dx, dy = xs - cx, ys - cy
    ang = np.arctan2(dy, dx)
    r = np.sqrt(dx * dx + dy * dy) / (H * 0.6)
    rays = 0.5 + 0.5 * np.tanh(3.0 * np.sin(14 * ang + 2 * math.pi * t))
    dark, light = np.array([22, 40, 150], np.float32), np.array([60, 110, 245], np.float32)
    img = dark + (light - dark) * rays[..., None]
    glow = np.clip(1.25 - r * 1.6, 0, 1)[..., None] ** 1.6
    img = img * (1 - glow) + np.array([255, 224, 90], np.float32) * glow
    img *= (1 - 0.35 * np.clip(r - 0.5, 0, 1))[..., None]  # soft vignette
    return np.clip(img, 0, 255).astype(np.uint8)


def aurora(t):
    """Dark night sky with soft green, teal and violet light drifting slowly."""
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    u, v = xs / W, ys / H
    ph = 2 * math.pi * t
    img = np.zeros((H, W, 3), np.float32) + np.array([8, 12, 40], np.float32)
    blobs = [((0.25, 0.25), (60, 255, 170), 0), ((0.8, 0.45), (120, 90, 255), 2.1),
             ((0.35, 0.75), (40, 200, 255), 4.2), ((0.85, 0.9), (255, 90, 200), 1.0)]
    for (bx, by), col, off in blobs:
        cx = bx + 0.12 * math.sin(ph + off)
        cy = by + 0.10 * math.cos(ph + off * 1.3)
        d2 = ((u - cx) * 1.1) ** 2 + ((v - cy) * 0.62) ** 2
        img += np.exp(-d2 / 0.045)[..., None] * np.array(col, np.float32) * 0.85
    return np.clip(img, 0, 255).astype(np.uint8)


OPTIONS = {
    "1_bubblegum": ("Bubblegum (current)", marble(PALETTES["bubblegum"])),
    "2_ocean": ("Ocean", marble(PALETTES["ocean"])),
    "3_sunset": ("Sunset", marble(PALETTES["sunset"])),
    "4_neon_night": ("Neon Night", marble(PALETTES["neon_night"])),
    "5_mint": ("Mint Fresh", marble(PALETTES["mint"])),
    "6_gold_black": ("Gold & Black", marble(PALETTES["gold_black"])),
    "7_sunburst": ("Game-show Sunburst", sunburst),
    "8_aurora": ("Aurora", aurora),
}


# ---------------------------------------------------------------- more styles (different patterns, not colours)
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402


def _grid():
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    return xs, ys


def _smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def candy_stripes(t):
    """Diagonal candy stripes sliding along, with a soft glossy shine."""
    xs, ys = _grid()
    c = (xs * 0.8 + ys * 0.6) / 58.0 - t  # one stripe-pair per loop
    f = c - np.floor(c)
    band = _smooth(0.0, 0.04, f) * (1 - _smooth(0.5, 0.54, f))
    a, b = np.array([255, 110, 175], np.float32), np.array([255, 241, 246], np.float32)
    img = b + (a - b) * band[..., None]
    shine = 0.12 * np.sin(xs / W * math.pi) * (1 - ys / H)
    return np.clip(img + shine[..., None] * 255, 0, 255).astype(np.uint8)


def halftone(t):
    """Comic-book Ben-Day dots on yellow; the dots swell and shrink in waves."""
    xs, ys = _grid()
    cell = 26.0
    ang = math.radians(35)
    u = (xs * math.cos(ang) + ys * math.sin(ang)) / cell
    v = (-xs * math.sin(ang) + ys * math.cos(ang)) / cell
    du, dv = u - np.round(u), v - np.round(v)
    d = np.sqrt(du * du + dv * dv)
    wave = 0.5 + 0.5 * np.sin(2 * math.pi * (ys / H * 1.6 + xs / W * 0.6 - t))
    r = 0.12 + 0.38 * wave
    dots = 1 - _smooth(r - 0.04, r + 0.04, d)
    bg, ink = np.array([255, 224, 60], np.float32), np.array([245, 55, 105], np.float32)
    return (bg + (ink - bg) * dots[..., None]).astype(np.uint8)


def confetti(t):
    """Party confetti: coloured shapes tumbling down a violet-to-blue backdrop."""
    ys = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    top, bot = np.array([120, 60, 230], np.float32), np.array([40, 130, 255], np.float32)
    base = (top + (bot - top) * ys) * np.ones((1, W, 1), np.float32)
    im = Image.fromarray(base.astype(np.uint8)).convert("RGBA")
    rng = np.random.RandomState(7)
    cols = [(255, 214, 10), (255, 80, 150), (60, 230, 180), (255, 255, 255), (255, 140, 40), (140, 255, 90)]
    d = ImageDraw.Draw(im)
    for _ in range(70):
        x0, y0 = rng.uniform(0, W), rng.uniform(0, H)
        speed, spin = int(rng.randint(1, 3)), int(rng.choice([-2, -1, 1, 2]))
        size = rng.uniform(10, 24)
        col = cols[rng.randint(len(cols))]
        kind = rng.randint(3)
        a0 = rng.uniform(0, 6.28)
        cy = (y0 + t * H * speed) % H
        cx = x0 + 14 * math.sin(2 * math.pi * t * speed + a0)
        for oy in (0, -H):  # wrap around the bottom edge
            y = cy + oy
            ang = a0 + 2 * math.pi * t * spin
            if kind == 0:
                d.ellipse([cx - size / 2, y - size / 2, cx + size / 2, y + size / 2], fill=col + (255,))
            else:
                n = 4 if kind == 1 else 3
                pts = [(cx + size * 0.7 * math.cos(ang + k * 2 * math.pi / n + (math.pi / 4 if n == 4 else 0)),
                        y + size * (0.45 if n == 4 else 0.7) * math.sin(ang + k * 2 * math.pi / n + (math.pi / 4 if n == 4 else 0)))
                       for k in range(n)]
                d.polygon(pts, fill=col + (255,))
    return np.array(im.convert("RGB"))


def synthwave(t):
    """Retro 80s: striped sunset sun over a glowing perspective grid that rolls toward you."""
    xs, ys = _grid()
    hor = H * 0.46
    sky_t = np.clip(ys / hor, 0, 1)[..., None]
    sky = np.array([30, 8, 90], np.float32) + (np.array([255, 70, 160], np.float32) - np.array([30, 8, 90], np.float32)) * sky_t ** 1.7
    img = sky.copy()
    cx, cy, R = W / 2, hor - 18, W * 0.34
    dd = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
    sun = (dd < R) & (ys < hor)
    grad = np.clip((ys - (cy - R)) / (2 * R), 0, 1)[..., None]
    suncol = np.array([255, 235, 80], np.float32) + (np.array([255, 60, 150], np.float32) - np.array([255, 235, 80], np.float32)) * grad
    cuts = ((ys - cy) > R * 0.05) & (np.sin((ys - cy) / (R * 0.11) * math.pi) > 0.1 + 0.9 * (1 - (ys - cy) / R))
    img = np.where((sun & ~cuts)[..., None], suncol, img)
    ground = ys >= hor
    gy = np.maximum(ys - hor, 1.0)
    z = 1.0 / (gy / (H - hor) + 0.06)
    h_line = 1 - _smooth(0.0, 0.10 + 0.02 * z, np.abs(((z * 1.1 - t * 1.0) % 1.0) - 0.5) * 2 - 0.0) if False else None
    zf = (z * 0.9 - t) % 1.0
    h_line = 1 - _smooth(0.0, 0.12, np.minimum(zf, 1 - zf))
    u = (xs - W / 2) / gy * 38
    uf = u % 1.0
    v_line = 1 - _smooth(0.0, 0.10 + 0.00 * gy, np.minimum(uf, 1 - uf))
    lines = np.clip(h_line + v_line * np.clip(gy / 40, 0, 1), 0, 1)
    gcol = np.array([14, 4, 50], np.float32) + (np.array([60, 10, 120], np.float32) - np.array([14, 4, 50], np.float32)) * (gy / (H - hor))[..., None]
    gimg = gcol + (np.array([40, 240, 255], np.float32) - gcol) * lines[..., None]
    img = np.where(ground[..., None], gimg, img)
    return np.clip(img, 0, 255).astype(np.uint8)


def starfield(t):
    """Deep space: a purple nebula and layers of stars drifting past at different speeds, twinkling."""
    xs, ys = _grid()
    u, v = xs / W, ys / H
    ph = 2 * math.pi * t
    img = np.zeros((H, W, 3), np.float32) + np.array([6, 6, 28], np.float32)
    for (bx, by), col, off in [((0.3, 0.3), (110, 40, 200), 0), ((0.75, 0.65), (30, 90, 220), 2.0), ((0.4, 0.9), (200, 40, 160), 4.0)]:
        cxx, cyy = bx + 0.06 * math.sin(ph + off), by + 0.05 * math.cos(ph + off)
        img += np.exp(-(((u - cxx) * 1.0) ** 2 + ((v - cyy) * 0.55) ** 2) / 0.06)[..., None] * np.array(col, np.float32) * 0.55
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).convert("RGB")
    d = ImageDraw.Draw(im)
    rng = np.random.RandomState(3)
    for i in range(260):
        x0, y0 = rng.uniform(0, W), rng.uniform(0, H)
        layer = int(rng.choice([1, 1, 2, 3]))
        tw = 0.65 + 0.35 * math.sin(2 * math.pi * (t * layer + rng.uniform()))
        size = 0.8 + layer * 0.55
        y = (y0 + t * H * layer) % H
        c = int(255 * tw)
        col = (c, c, min(255, c + 25))
        d.ellipse([x0 - size, y - size, x0 + size, y + size], fill=col)
    return np.array(im.filter(ImageFilter.GaussianBlur(0.5)))


def bokeh(t):
    """Soft glowing light circles floating up, like blurred city lights at night."""
    ys = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    top, bot = np.array([20, 28, 90], np.float32), np.array([120, 40, 130], np.float32)
    base = (top + (bot - top) * ys) * np.ones((1, W, 1), np.float32)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rng = np.random.RandomState(11)
    cols = [(255, 190, 90), (255, 110, 170), (120, 200, 255), (200, 150, 255), (255, 240, 170)]
    for _ in range(46):
        x0, y0 = rng.uniform(0, W), rng.uniform(0, H)
        r = rng.uniform(16, 62)
        speed = int(rng.randint(1, 3))
        col = cols[rng.randint(len(cols))]
        alpha = int(rng.uniform(55, 130))
        cy = (y0 - t * H * speed) % H
        cx = x0 + 18 * math.sin(2 * math.pi * t + y0)
        for oy in (0, H):
            d.ellipse([cx - r, cy + oy - r, cx + r, cy + oy + r], fill=col + (alpha,))
            d.ellipse([cx - r, cy + oy - r, cx + r, cy + oy + r], outline=col + (min(255, alpha + 60),), width=2)
    layer = layer.filter(ImageFilter.GaussianBlur(3.2))
    out = Image.fromarray(base.astype(np.uint8)).convert("RGBA")
    out.alpha_composite(layer)
    return np.array(out.convert("RGB"))


def paper_waves(t):
    """Layered paper-cut waves in blues and teals, each layer swaying at its own pace."""
    xs, ys = _grid()
    img = np.zeros((H, W, 3), np.float32) + np.array([255, 236, 214], np.float32)
    n = 9
    cols = [(255, 190, 150), (255, 150, 140), (240, 110, 150), (190, 90, 180), (130, 90, 210),
            (80, 110, 230), (40, 140, 235), (30, 180, 225), (25, 215, 215)]
    for i in range(n):
        base = H * (0.14 + 0.095 * i)
        amp = 24 + 5 * i
        y = base + amp * np.sin(2 * math.pi * (xs / W * (1.0 + 0.35 * (i % 3)) + t * (1 if i % 2 == 0 else -1)) + i)
        shade = np.exp(-np.clip(ys - y, 0, None) / 38.0)[..., None]
        layer = np.array(cols[i], np.float32) * (0.72 + 0.28 * (1 - shade))
        img = np.where((ys >= y)[..., None], layer, img)
    return np.clip(img, 0, 255).astype(np.uint8)


def hex_grid(t):
    """Tech honeycomb: dark cells with neon edges and cells that pulse on and off."""
    xs, ys = _grid()
    s = 46.0
    px, py = xs / s, ys / s
    rx, ry = 1.0, 1.7320508
    ax, ay = np.mod(px, rx) - rx / 2, np.mod(py, ry) - ry / 2
    bx, by = np.mod(px - rx / 2, rx) - rx / 2, np.mod(py - ry / 2, ry) - ry / 2
    use_a = (ax * ax + ay * ay) < (bx * bx + by * by)
    gx, gy = np.where(use_a, ax, bx), np.where(use_a, ay, by)
    idx, idy = px - gx, py - gy
    hd = np.maximum(np.abs(gx) * 0.5 + np.abs(gy) * 0.8660254, np.abs(gx))
    edge = _smooth(0.43, 0.5, hd)
    hsh = np.abs(np.sin(idx * 12.9898 + idy * 78.233) * 43758.5453)
    hsh = hsh - np.floor(hsh)
    pulse = 0.5 + 0.5 * np.sin(2 * math.pi * (t * (1 + (hsh > 0.5)) + hsh))
    pulse = pulse ** 3
    bg = np.array([8, 12, 42], np.float32)
    cyan, mag = np.array([40, 230, 255], np.float32), np.array([255, 60, 200], np.float32)
    glow = np.where((hsh > 0.5)[..., None], cyan, mag)
    img = bg + (glow * 0.8 * pulse[..., None]) * (1 - edge[..., None] * 0.5)
    img = img + (np.array([120, 200, 255], np.float32) * 0.55) * edge[..., None]
    return np.clip(img, 0, 255).astype(np.uint8)


OPTIONS.update({
    "9_candy_stripes": ("Candy Stripes", candy_stripes),
    "10_halftone": ("Comic Halftone", halftone),
    "11_confetti": ("Confetti Party", confetti),
    "12_synthwave": ("Retro Synthwave", synthwave),
    "13_starfield": ("Deep Space", starfield),
    "14_bokeh": ("Bokeh Lights", bokeh),
    "15_paper_waves": ("Paper-cut Waves", paper_waves),
    "16_hex_grid": ("Neon Hex Grid", hex_grid),
})
