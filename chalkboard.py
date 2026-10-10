"""Generates a static chalkboard image (assets/chalkboard.png) for the intro, once, and caches it."""
import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import ASSETS_DIR

CHALK = ASSETS_DIR / "chalkboard.png"
W, H = 1080, 1920
SYMS = ["E = mc²", "π", "∑", "√x", "x² + y² = z²", "a² + b²", "∫ f(x)dx", "Δ", "sin θ", "H₂O", "F = ma", "∞",
        "log n", "7 × 8", "2πr", "θ", "λ", "(a+b)²", "1 + 1 = 2", "ħ", "e^iπ + 1 = 0", "ΔG", "CO₂", "n!"]
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
         "/System/Library/Fonts/Supplemental/Arial.ttf", "C:/Windows/Fonts/arial.ttf"]


def _font(size):
    for p in FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def ensure_chalkboard():
    if CHALK.exists() and CHALK.stat().st_size > 10_000:
        return CHALK
    rnd = random.Random(11)
    rng = np.random.default_rng(11)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    # green-grey board with a soft light patch and vignette
    base = np.array([58, 86, 70], dtype=np.float32)
    light = 1.0 + 0.22 * np.exp(-(((xx - W * 0.45) / 700) ** 2 + ((yy - H * 0.35) / 900) ** 2))
    vig = 1.0 - 0.38 * (((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.75)) ** 2)
    img = base[None, None, :] * (light * vig)[..., None]
    img += rng.normal(0, 4.5, (H, W, 1))
    board = Image.fromarray(np.clip(img, 0, 255).astype("uint8")).convert("RGBA")

    chalk = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(chalk)
    for _ in range(26):  # eraser smudges
        x, y = rnd.randint(-100, W), rnd.randint(0, H)
        w, h = rnd.randint(220, 620), rnd.randint(40, 130)
        d.ellipse((x, y, x + w, y + h), fill=(235, 240, 235, rnd.randint(14, 34)))
    chalk = chalk.filter(ImageFilter.GaussianBlur(26))
    d = ImageDraw.Draw(chalk)
    for _ in range(46):  # chalk formulas
        txt = rnd.choice(SYMS)
        f = _font(rnd.randint(60, 150))
        layer = Image.new("RGBA", (900, 260), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((20, 30), txt, font=f, fill=(240, 244, 240, rnd.randint(110, 190)))
        layer = layer.rotate(rnd.randint(-22, 22), expand=True, resample=Image.BICUBIC)
        chalk.alpha_composite(layer, (rnd.randint(-120, W - 250), rnd.randint(-20, H - 200)))
    d = ImageDraw.Draw(chalk)
    for _ in range(70):  # loose scribble lines and arcs
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        a = rnd.random() * math.tau
        L = rnd.randint(120, 520)
        col = (240, 244, 240, rnd.randint(70, 140))
        if rnd.random() < 0.5:
            d.line((x, y, x + math.cos(a) * L, y + math.sin(a) * L), fill=col, width=rnd.randint(3, 6))
        else:
            r = rnd.randint(60, 200)
            d.arc((x, y, x + r, y + r), rnd.randint(0, 360), rnd.randint(0, 360), fill=col, width=rnd.randint(3, 6))
    # rough up the chalk so it looks grainy rather than vector-clean
    a = np.array(chalk.getchannel("A"), dtype=np.float32)
    a *= np.clip(rng.normal(0.8, 0.28, a.shape), 0.25, 1.0)
    chalk.putalpha(Image.fromarray(a.astype("uint8")))
    board.alpha_composite(chalk.filter(ImageFilter.GaussianBlur(0.8)))
    board.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 55)))  # darken so text pops
    tmp = CHALK.with_suffix(".tmp.png")
    board.convert("RGB").save(tmp, "PNG", optimize=True)
    tmp.replace(CHALK)
    return CHALK


if __name__ == "__main__":
    print(ensure_chalkboard())
