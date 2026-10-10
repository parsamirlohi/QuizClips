"""Draws the 1080x1920 quiz overlays (reference "marble + purple header" style) and renders each scene with ffmpeg.

Layers per scene:  animated marble background  ->  framed stock clip  ->  Pillow overlay (header, bars, circle ...).
"""
import math
import random
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import ASSETS_DIR, env, run_ffmpeg
from chalkboard import ensure_chalkboard
from marble import ensure_marble

W, H = 1080, 1920
SS = 3  # supersampling for smooth shapes

PINK = (255, 110, 185)
HOT = (255, 70, 160)
YELLOW = (255, 226, 40)
THEMES = {
    "purple": dict(fill=(112, 84, 240), line=PINK, border=PINK),
    "green": dict(fill=(74, 160, 74), line=(255, 255, 255), border=(90, 200, 110)),
    "red": dict(fill=(226, 56, 56), line=(255, 150, 160), border=(255, 80, 90)),
}
BAR_STYLES = {
    "purple": dict(fill=(255, 255, 255), line=PINK, text=HOT, circ=PINK, circ_line=(255, 255, 255), letter=(255, 255, 255)),
    "red": dict(fill=(222, 50, 50), line=(255, 160, 160), text=(255, 255, 255), circ=(255, 255, 255), circ_line=(255, 160, 160), letter=(222, 50, 50)),
    "green": dict(fill=(70, 165, 70), line=(255, 255, 255), text=(255, 255, 255), circ=(70, 165, 70), circ_line=(255, 255, 255), letter=(255, 255, 255)),
}

# clip window (the stock footage is placed here by ffmpeg, the overlay draws the white frame around it)
CLIP = (215, 620, 865, 970)
HEADER = (56, 64, 1024, 500)
BAR_Y0, BAR_STEP, BAR_H = 1010, 172, 136
NUM_C = (540, 1772)

