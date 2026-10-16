"""Every selectable look (24): an animated background plus matching colours for the header and answer bars.

Pick one in the page's "Look" section (or STYLE-less default = Bubblegum, the original pink and purple).
Backgrounds are generated once into assets/backgrounds/<key>.mp4 (a seamless loop) the first time a look is used;
delete that folder to regenerate them. The blurred-clip looks use each question's own footage instead.
"""
import random
import re
import subprocess

import backgrounds
import styles
from config import ASSETS_DIR, ffmpeg_exe
from marble import ensure_marble

BG_DIR = ASSETS_DIR / "backgrounds"
BG_DIR.mkdir(exist_ok=True)
DEFAULT = "bubblegum"
GROUPS = ["Clean, dark & illustrated", "Swirls & glow", "Patterns & scenes"]
LOOP_FRAMES, LOOP_FPS = 144, 24  # 6 second seamless loop

BLUR = {
    "blurred_dark": dict(dark=0.35, sat=0.85),
    "blurred_tint": dict(dark=0.25, sat=0.9, tint="6e32be", alpha=0.38),
}

LOOKS: dict = {}


def _add(key, title, group, bg, skin=None, blur=None):
    LOOKS[key] = dict(key=key, title=re.sub(r"\s*\(.*?\)", "", title), group=group, bg=bg, skin=skin, blur=blur)


for _k, (_title, _fn, _sk) in styles.STYLES.items():
    _key = _k.split("_", 1)[1]
    _add(_key, _title, GROUPS[0], _fn, skin=_sk, blur=BLUR.get(_key))
for _k, (_title, _fn) in backgrounds.OPTIONS.items():
    _n, _key = int(_k.split("_", 1)[0]), _k.split("_", 1)[1]
    _add(_key, _title, GROUPS[1] if _n <= 8 else GROUPS[2], (lambda f: (lambda t, sample=None: f(t)))(_fn))


def resolve(key: str) -> dict:
    """The look for a key; 'random' picks one; anything unknown falls back to the original."""
    if key == "random":
        key = random.choice(list(LOOKS))
    return LOOKS.get(key) or LOOKS[DEFAULT]


def listing() -> list:
    return [{"key": v["key"], "title": v["title"], "group": v["group"]} for v in LOOKS.values()]


def ensure_background(key: str):
    """Path of the looping background video for a look (made on first use). Bubblegum is the original marble."""
    if key == DEFAULT:
        return ensure_marble()
    path = BG_DIR / f"{key}.mp4"
    if path.exists() and path.stat().st_size > 10_000:
        return path
    fn = LOOKS[key]["bg"]
    first = fn(0.0, None)
    h, w = first.shape[:2]
    tmp = path.with_suffix(".tmp.mp4")
    cmd = [ffmpeg_exe(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(LOOP_FPS), "-i", "-", "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", str(tmp)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(LOOP_FRAMES):
            p.stdin.write(fn(i / LOOP_FRAMES, None).tobytes())
        p.stdin.close()
        err = p.stderr.read().decode(errors="ignore")
        if p.wait() != 0:
            raise RuntimeError("could not create the background: " + err[-300:])
    except BrokenPipeError:
        raise RuntimeError("could not create the background: " + p.stderr.read().decode(errors="ignore")[-300:])
    tmp.replace(path)
    return path
