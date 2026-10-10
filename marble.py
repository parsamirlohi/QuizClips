"""Generates the animated pink/purple liquid-marble background (a seamless loop), once, and caches it."""
import math

import numpy as np

from config import ASSETS_DIR, run_ffmpeg

MARBLE = ASSETS_DIR / "marble.mp4"
W, H, FPS, SECONDS = 406, 720, 30, 8

# lilac -> pink -> white -> violet, blended smoothly
STOPS = np.array([
    [176, 124, 255],
    [255, 128, 208],
    [252, 236, 255],
    [150, 100, 245],
    [214, 160, 255],
    [176, 124, 255],
], dtype=np.float32)


def _palette(v):
    v = np.clip(v, 0, 0.9999) * (len(STOPS) - 1)
    i = v.astype(int)
    f = (v - i)[..., None]
    f = f * f * (3 - 2 * f)
    return STOPS[i] * (1 - f) + STOPS[i + 1] * f


def _frame(t):
    """t in [0,1): phase of the loop. Domain-warped sine fields give a liquid-paint look."""
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    x, y = xs / W * 3.2, ys / H * 5.6
    ph = 2 * math.pi * t
    for k in range(3):
        x2 = x + 0.9 * np.sin(1.3 * y + ph + k * 1.7)
        y2 = y + 0.9 * np.cos(1.1 * x + ph * (1 if k % 2 == 0 else -1) + k)
        x, y = x2, y2
    v = 0.5 + 0.25 * np.sin(1.7 * x + 0.8 * y + ph) + 0.25 * np.sin(1.2 * y - 0.6 * x - ph)
    return _palette(v).astype(np.uint8)


def ensure_marble():
    """Create assets/marble.mp4 if missing. Takes a few seconds the first time."""
    if MARBLE.exists() and MARBLE.stat().st_size > 10_000:
        return MARBLE
    import imageio

    tmp = MARBLE.with_suffix(".tmp.mp4")
    n = FPS * SECONDS
    writer = imageio.get_writer(str(tmp), fps=FPS, codec="libx264", macro_block_size=1,
                                ffmpeg_params=["-crf", "16"])
    try:
        for i in range(n):
            writer.append_data(_frame(i / n))
    finally:
        writer.close()
    tmp.replace(MARBLE)
    return MARBLE


if __name__ == "__main__":
    print(ensure_marble())
