"""Draws the 1080x1920 quiz overlays (reference "marble + purple header" style) and renders each scene with ffmpeg.

Layers per scene:  animated marble background  ->  framed stock clip  ->  Pillow overlay (header, bars, circle ...).
"""
import math
import random
import threading
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import ASSETS_DIR, env, run_ffmpeg
from chalkboard import ensure_chalkboard  # noqa: F401  (offline fallback intro picture)
from marble import ensure_marble

W, H = 1080, 1920
SS = 3  # supersampling for smooth shapes
WATERMARK = None  # text for the bottom of the screen; set per video by the pipeline ('' = none)

PINK = (255, 78, 178)
HOT = (246, 36, 140)
YELLOW = (255, 226, 40)
THEMES = {
    "purple": dict(fill=(112, 84, 240), line=PINK, border=PINK),
    "green": dict(fill=(74, 160, 74), line=(255, 255, 255), border=(90, 200, 110)),
    "red": dict(fill=(226, 56, 56), line=(255, 150, 160), border=(255, 80, 90)),
}
LIT = [PINK]  # colour of the highlighted words in the header; changed by the chosen look
_DEFAULT_SKIN = None


def _forget_drawn_layers():
    """The header, answer bars and number circle are remembered while a video is drawn; a new look changes them."""
    for fn in ("_header", "_bar", "_circle"):
        f = globals().get(fn)
        if f is not None and hasattr(f, "cache_clear"):
            f.cache_clear()


def apply_skin(skin):
    """Use a look's colours (header, answer bars, border, accents) for the video being made. None = original pink."""
    global HOT, _DEFAULT_SKIN
    _forget_drawn_layers()
    if _DEFAULT_SKIN is None:
        _DEFAULT_SKIN = (dict(THEMES["purple"]), dict(BAR_STYLES["purple"]), (246, 36, 140), PINK)
    if not skin:
        return reset_skin()
    THEMES["purple"] = dict(skin["theme"])
    BAR_STYLES["purple"] = dict(skin["bar"])
    HOT = tuple(skin["accent"])
    LIT[0] = tuple(skin["accent"])


def reset_skin():
    global HOT
    _forget_drawn_layers()
    if _DEFAULT_SKIN is not None:
        THEMES["purple"], BAR_STYLES["purple"] = dict(_DEFAULT_SKIN[0]), dict(_DEFAULT_SKIN[1])
        HOT, LIT[0] = _DEFAULT_SKIN[2], _DEFAULT_SKIN[3]


BAR_STYLES = {
    "purple": dict(fill=(255, 255, 255), line=PINK, text=HOT, circ=PINK, circ_line=(255, 255, 255), letter=(255, 255, 255)),
    "red": dict(fill=(222, 50, 50), line=(255, 160, 160), text=(255, 255, 255), circ=(255, 255, 255), circ_line=(255, 160, 160), letter=(222, 50, 50)),
    "green": dict(fill=(70, 165, 70), line=(255, 255, 255), text=(255, 255, 255), circ=(70, 165, 70), circ_line=(255, 255, 255), letter=(255, 255, 255)),
}

# clip window (the stock footage is placed here by ffmpeg, the overlay draws the white frame around it)
CLIP = (215, 620, 865, 970)
HEADER = (56, 64, 1024, 500)
BAR_Y0, BAR_STEP, BAR_H = 1010, 172, 136
NUM_C = (540, 1745)

_FONTS = [
    str(ASSETS_DIR / "fonts" / "LilitaOne-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "C:/Windows/Fonts/ariblk.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
]


HOOK_FONTS = [str(ASSETS_DIR / "fonts" / "Bangers-Regular.ttf")]


@lru_cache(maxsize=None)
def font(size: int, face: str = "main"):
    return _font(size, face, threading.get_ident())   # scenes are drawn on several threads; each gets its own font objects


@lru_cache(maxsize=512)
def _font(size, face, _thread):
    custom = env("FONT_PATH")
    for p in (HOOK_FONTS if face == "hook" else []) + ([custom] if custom else []) + _FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _mask(w, h, radius):
    m = Image.new("L", (w * SS, h * SS), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius * SS, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def _box(w, h, radius, fill, line=None, lw=0):
    """Rounded rectangle layer with optional outline."""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if line and lw:
        layer.paste(Image.new("RGBA", (w, h), tuple(line) + (255,)), (0, 0), _mask(w, h, radius))
        inner = _mask(w - 2 * lw, h - 2 * lw, max(1, radius - lw))
        layer.paste(Image.new("RGBA", (w - 2 * lw, h - 2 * lw), tuple(fill) + (255,)), (lw, lw), inner)
    else:
        layer.paste(Image.new("RGBA", (w, h), tuple(fill) + (255,)), (0, 0), _mask(w, h, radius))
    return layer


def _place(img, layer, cx, cy, scale=1.0, alpha=1.0):
    """Paste layer centered on (cx, cy), optionally scaled/faded; clips safely at the edges."""
    if scale != 1.0:
        layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))), Image.LANCZOS)
    if alpha < 1.0:
        layer = layer.copy()
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
    x, y = int(cx - layer.width / 2), int(cy - layer.height / 2)
    l, t = max(0, -x), max(0, -y)
    r, b = min(layer.width, W - x), min(layer.height, H - y)
    if r <= l or b <= t:
        return
    img.alpha_composite(layer.crop((l, t, r, b)), (x + l, y + t))


