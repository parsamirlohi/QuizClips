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


def default_colors(look: dict) -> dict:
    """The look's own colours as #rrggbb, so the Studio page can show them before the person changes anything."""
    s = look.get("skin") or {}
    th = s.get("theme") or dict(fill=(112, 84, 240), line=(255, 78, 178), border=(255, 78, 178))
    bar = s.get("bar") or dict(fill=(255, 255, 255), line=(255, 78, 178))
    hx = lambda c: "#%02x%02x%02x" % tuple(c)
    return {"question_box": hx(th["fill"]), "question_outline": hx(th["line"]), "answer_box": hx(bar["fill"]),
            "answer_outline": hx(bar["line"]), "frame": hx(th["border"]), "highlight": hx(s.get("accent") or (246, 36, 140))}


def listing() -> list:
    return [{"key": v["key"], "title": v["title"], "group": v["group"], "colors": default_colors(v)} for v in LOOKS.values()]


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


# ------------------------------------------------------------------ the person's own colours
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
COLOR_KEYS = ("question_box", "question_outline", "answer_box", "answer_outline", "frame", "highlight")


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _lum(c):
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255


def clean_colors(colors) -> dict:
    """Keep only known keys with a valid #rrggbb value."""
    return {k: v for k, v in (colors or {}).items() if k in COLOR_KEYS and isinstance(v, str) and HEX.match(v)}


def with_colors(look: dict, colors) -> dict:
    """The look with the person's colours on top. Anything they did not change keeps the look's own colour."""
    c = clean_colors(colors)
    if not c:
        return look
    base = look.get("skin") or {}
    th, bar = dict(base.get("theme") or {}), dict(base.get("bar") or {})
    th.setdefault("fill", (112, 84, 240)); th.setdefault("line", (255, 78, 178)); th.setdefault("border", (255, 78, 178))
    bar.setdefault("fill", (255, 255, 255)); bar.setdefault("line", (255, 78, 178))
    accent = tuple(base.get("accent") or (246, 36, 140))
    if "question_box" in c:
        th["fill"] = _rgb(c["question_box"])
    if "question_outline" in c:
        th["line"] = _rgb(c["question_outline"])
    if "frame" in c:
        th["border"] = _rgb(c["frame"])
    if "highlight" in c:
        accent = _rgb(c["highlight"])
    if "answer_box" in c:
        bar["fill"] = _rgb(c["answer_box"])
    if "answer_outline" in c:
        bar["line"] = _rgb(c["answer_outline"])
    bar["circ"] = tuple(bar["line"])
    bar["circ_line"] = (255, 255, 255) if _lum(bar["fill"]) > 0.5 or _lum(bar["line"]) < 0.8 else (30, 30, 40)
    bar["letter"] = (255, 255, 255) if _lum(bar["circ"]) < 0.6 else (25, 25, 35)
    # answer text: the highlight colour when it reads well on the box, otherwise plain dark or white
    if abs(_lum(bar["fill"]) - _lum(accent)) > 0.35:
        bar["text"] = accent
    else:
        bar["text"] = (25, 25, 35) if _lum(bar["fill"]) > 0.5 else (255, 255, 255)
    return dict(look, skin=dict(theme=th, bar=bar, accent=accent))