_FONTS = [
    str(ASSETS_DIR / "fonts" / "LilitaOne-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "C:/Windows/Fonts/ariblk.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
]


@lru_cache(maxsize=None)
def font(size: int):
    custom = env("FONT_PATH")
    for p in ([custom] if custom else []) + _FONTS:
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


def _fit(text, max_w, max_h, start, minimum, gap=1.1):
    size = start
    while True:
        f = font(size)
        lines = _wrap(text, f, max_w)
        ok = len(lines) * size * gap <= max_h and all(f.getlength(" ".join(l)) <= max_w for l in lines)
        if ok or size <= minimum:
            return f, lines
        size -= 4


def _words(layer, cx, cy, text, max_w, max_h, start, minimum, color, lit=None, lit_color=PINK, stroke=9, only=None):
    """Chunky outlined centered text, optionally with the first `lit` words in a highlight color."""
    f, lines = _fit(text, max_w, max_h, start, minimum, 1.12)
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


def _header(theme, text, lit=None):
    t = THEMES[theme]
    x0, y0, x1, y1 = HEADER
    w, h = x1 - x0, y1 - y0
    layer = _box(w, h, 6, t["fill"], t["line"], 9)
    _words(layer, w // 2, h // 2, text, w - 110, h - 80, 150, 54, (255, 255, 255), lit, stroke=11)
    return layer


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


def _number_circle(img, label, reveal, timer, think, urgent):
    cx, cy = NUM_C
    big = Image.new("RGBA", (150 * SS, 150 * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.ellipse((2 * SS, 2 * SS, 148 * SS, 148 * SS), fill=(255, 255, 255, 255))
    d.ellipse((12 * SS, 12 * SS, 138 * SS, 138 * SS), fill=((255, 255, 255, 255) if reveal else (0, 0, 0, 255)))
    c = big.resize((150, 150), Image.LANCZOS)
    col = (70, 165, 70) if reveal else ((255, 70, 70) if urgent else HOT)
    _ctext(c, 75, 75, label, font(92), col + (255,))
    _place(img, c, cx, cy)
    if timer is not None and not reveal:
        _ring(img, cx, cy, 84, 10, max(0.0, timer) / think, (255, 70, 70, 255) if urgent else (255, 110, 185, 255))


def _frame_border(img, color):
    d = ImageDraw.Draw(img)
    c = color + (255,)
    d.rectangle((0, 0, W - 1, 17), fill=c)
    d.rectangle((0, H - 18, W - 1, H - 1), fill=c)
    d.rectangle((0, 0, 17, H - 1), fill=c)
    d.rectangle((W - 18, 0, W - 1, H - 1), fill=c)


def _clip_frame(img):
    x0, y0, x1, y1 = CLIP
    t = 14
    w, h = x1 - x0 + 2 * t, y1 - y0 + 2 * t
    outer = _mask(w, h, 30)
    inner = Image.new("L", (w, h), 0)
    inner.paste(_mask(w - 2 * t, h - 2 * t, 18), (t, t))
    a = np.clip(np.array(outer, dtype=np.int16) - np.array(inner, dtype=np.int16), 0, 255).astype("uint8")
    ring = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    ring.putalpha(Image.fromarray(a))
    img.alpha_composite(ring, (x0 - t, y0 - t))


def _outline_label(img, cx, cy, text, size, fill=(255, 255, 255)):
    _ctext(img, cx, cy, text, font(size), fill + (255,), stroke=7)


def draw_scene(theme="purple", header="", lit=None, hscale=1.0, label="", choices=(), letters="ABCD",
               visible=0, anim=1.0, correct_idx=None, reveal=False, timer=None, think=5, q_num=1,
               plus=0.0, clip=True, num_label=None, **_):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shown = "green" if reveal else theme
    _frame_border(img, THEMES[shown]["border"])
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
        cy = BAR_Y0 + i * BAR_STEP + BAR_H / 2
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

    name = env("CHANNEL_NAME")
    if name:
        _ctext(img, 540, 1858, name, font(50), (255, 255, 255, 255), stroke=6)
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


def draw_challenge(flash=0, boxscale=1.0, **_):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _frame_border(img, THEMES["red"]["border"])
    _place(img, _siren((70, 220, 90), flash % 2 == 0), 540, 420)
    _place(img, _siren((255, 50, 50), flash % 2 == 1), 540, 1500)
    box = _box(900, 330, 6, (255, 255, 255), (255, 70, 90), 10)
    for dy, txt in ((105, "CHALLENGE"), (240, "ROUND")):
        _ctext(box, 450, dy, txt, font(138), (255, 255, 255, 255), stroke=7, stroke_fill=(220, 30, 50, 255))
    _place(img, box, 540, 960, boxscale)
    return img


def draw_hook(text="", hl=0, hscale=1.0, **_):
    """Intro text over the static chalkboard: big outlined words, the word currently being read (index `hl`) in pink."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer = Image.new("RGBA", (W, 900), (0, 0, 0, 0))
    _words(layer, W // 2, 450, text, 900, 760, 190, 90, (255, 255, 255), None, stroke=15, only=hl)
    _place(img, layer, 540, 940, hscale)
    return img


def make_overlay(kind, args):
    if kind == "hook":
        return draw_hook(**args)
    return draw_challenge(**args) if kind == "challenge" else draw_scene(**args)


def _vcodec_args():
    enc = env("VIDEO_ENCODER", "libx264")
    if enc == "libx264":
        return ["-c:v", "libx264", "-preset", env("X264_PRESET", "veryfast"), "-crf", env("VIDEO_CRF", "24")]
    if enc == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "22", "-b:v", "0"]
    return ["-c:v", enc]


def _q(path) -> str:
    return path.as_posix().replace("'", "'\\''")


def render_segment(clip, frame_specs, duration, out_path, tmp, still=False):
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

    if still:  # static image background (chalkboard intro)
        inputs = ["-loop", "1", "-framerate", "30", "-i", ensure_chalkboard()]
    else:
        inputs = ["-ss", f"{random.uniform(0, 7):.2f}", "-stream_loop", "-1", "-i", ensure_marble()]
    cw, ch = CLIP[2] - CLIP[0], CLIP[3] - CLIP[1]
    if clip:
        inputs += ["-stream_loop", "-1", "-i", clip]
        ov = 2
        vf = (f"[0:v]scale=1080:1920:flags=bicubic,setsar=1,fps=30[bg];"
              f"[1:v]scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},setsar=1,fps=30[c];"
              f"[bg][c]overlay={CLIP[0]}:{CLIP[1]}:shortest=0[b2];")
        base = "b2"
    else:
        ov = 1
        vf = "[0:v]scale=1080:1920:flags=bicubic,setsar=1,fps=30[bg];"
        base = "bg"
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