def _ctext(img, cx, cy, text, f, fill=(255, 255, 255, 255), stroke=0, stroke_fill=(0, 0, 0, 255)):
    """Center the glyph shape (not the line box) on (cx, cy)."""
    d = ImageDraw.Draw(img)
    l, t, r, b = d.textbbox((0, 0), text, font=f, anchor="la", stroke_width=stroke)
    d.text((cx - (l + r) / 2, cy - (t + b) / 2), text, font=f, fill=fill, anchor="la",
           stroke_width=stroke, stroke_fill=stroke_fill)


def _wrap(text, f, max_w):
    lines, cur = [], []
    for w in text.split():
        t = " ".join(cur + [w])
        if f.getlength(t) <= max_w or not cur:
            cur.append(w)
        else:
            lines.append(cur)
            cur = [w]
    if cur:
        lines.append(cur)
    return lines  # list of word lists


def _fit(text, max_w, max_h, start, minimum, gap=1.1, face="main"):
    size = start
    while True:
        f = font(size, face)
        lines = _wrap(text, f, max_w)
        ok = len(lines) * size * gap <= max_h and all(f.getlength(" ".join(l)) <= max_w for l in lines)
        if ok or size <= minimum:
            return f, lines
        size -= 4


def _words(layer, cx, cy, text, max_w, max_h, start, minimum, color, lit=None, lit_color=None, stroke=9, only=None, face="main"):
    """Chunky outlined centered text, optionally with the first `lit` words in a highlight color."""
    lit_color = lit_color or LIT[0]
    f, lines = _fit(text, max_w, max_h, start, minimum, 1.12, face)
    lh = int(f.size * 1.12)
    d = ImageDraw.Draw(layer)
    base = cy + int(0.35 * f.size) - (len(lines) - 1) * lh / 2
    idx = 0
    for k, words in enumerate(lines):
        line = " ".join(words)
        x = cx - f.getlength(line) / 2
        y = base + k * lh
        for w in words:
            col = lit_color if ((lit is not None and idx < lit) or (only is not None and idx == only)) else color
            d.text((x, y), w, font=f, fill=col + (255,), anchor="ls", stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            x += f.getlength(w + " ")
            idx += 1


@lru_cache(maxsize=128)
def _header(theme, text, lit=None):   # cached: identical on every frame of a countdown (layers are never modified)
    t = THEMES[theme]
    x0, y0, x1, y1 = HEADER
    w, h = x1 - x0, y1 - y0
    layer = _box(w, h, 6, t["fill"], t["line"], 9)
    _words(layer, w // 2, h // 2, text, w - 110, h - 80, 150, 54, (255, 255, 255), lit, stroke=11)
    return layer


@lru_cache(maxsize=256)
def _bar(text, letter, style):
    s = BAR_STYLES[style]
    w, h = 960, BAR_H
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rect = _box(w - 70, 112, 8, s["fill"], s["line"], 7)
    layer.alpha_composite(rect, (70, 12))
    f = font(78)
    size = 78
    while f.getlength(text) > w - 70 - 190 and size > 30:
        size -= 4
        f = font(size)
    _ctext(layer, 70 + (w - 70 + 90) / 2 - 40, 68, text, f, s["text"] + (255,))
    c = Image.new("RGBA", (136, 136), (0, 0, 0, 0))
    big = Image.new("RGBA", (136 * SS, 136 * SS), (0, 0, 0, 0))
    bd = ImageDraw.Draw(big)
    bd.ellipse((4 * SS, 4 * SS, 132 * SS, 132 * SS), fill=s["circ_line"] + (255,))
    bd.ellipse((14 * SS, 14 * SS, 122 * SS, 122 * SS), fill=s["circ"] + (255,))
    c = big.resize((136, 136), Image.LANCZOS)
    _ctext(c, 68, 68, letter, font(84), s["letter"] + (255,))
    layer.alpha_composite(c, (0, 0))
    return layer


def _ring(img, cx, cy, r, thickness, frac, color):
    size = 2 * (r + thickness)
    layer = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    box = (thickness * SS, thickness * SS, (size - thickness) * SS, (size - thickness) * SS)
    d.ellipse(box, outline=(255, 255, 255, 90), width=thickness * SS)
    if frac > 0:
        d.arc(box, -90, -90 + 360 * min(frac, 1.0), fill=color, width=thickness * SS)
    _place(img, layer.resize((size, size), Image.LANCZOS), cx, cy)


@lru_cache(maxsize=128)
def _circle(label, reveal, urgent, hot):
    big = Image.new("RGBA", (150 * SS, 150 * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.ellipse((2 * SS, 2 * SS, 148 * SS, 148 * SS), fill=(255, 255, 255, 255))
    d.ellipse((12 * SS, 12 * SS, 138 * SS, 138 * SS), fill=((255, 255, 255, 255) if reveal else (0, 0, 0, 255)))
    c = big.resize((150, 150), Image.LANCZOS)
    col = (70, 165, 70) if reveal else ((255, 70, 70) if urgent else hot)
    _ctext(c, 75, 75, label, font(92), col + (255,))
    return c


def _number_circle(img, label, reveal, timer, think, urgent):
    cx, cy = NUM_C
    _place(img, _circle(label, bool(reveal), bool(urgent), tuple(HOT)), cx, cy)


def _border_path(img, color, frac=1.0, t=24, track=(255, 255, 255)):
    """Border around the screen that doubles as the timer: it shrinks clockwise from the top centre."""
    if frac <= 0:
        return
    if frac < 1.0 and track:  # a track of the same size behind the bar, so you can see the timer deplete
        _border_path(img, track, 1.0, t, None)
    d = ImageDraw.Draw(img)
    c = color + (255,)
    # clockwise path: top-centre -> top-right -> bottom-right -> bottom-left -> top-left -> top-centre
    segs = [((W // 2, 0), (W, 0)), ((W, 0), (W, H)), ((W, H), (0, H)), ((0, H), (0, 0)), ((0, 0), (W // 2, 0))]
    total = sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in segs)
    left = total * min(frac, 1.0)
    for (x0, y0), (x1, y1) in segs:
        length = abs(x1 - x0) + abs(y1 - y0)
        use = min(length, left)
        if use <= 0:
            break
        ex = x0 + (x1 - x0) * use / length
        ey = y0 + (y1 - y0) * use / length
        xa, xb = sorted((x0, ex))
        ya, yb = sorted((y0, ey))
        if y0 == y1:  # horizontal run, drawn on the top or bottom edge
            top = 0 if y0 == 0 else H - t
            d.rectangle((xa, top, xb, top + t - 1), fill=c)
        else:
            left_x = 0 if x0 == 0 else W - t
            d.rectangle((left_x, ya, left_x + t - 1, yb), fill=c)
        left -= use


def _lum(c):
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255


def _bar_colors(color):
    """(bar colour, track colour) for the border / countdown bar. A white (or nearly white) border would vanish against
    the white track and bright backgrounds, so it is drawn black; other light colours keep their colour but get a dark track."""
    color, track = tuple(color), (255, 255, 255)
    lum = _lum(color)
    if lum >= 0.9:
        color = (0, 0, 0)
    elif lum >= 0.75:
        track = (30, 30, 40)
    return color, track


def _frame_border(img, color, frac=1.0, t=24, track_only=False):
    """The border / countdown bar. track_only draws just the full track: the shrinking bar itself is then drawn
    by ffmpeg on every video frame (see _bar_filters), which is what makes the countdown smooth."""
    if frac <= 0:
        return
    color, track = _bar_colors(color)
    if track_only:
        _border_path(img, track, 1.0, t, None)
        return
    _border_path(img, color, frac, t, track)


def _bar_filters(start, think, color, src, dst, t=24):
    """ffmpeg filters that draw the countdown bar shrinking smoothly, clockwise from the top centre, on every frame.
    It starts full at `start` seconds and is gone `think` seconds later. Each of the five edges is a short coloured strip
    next to a transparent one; a crop window slides along it (crop's x / y are worked out per frame), so only the part
    of the edge that is still left shows."""
    Wd, Hd = W, H
    segs = [  # orientation, length, where it sits, which end the colour is attached to
        ("h", Wd // 2, (Wd // 2, 0), "start"), ("v", Hd, (Wd - t, 0), "start"), ("h", Wd, (0, Hd - t), "end"),
        ("v", Hd, (0, 0), "end"), ("h", Wd // 2, (0, 0), "start"),
    ]
    total = sum(sg[1] for sg in segs)
    left = f"{total}*clip(1-(t-{start:.4f})/{think},0,1)"
    hexc = "0x%02X%02X%02X" % tuple(color)
    parts, cum, cur = [], 0, src
    for i, (orient, L, (x, y), anchor) in enumerate(segs):
        used = f"clip({left}-{cum},0,{L})"
        size = f"{L}x{t}" if orient == "h" else f"{t}x{L}"
        a, b = (f"[s{i}c][s{i}t]", None) if anchor == "start" else (f"[s{i}t][s{i}c]", None)
        stack = "hstack" if orient == "h" else "vstack"
        parts.append(f"color=c={hexc}:s={size}:r=30,format=rgba[s{i}c];color=c=black@0:s={size}:r=30,format=rgba[s{i}t];"
                     f"{a}{stack}=inputs=2[s{i}];")
        off = f"{L}-{used}" if anchor == "start" else used
        crop = f"crop=w={L}:h={t}:x='{off}':y=0" if orient == "h" else f"crop=w={t}:h={L}:x=0:y='{off}'"
        parts.append(f"[s{i}]{crop}[w{i}];")
        nxt = dst if i == len(segs) - 1 else f"o{i}"
        parts.append(f"[{cur}][w{i}]overlay={x}:{y}:format=auto[{nxt}];")
        cur = nxt
        cum += L
    return "".join(parts)


@lru_cache(maxsize=1)
def _clip_ring():
    x0, y0, x1, y1 = CLIP
    t = 14
    w, h = x1 - x0 + 2 * t, y1 - y0 + 2 * t
    outer = _mask(w, h, 30)
    inner = Image.new("L", (w, h), 0)
    inner.paste(_mask(w - 2 * t, h - 2 * t, 18), (t, t))
    a = np.clip(np.array(outer, dtype=np.int16) - np.array(inner, dtype=np.int16), 0, 255).astype("uint8")
    ring = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    ring.putalpha(Image.fromarray(a))
    return ring


def _clip_frame(img):
    x0, y0, x1, y1 = CLIP
    t = 14
    img.alpha_composite(_clip_ring(), (x0 - t, y0 - t))


def _outline_label(img, cx, cy, text, size, fill=(255, 255, 255)):
    _ctext(img, cx, cy, text, font(size), fill + (255,), stroke=7)


def draw_scene(theme="purple", header="", lit=None, hscale=1.0, label="", choices=(), letters="ABCD",
               visible=0, anim=1.0, correct_idx=None, reveal=False, timer=None, think=5, q_num=1,
               plus=0.0, clip=True, num_label=None, border=True, bar_dy=0, smooth=False, **_):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shown = "green" if reveal else theme
    if timer is not None:
        bfrac = timer / think
    else:
        bfrac = 0.0 if reveal else 1.0
    if border:
        _frame_border(img, THEMES[theme]["border"], bfrac, track_only=bool(smooth) and timer is not None)
    hx0, hy0, hx1, hy1 = HEADER
    _place(img, _header(shown, header, lit), (hx0 + hx1) / 2, (hy0 + hy1) / 2, hscale)
    if clip:
        _clip_frame(img)
    if label:
        _outline_label(img, 540, 566, label, 50)

    bar_style = "red" if theme == "red" else "purple"
    for i in range(min(visible, len(choices))):
        if reveal and i != correct_idx:
            continue
        style = "green" if reveal else bar_style
        layer = _bar(choices[i], letters[i], style)
        cy = BAR_Y0 + i * BAR_STEP + BAR_H / 2 + bar_dy
        if i == visible - 1 and anim < 1.0 or (i == visible - 1 and anim > 1.0):
            _place(img, layer, 50 + layer.width / 2, cy, anim, min(1.0, max(0.2, (anim - 0.4) * 2.5)))
        else:
            _place(img, layer, 50 + layer.width / 2, cy)

    if plus > 0:
        txt = Image.new("RGBA", (1000, 360), (0, 0, 0, 0))
        d = ImageDraw.Draw(txt)
        f = font(250)
        d.text((500, 180), "+500", font=f, fill=YELLOW + (255,), anchor="mm", stroke_width=18, stroke_fill=(45, 20, 70, 255))
        _place(img, txt, 540, 795, plus)

    if num_label is not False:
        _number_circle(img, str(num_label if num_label is not None else q_num), reveal, timer, think,
                       timer is not None and timer <= 2.0)

    name = WATERMARK if WATERMARK is not None else env("CHANNEL_NAME")
    if name and name.lower() != "none":
        _ctext(img, 540, 1850, name, font(36), (255, 255, 255, 255), stroke=5)
    return img


@lru_cache(maxsize=1)
def _story_scrim():
    """Soft dark fades at the top and the bottom so the words stay readable over any footage."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = img.load()
    for y in range(H):
        a = 0.0
        if y < 820:
            a = 0.62 * (1 - y / 820) ** 1.3
        elif y > 980:
            a = 0.72 * min(1.0, (y - 980) / 520)
        if a > 0:
            v = int(255 * a)
            for x in range(W):
                px[x, y] = (0, 0, 0, v)
    return img


def draw_story(theme="purple", header="", hscale=1.0, label="", choices=(), letters="ABCD", visible=0, anim=1.0,
               timer=None, think=5, num_label=None, border=True, bar_dy=0, smooth=False, **_):
    """The Story video: the footage fills the whole screen, the situation is big outlined text on top of it and the
    options sit in bars lower down. Same countdown border and bars as the other scenes."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.alpha_composite(_story_scrim())
    if border:
        bfrac = 1.0 if timer is None else timer / think
        _frame_border(img, THEMES[theme]["border"], bfrac, track_only=bool(smooth) and timer is not None)
    if label:
        _outline_label(img, 540, 150, label, 52)
    layer = Image.new("RGBA", (W, 560), (0, 0, 0, 0))
    _words(layer, W // 2, 280, header, 960, 500, 150, 60, (255, 255, 255), None, stroke=14)
    _place(img, layer, 540, 470, hscale)
    bar_style = "red" if theme == "red" else "purple"
    for i in range(min(visible, len(choices))):
        bar = _bar(choices[i], letters[i], bar_style)
        cy = BAR_Y0 + i * BAR_STEP + BAR_H / 2 + bar_dy
        if i == visible - 1 and anim != 1.0:
            _place(img, bar, 50 + bar.width / 2, cy, anim, min(1.0, max(0.2, (anim - 0.4) * 2.5)))
        else:
            _place(img, bar, 50 + bar.width / 2, cy)
    if num_label is not False:
        _number_circle(img, str(num_label if num_label is not None else 1), False, timer, think,
                       timer is not None and timer <= 2.0)
    name = WATERMARK if WATERMARK is not None else env("CHANNEL_NAME")
    if name and name.lower() != "none":
        _ctext(img, 540, 1850, name, font(36), (255, 255, 255, 255), stroke=5)
    return img


def _caption_box(text):
    """White rounded box with the text in the look's accent colour (same style as an answer bar)."""
    s = BAR_STYLES["purple"]
    f, lines = _fit(text, 840, 400, 80, 44, 1.12)
    h = max(190, int(len(lines) * f.size * 1.12) + 96)
    layer = _box(960, h, 12, s["fill"], s["line"], 8)
    _words(layer, 480, h // 2, text, 840, h - 70, 80, 44, s["text"], stroke=0)
    return layer


def draw_card(theme="purple", header="", lit=None, hscale=1.0, label="", caption="", anim=1.0, badge="", border=True,
              clip=True, tag="", **_):
    """One item of a list: header (name), footage window, small label, caption box with a sentence, number badge."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if border:
        _frame_border(img, THEMES[theme]["border"], 1.0)
    hx0, hy0, hx1, hy1 = HEADER
    _place(img, _header(theme, header, lit), (hx0 + hx1) / 2, (hy0 + hy1) / 2, hscale)
    if clip:
        _clip_frame(img)
    if label:
        _outline_label(img, 540, 566, label, 50)
    if caption:
        box = _caption_box(caption)
        cy = 1040 + box.height / 2
        _place(img, box, 540, cy, anim, min(1.0, max(0.0, (anim - 0.4) * 2.5)) if anim != 1.0 else 1.0)
    if badge:
        _number_circle(img, str(badge), False, None, 5, False)
    name = WATERMARK if WATERMARK is not None else env("CHANNEL_NAME")
    if name and name.lower() != "none":
        _ctext(img, 540, 1850, name, font(36), (255, 255, 255, 255), stroke=5)
    return img



def _siren(color_on, on):
    w, h = 190, 220
    layer = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    base = (150, 150, 160, 255)
    d.rounded_rectangle((20 * SS, 170 * SS, 170 * SS, 215 * SS), 10 * SS, fill=base)
    body = color_on if on else tuple(int(c * 0.35) for c in color_on)
    d.rounded_rectangle((35 * SS, 40 * SS, 155 * SS, 180 * SS), 55 * SS, fill=body + (255,), outline=(30, 30, 30, 255), width=6 * SS)
    d.rectangle((35 * SS, 120 * SS, 155 * SS, 172 * SS), fill=body + (255,))
    d.ellipse((60 * SS, 62 * SS, 90 * SS, 100 * SS), fill=(255, 255, 255, 200 if on else 60))
    img = layer.resize((w, h), Image.LANCZOS)
    if on:
        glow = Image.new("RGBA", (w + 160, h + 160), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((20, 20, w + 140, h + 140), fill=color_on + (150,))
        glow = glow.filter(ImageFilter.GaussianBlur(34))
        out = Image.new("RGBA", glow.size, (0, 0, 0, 0))
        out.alpha_composite(glow)
        out.alpha_composite(img, (80, 80))
        return out
    return img


def _ease_out(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def _ease_back(x):
    x = min(max(x, 0.0), 1.0)
    return 1 + 2.70158 * (x - 1) ** 3 + 1.70158 * (x - 1) ** 2


@lru_cache(maxsize=1)
def _hazard_strip():
    """Yellow/black warning stripes; repeats every 80 px so it can scroll."""
    h = 74
    img = Image.new("RGBA", (W + 160, h), (18, 14, 22, 255))
    d = ImageDraw.Draw(img)
    for x in range(-80, W + 240, 80):
        d.polygon([(x, 0), (x + 40, 0), (x + 5, h), (x - 35, h)], fill=(255, 214, 0, 255))
    return img


@lru_cache(maxsize=1)
def _vignette_alpha():
    sw, sh = 135, 240
    yy, xx = np.mgrid[0:sh, 0:sw]
    dist = np.sqrt(((xx - sw / 2) / (sw / 2)) ** 2 + ((yy - sh / 2) / (sh / 2)) ** 2)
    return np.clip((dist - 0.35) / 0.9, 0, 1) ** 1.4


def _vignette(k):
    a = (_vignette_alpha() * k * 235).astype(np.uint8)
    small = Image.new("RGBA", a.shape[::-1], (205, 12, 34, 0))
    small.putalpha(Image.fromarray(a))
    return small.resize((W, H), Image.BICUBIC)


@lru_cache(maxsize=4)
def _title_layer(text, size_cap):
    size = size_cap
    f = font(size, "hook")
    while f.getlength(text) > 940 and size > 80:
        size -= 6
        f = font(size, "hook")
    m = 90
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    l, t, r, bb = probe.textbbox((0, 0), text, font=f, anchor="la", stroke_width=16)
    tw, th = int(r - l), int(bb - t)
    layer = Image.new("RGBA", (tw + 2 * m, th + 2 * m), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((m - l, m - t), text, font=f, fill=(255, 255, 255, 255), anchor="la",
                               stroke_width=16, stroke_fill=(120, 0, 24, 255))
    glow = Image.new("RGBA", layer.size, (255, 40, 70, 0))
    glow.putalpha(layer.getchannel("A").filter(ImageFilter.GaussianBlur(26)).point(lambda v: min(255, v * 2)))
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 170), (0, 14), layer.getchannel("A"))
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    out.alpha_composite(glow)
    out.alpha_composite(shadow)
    out.alpha_composite(layer)
    return out


def _slam(t, t0, dur=0.2, start=3.2):
    """(scale, alpha) of a word that slams in from huge at time t0."""
    if t < t0:
        return None
    p = (t - t0) / dur
    return start + (1.0 - start) * _ease_out(p), min(1.0, (t - t0) / 0.06)


def draw_challenge(t=0.0, dur=3.4, **_):
    """Cinematic title card: dim + red vignette, scrolling hazard bars, rays, 'CHALLENGE' and 'ROUND' slam in with
    shockwaves, flashes and screen shake, then a 'Final question' tag."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    T1, T2, T3 = 0.45, 0.80, 1.22
    pulse = 0.82 + 0.18 * math.sin(2 * math.pi * 2.0 * t)
    ramp = _ease_out(t / 0.4)
    img.alpha_composite(Image.new("RGBA", (W, H), (8, 0, 6, int(120 * ramp))))
    img.alpha_composite(_vignette(ramp * pulse))

    # rotating rays
    if ramp > 0:
        rays = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        rd = ImageDraw.Draw(rays)
        base, step = t * 0.35, math.pi / 9
        for k in range(18):
            a0 = base + k * step * 2
            rd.polygon([(W / 2, 930), (W / 2 + 2200 * math.cos(a0), 930 + 2200 * math.sin(a0)),
                        (W / 2 + 2200 * math.cos(a0 + step), 930 + 2200 * math.sin(a0 + step))],
                       fill=(255, 90, 110, int(34 * ramp)))
        img.alpha_composite(rays)

    # shake after each impact
    shake = 0.0
    for ti, amp in ((T1, 30), (T2, 18)):
        if t >= ti:
            shake += amp * math.exp(-(t - ti) * 9) * math.sin((t - ti) * 70)
    sx, sy = shake, shake * 0.6

    # hazard bars slide in from opposite sides and keep scrolling
    strip = _hazard_strip()
    off = int(t * 260) % 80
    bar = strip.crop((off, 0, off + W, strip.height))
    e = _ease_out(t / 0.35)
    img.alpha_composite(bar, (int(-W * (1 - e) + sx), int(250 + sy)))
    img.alpha_composite(bar.transpose(Image.FLIP_LEFT_RIGHT), (int(W * (1 - e) + sx), int(1596 + sy)))

    # build-up line across the middle before the first hit
    if t < T1:
        wline = int(W * _ease_out(t / T1))
        ImageDraw.Draw(img).rectangle((W // 2 - wline // 2, 954, W // 2 + wline // 2, 966), fill=(255, 255, 255, 235))

    # shockwave rings
    d = ImageDraw.Draw(img)
    for ti in (T1, T2):
        if t >= ti:
            p = (t - ti) / 0.55
            if p < 1:
                r = 90 + 980 * _ease_out(p)
                wd = max(2, int(22 * (1 - p)))
                d.ellipse((W / 2 + sx - r, 930 + sy - r, W / 2 + sx + r, 930 + sy + r),
                          outline=(255, 255, 255, int(235 * (1 - p))), width=wd)

    # the words
    for text, cap, t0, cy in (("CHALLENGE", 300, T1, 840), ("ROUND", 340, T2, 1110)):
        s_a = _slam(t, t0)
        if not s_a:
            continue
        sc, al = s_a
        if t > t0 + 0.3:
            sc *= 1 + 0.012 * math.sin(2 * math.pi * 1.8 * t)
        _place(img, _title_layer(text, cap), 540 + sx, cy + sy, sc, al)

    # 'final question' tag
    if t >= T3:
        p = _ease_back((t - T3) / 0.35)
        tag = _box(560, 92, 46, (255, 214, 0), (18, 14, 22), 6)
        _ctext(tag, 280, 46, "FINAL QUESTION", font(78, "hook"), (30, 8, 18, 255))
        _place(img, tag, 540, 1365 - 40 * (1 - min(p, 1.0)) + sy, 0.7 + 0.3 * min(p, 1.2), min(1.0, p))

    # white flashes on the hits
    fl = 0.0
    for ti, g in ((T1, 205), (T2, 130)):
        if t >= ti:
            fl = max(fl, g * math.exp(-(t - ti) * 11))
    if fl > 4:
        img.alpha_composite(Image.new("RGBA", (W, H), (255, 245, 245, int(fl))))

    # fade the whole card out at the end
    if t > dur - 0.22:
        k = max(0.0, (dur - t) / 0.22)
        img.putalpha(img.getchannel("A").point(lambda v: int(v * k)))
    return img


def draw_hook(text="", hl=0, hscale=1.0, **_):
    """Intro text over the static chalkboard: big outlined words, the word currently being read (index `hl`) in pink."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer = Image.new("RGBA", (W, 900), (0, 0, 0, 0))
    _words(layer, W // 2, 450, text, 940, 780, 250, 100, (255, 255, 255), None, stroke=16, only=hl, face="hook")
    _place(img, layer, 540, 940, hscale)
    return img


_BRAND_MARK = []


def _brand_mark():
    """The 'Made with Quizclips' stamp drawn on every frame: a round white sticker with a spiky edge, like a seal.
    Built once and reused."""
    import math
    if _BRAND_MARK:
        return _BRAND_MARK[0]
    S = 3                          # drawn at triple size, then shrunk, so the edges are smooth
    D = 236                        # sticker size on the video
    ink, purple = (20, 22, 31, 255), (112, 84, 240, 255)
    cx = cy = D * S // 2
    big = Image.new("RGBA", (D * S, D * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)

    def burst(r_out, r_in, teeth, fill):
        pts = []
        for k in range(teeth * 2):
            r = r_out if k % 2 == 0 else r_in
            a = math.pi * k / teeth
            pts.append((cx + r * S * math.cos(a), cy + r * S * math.sin(a)))
        d.polygon(pts, fill=fill)

    burst(112, 101, 24, ink)       # dark edge
    burst(108, 97, 24, (255, 255, 255, 255))
    d.ellipse((cx - 93 * S, cy - 93 * S, cx + 93 * S, cy + 93 * S), outline=purple, width=3 * S)
    try:
        logo = Image.open(ASSETS_DIR / "quizclips_logo.png").convert("RGBA").resize((84 * S, 84 * S), Image.LANCZOS)
        big.alpha_composite(logo, (cx - 42 * S, cy - 50 * S))
    except OSError:
        pass
    small, name = font(17 * S), font(30 * S)
    d.text((cx, cy - 60 * S), "MADE WITH", font=small, fill=purple, anchor="mm")
    d.text((cx, cy + 48 * S), "Quizclips", font=name, fill=ink, anchor="mm")
    big = big.rotate(8, resample=Image.BICUBIC, expand=False)
    D = 180
    sticker = big.resize((D, D), Image.LANCZOS)
    shadow = Image.new("RGBA", (D + 20, D + 20), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 90), (10, 14), sticker.getchannel("A"))
    shadow = shadow.filter(ImageFilter.GaussianBlur(5))
    shadow.alpha_composite(sticker, (10, 10))
    _BRAND_MARK.append(shadow)
    return shadow


BRAND_POS = (44, 1673)   # bottom left: clear of the answer bars, the number circle and the channel name


def make_overlay(kind, args):
    if kind == "hook":
        img = draw_hook(**args)
    elif kind == "card":
        img = draw_card(**args)
    elif kind == "story":
        img = draw_story(**args)
    else:
        img = draw_challenge(**args) if kind == "challenge" else draw_scene(**args)
    if env("BRAND_MARK", "1") != "0":   # set BRAND_MARK=0 to leave it off (for a paid plan, later)
        img.alpha_composite(_brand_mark(), BRAND_POS)
    return img


def _vcodec_args():
    enc = env("VIDEO_ENCODER", "libx264")
    if enc == "libx264":
        return ["-c:v", "libx264", "-preset", env("X264_PRESET", "veryfast"), "-crf", env("VIDEO_CRF", "24")]
    if enc == "h264_videotoolbox":   # the Mac's hardware encoder: much faster, a little bigger files
        return ["-c:v", enc, "-b:v", env("VIDEO_BITRATE", "9M"), "-allow_sw", "1"]
    if enc == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "22", "-b:v", "0"]
    return ["-c:v", enc]


def _q(path) -> str:
    return path.as_posix().replace("'", "'\\''")


def render_segment(clip, frame_specs, duration, out_path, tmp, full=None, look=None):
    """frame_specs: list of (start_time, kind, args). Each overlay holds until the next one starts.
    clip: path of a stock video shown inside the frame, or None."""
    items = []
    for idx, (start, kind, args) in enumerate(frame_specs):
        end = frame_specs[idx + 1][0] if idx + 1 < len(frame_specs) else duration
        png = tmp / f"{out_path.stem}_{idx:02d}.png"
        make_overlay(kind, args).save(png, compress_level=1)
        items.append((png, max(0.04, end - start)))
    lines = []
    for png, dur in items:
        lines += [f"file '{_q(png)}'", f"duration {dur:.3f}"]
    lines.append(f"file '{_q(items[-1][0])}'")
    lst = tmp / f"{out_path.stem}.txt"
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")

    blur = (look or {}).get("blur") if (clip and not full) else None
    bg_loop = (look or {}).get("bg") or ensure_marble()
    cw, ch = CLIP[2] - CLIP[0], CLIP[3] - CLIP[1]
    photo = bool(clip) and str(clip).lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    if full:  # full-screen picture or video behind everything (chalkboard intro)
        if str(full).lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            inputs = ["-loop", "1", "-framerate", "30", "-i", str(full)]
        else:
            inputs = ["-stream_loop", "-1", "-i", str(full)]
    elif blur:  # the background is the question's own clip, blown up, blurred and darkened
        inputs = (["-loop", "1", "-framerate", "30", "-i", str(clip)] if photo
                  else ["-stream_loop", "-1", "-i", str(clip)])
    else:
        inputs = ["-ss", f"{random.uniform(0, 5):.2f}", "-stream_loop", "-1", "-i", str(bg_loop)]
    if clip:
        pre = ""
        if blur:
            if photo:
                inputs += ["-i", str(clip)]  # second copy, not looped, for the slow zoom
                bsrc, src, ov = "0:v", "1:v", 2
            else:
                pre = "[0:v]split=2[s1][s2];"
                bsrc, src, ov = "s1", "s2", 1
            # darken / tint at the small size, then enlarge: same picture, a sixteenth of the pixels to process
            bgf = (f"[{bsrc}]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,setsar=1,fps=30,"
                   f"gblur=sigma=8,eq=brightness={-blur.get('dark', 0.3):.2f}:saturation={blur.get('sat', 0.9):.2f}")
            if blur.get("tint"):
                bgf += f",drawbox=x=0:y=0:w=iw:h=ih:color=0x{blur['tint']}@{blur.get('alpha', 0.35)}:t=fill"
            bgf += ",scale=1080:1920:flags=bicubic[bg];"
        else:
            inputs += ["-i", str(clip)] if photo else ["-stream_loop", "-1", "-i", str(clip)]
            src, ov = "1:v", 2
            bgf = "[0:v]scale=1080:1920:flags=bicubic,setsar=1,fps=30[bg];"
        if photo:  # a single photo with a slow zoom-in
            frames = int(duration * 30) + 30
            cvf = (f"[{src}]scale={cw * 2}:{ch * 2}:force_original_aspect_ratio=increase,crop={cw * 2}:{ch * 2},"
                   f"zoompan=z='min(1+0.0009*on,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={cw}x{ch}:fps=30,"
                   f"setsar=1[c];")
        else:
            cvf = f"[{src}]scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},setsar=1,fps=30[c];"
        vf = pre + bgf + cvf + f"[bg][c]overlay={CLIP[0]}:{CLIP[1]}:shortest=0[b2];"
        base = "b2"
    else:
        ov = 1
        if full:
            vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase:flags=bicubic,crop=1080:1920,setsar=1,"
                  "fps=30,eq=brightness=-0.10:saturation=0.9[bg];")
        else:
            vf = "[0:v]scale=1080:1920:flags=bicubic,setsar=1,fps=30[bg];"
        base = "bg"
    smooth = [(st, a) for st, k, a in frame_specs if k in ("scene", "story") and a.get("smooth") and a.get("timer") is not None]
    if smooth:   # the countdown bar is drawn by ffmpeg on every video frame, not once per overlay picture
        a0 = smooth[0][1]
        color, _track = _bar_colors(THEMES[a0.get("theme", "purple")]["border"])
        vf += f"[{ov}:v]format=rgba[ov];[{base}][ov]overlay=0:0:format=auto[vo];"
        vf += _bar_filters(smooth[0][0], a0.get("think", 5), color, "vo", "vb") + "[vb]format=yuv420p[v]"
    else:
        vf += f"[{ov}:v]format=rgba[ov];[{base}][ov]overlay=0:0:format=auto,format=yuv420p[v]"
    run_ffmpeg(inputs + ["-f", "concat", "-safe", "0", "-i", lst, "-filter_complex", vf, "-map", "[v]",
                         "-t", f"{duration:.3f}", "-an"]
               + _vcodec_args() + ["-pix_fmt", "yuv420p", "-r", "30", out_path])


def concat_videos(paths, out, tmp):
    lst = tmp / "segments.txt"
    lst.write_text("".join(f"file '{_q(p)}'\n" for p in paths), encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])


def mux(video, audio_wav, out):
    run_ffmpeg(["-i", video, "-i", audio_wav, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart", out])
