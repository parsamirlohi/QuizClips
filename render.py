"""Draws the 1080x1920 quiz overlays with Pillow and renders each scene with ffmpeg."""
import math
import random
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import env, run_ffmpeg

W, H = 1080, 1920
LETTERS = "ABCD"
# (light, dark) gradient colors for each answer letter
LETTER_GRADS = [
    ((255, 99, 99), (205, 40, 95)),     # A coral red
    ((72, 176, 255), (40, 95, 225)),    # B blue
    ((184, 120, 255), (115, 65, 225)),  # C purple
    ((255, 190, 50), (240, 112, 22)),   # D orange
]
GREEN = ((52, 211, 120), (16, 150, 80))
GOLD = (255, 214, 10)
SS = 3  # supersampling for smooth shapes

_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "C:/Windows/Fonts/ariblk.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "arialbd.ttf",
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


def _grad_img(w, h, c0, c1, alpha=255, horizontal=True):
    t = np.linspace(0, 1, w if horizontal else h)
    t = t[None, :, None] if horizontal else t[:, None, None]
    c0, c1 = np.array(c0, dtype=np.float32), np.array(c1, dtype=np.float32)
    rgb = c0 * (1 - t) + c1 * t
    rgb = np.broadcast_to(rgb, (h, w, 3))
    a = np.full((h, w, 1), alpha, dtype=np.float32)
    return Image.fromarray(np.concatenate([rgb, a], axis=2).astype("uint8"), "RGBA")


def _shadow(img, box, radius, blur=20, alpha=120, dy=12, color=(0, 0, 0)):
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h, pad = x1 - x0, y1 - y0, blur * 3
    layer = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((pad, pad, pad + w, pad + h), radius, fill=color + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(layer, (x0 - pad, y0 - pad + dy))


def _card(img, box, radius, c0=None, c1=None, fill=None, alpha=255, outline=None, ow=0, shadow=True,
          horizontal=True):
    """Rounded card: gradient (c0 -> c1) or flat fill, optional outline and soft shadow."""
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = x1 - x0, y1 - y0
    if shadow:
        _shadow(img, box, radius, alpha=int(110 * alpha / 255))
    base = _grad_img(w, h, c0, c1, alpha, horizontal) if c0 is not None else Image.new("RGBA", (w, h), fill)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    layer.paste(base, (0, 0), _mask(w, h, radius))
    if outline:
        outer = _mask(w, h, radius)
        inner = Image.new("L", (w, h), 0)
        inner.paste(_mask(w - 2 * ow, h - 2 * ow, max(1, radius - ow)), (ow, ow))
        ring = Image.new("RGBA", (w, h), outline)
        ring.putalpha(Image.fromarray(np.clip(np.array(outer, dtype=np.int16) - np.array(inner, dtype=np.int16), 0, 255).astype("uint8")))
        layer.alpha_composite(ring)
    img.alpha_composite(layer, (x0, y0))


def _circle(img, cx, cy, r, fill, outline=None, width=0):
    w = 2 * r
    layer = Image.new("RGBA", (w * SS, w * SS), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse((0, 0, w * SS - 1, w * SS - 1), fill=fill, outline=outline, width=width * SS)
    img.alpha_composite(layer.resize((w, w), Image.LANCZOS), (int(cx - r), int(cy - r)))


def _ring(img, cx, cy, r, thickness, frac, color, track=(255, 255, 255, 60)):
    size = 2 * (r + thickness)
    layer = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    box = (thickness * SS, thickness * SS, (size - thickness) * SS, (size - thickness) * SS)
    d.ellipse(box, outline=track, width=thickness * SS)
    if frac > 0:
        d.arc(box, -90, -90 + 360 * min(frac, 1.0), fill=color, width=thickness * SS)
    img.alpha_composite(layer.resize((size, size), Image.LANCZOS), (int(cx - size / 2), int(cy - size / 2)))


def _text(img, xy, text, f, fill=(255, 255, 255, 255), anchor="la", shadow=True):
    d = ImageDraw.Draw(img)
    if shadow:
        d.text((xy[0] + 3, xy[1] + 4), text, font=f, fill=(0, 0, 0, 140), anchor=anchor)
    d.text(xy, text, font=f, fill=fill, anchor=anchor)


def _ctext(img, cx, cy, text, f, fill=(255, 255, 255, 255)):
    """Draw text so its actual glyph shape (not the font's line box) is centered on (cx, cy)."""
    d = ImageDraw.Draw(img)
    l, t, r, b = d.textbbox((0, 0), text, font=f, anchor="la")
    d.text((cx - (l + r) / 2, cy - (t + b) / 2), text, font=f, fill=fill, anchor="la")


def _wrap(text, f, max_w):
    lines, cur = [], ""
    for w in text.split():
        t = f"{cur} {w}".strip()
        if f.getlength(t) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit(text, max_w, max_h, start, minimum, gap=1.2):
    size = start
    while True:
        f = font(size)
        lines = _wrap(text, f, max_w)
        fits = len(lines) * size * gap <= max_h and all(f.getlength(l) <= max_w for l in lines)
        if fits or size <= minimum:
            return f, lines
        size -= 4


def _confetti(img, seed, box):
    rnd = random.Random(seed)
    colors = [g[0] for g in LETTER_GRADS] + [GOLD, (255, 255, 255)]
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    for _ in range(80):
        x, y = rnd.randint(x0, x1), rnd.randint(y0, y1)
        c = rnd.choice(colors) + (255,)
        if rnd.random() < 0.5:
            r = rnd.randint(6, 13)
            d.ellipse((x - r, y - r, x + r, y + r), fill=c)
        else:
            a, L = rnd.random() * math.pi, rnd.randint(14, 30)
            d.line((x, y, x + math.cos(a) * L, y + math.sin(a) * L), fill=c, width=8)


CARD_X0, CARD_X1, CARD_H, CARD_STEP, CARD_Y0 = 70, 950, 150, 172, 840


def _choice_card(q_idx, text, i, reveal, is_correct):
    """One answer card on its own transparent layer so it can slide in."""
    y = CARD_Y0 + i * CARD_STEP
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    box = (CARD_X0, y, CARD_X1, y + CARD_H)
    light, dark = LETTER_GRADS[i]
    if is_correct:
        _shadow(layer, box, 44, blur=30, alpha=200, dy=0, color=GREEN[0])
        _card(layer, box, 44, GREEN[0], GREEN[1], outline=(255, 255, 255, 255), ow=6, shadow=False)
    elif reveal:
        _card(layer, box, 44, fill=(30, 28, 45, 225), shadow=False)
    else:
        _card(layer, box, 44, light, dark, alpha=245)
    cx, cy = CARD_X0 + 78, y + CARD_H // 2
    dim = reveal and not is_correct
    _circle(layer, cx, cy, 52, (255, 255, 255, 120 if dim else 245))
    _ctext(layer, cx, cy, LETTERS[i], font(66), fill=((90, 90, 100, 255) if dim else dark + (255,)))
    f, lines = _fit(text, CARD_X1 - CARD_X0 - 250, CARD_H - 20, 54, 32, gap=1.15)
    lh = int(f.size * 1.18)
    ty = cy - (lh * len(lines)) // 2
    color = (200, 200, 205, 255) if dim else (255, 255, 255, 255)
    for ln in lines:
        _text(layer, (CARD_X0 + 160, ty), ln, f, fill=color, anchor="lt", shadow=not dim)
        ty += lh
    if is_correct:
        d = ImageDraw.Draw(layer)
        px, py = CARD_X1 - 62, cy
        d.line([(px - 22, py + 2), (px - 6, py + 20), (px + 24, py - 18)], fill=(255, 255, 255, 255), width=12, joint="curve")
    return layer


def draw_quiz(q_num, total, question, choices, correct_idx, category="", visible=0, anim=1.0,
              timer=None, reveal=False, think=5, seed=0):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # soft dark gradient top and bottom so text stays readable on any footage
    top = _grad_img(W, 700, (0, 0, 0), (0, 0, 0), 255, horizontal=False)
    a = np.linspace(150, 0, 700, dtype=np.float32)[:, None]
    top.putalpha(Image.fromarray(np.broadcast_to(a, (700, W)).astype("uint8")))
    img.alpha_composite(top, (0, 0))
    bot = _grad_img(W, 700, (0, 0, 0), (0, 0, 0), 255, horizontal=False)
    a = np.linspace(0, 170, 700, dtype=np.float32)[:, None]
    bot.putalpha(Image.fromarray(np.broadcast_to(a, (700, W)).astype("uint8")))
    img.alpha_composite(bot, (0, H - 700))

    if reveal:  # confetti sits behind the cards
        _confetti(img, seed + q_num, (40, 330, 1040, 1560))

    # header: question pill + category pill
    label = f"QUESTION {q_num}/{total}"
    f = font(40)
    tw = int(f.getlength(label))
    _card(img, (60, 140, 60 + tw + 70, 218), 39, GOLD, (255, 160, 20), shadow=True)
    _text(img, (95, 180), label, f, fill=(30, 20, 0, 255), anchor="lm", shadow=False)
    if category:
        cat = category.split(":")[-1].strip().upper()[:22]
        cf = font(34)
        cw = int(cf.getlength(cat))
        _card(img, (W - 60 - cw - 60, 146, W - 60, 212), 33, fill=(0, 0, 0, 150), outline=(255, 255, 255, 110), ow=3,
              shadow=False)
        _text(img, (W - 90 - cw // 2 + 0, 179), cat, cf, anchor="mm", shadow=False)

    # progress bar
    done = (q_num - 1 + (1 if reveal else 0.5)) / total
    _card(img, (60, 246, 1020, 262), 8, fill=(255, 255, 255, 70), shadow=False)
    if done > 0:
        _card(img, (60, 246, 60 + max(24, int(960 * done)), 262), 8, GOLD, (255, 120, 40), shadow=False)

    # question card
    qbox = (60, 296, 1020, 640)
    _card(img, qbox, 48, fill=(14, 12, 30, 238), outline=GOLD + (255,), ow=5)
    f, lines = _fit(question, 840, 290, 74, 38)
    lh = int(f.size * 1.22)
    y = 296 + (344 - lh * len(lines)) // 2
    for ln in lines:
        _text(img, (540, y), ln, f, anchor="mt")
        y += lh

    # timer ring or reveal banner (between question and answers)
    cx, cy = 540, 732
    if reveal:
        _card(img, (300, cy - 44, 780, cy + 44), 44, GREEN[0], GREEN[1], outline=(255, 255, 255, 255), ow=4)
        _ctext(img, 540, cy, "CORRECT ANSWER", font(42))
    elif timer is not None:
        left = max(0.0, timer)
        urgent = left <= 2.0
        col = (255, 80, 80, 255) if urgent else GOLD + (255,)
        _circle(img, cx, cy, 62, (0, 0, 0, 170))
        _ring(img, cx, cy, 62, 9, left / think, col)
        _ctext(img, cx, cy, str(max(1, math.ceil(left))), font(74), fill=col)

    # answer cards (newest one slides in from the right)
    for i in range(visible):
        layer = _choice_card(q_num, choices[i], i, reveal, reveal and i == correct_idx)
        if i == visible - 1 and anim < 1.0:
            e = 1 - (1 - anim) ** 3
            shift = int((1 - e) * 420)
            alpha = layer.getchannel("A").point(lambda v: int(v * e))
            layer.putalpha(alpha)
            moved = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            moved.paste(layer, (shift, 0))
            layer = moved
        img.alpha_composite(layer)

    return img


def draw_title(title, subtitle=""):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    veil = Image.new("RGBA", (W, H), (0, 0, 0, 90))
    img.alpha_composite(veil)
    box = (60, 600, 1020, 1280)
    _card(img, box, 64, fill=(14, 12, 30, 225), outline=GOLD + (255,), ow=6)
    f, lines = _fit(title, 840, 320, 120, 60, gap=1.15)
    lh = int(f.size * 1.15)
    sf, slines = _fit(subtitle, 840, 150, 54, 34) if subtitle else (font(40), [])
    slh = int(sf.size * 1.2)
    block = lh * len(lines) + (50 + slh * len(slines) if slines else 0)
    y = 600 + (680 - block) // 2
    for ln in lines:
        _text(img, (540, y), ln, f, anchor="mt")
        y += lh
    y += 50
    for ln in slines:
        _text(img, (540, y), ln, sf, fill=GOLD + (255,), anchor="mt")
        y += slh
    return img


def make_overlay(kind, args):
    return draw_title(**args) if kind == "title" else draw_quiz(**args)


def _vcodec_args():
    enc = env("VIDEO_ENCODER", "libx264")
    if enc == "libx264":
        return ["-c:v", "libx264", "-preset", env("X264_PRESET", "veryfast"), "-crf", env("VIDEO_CRF", "24")]
    if enc == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "22", "-b:v", "0"]
    return ["-c:v", enc]


def _q(path) -> str:
    return path.as_posix().replace("'", "'\\''")


def render_segment(bg, frame_specs, duration, out_path, tmp):
    """frame_specs: list of (start_time, kind, args). Each overlay holds until the next one starts."""
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

    vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30,"
          "eq=brightness=-0.06:saturation=1.3:contrast=1.08,vignette=angle=PI/5[bg];[1:v]format=rgba[ov];[bg][ov]overlay=0:0:format=auto,format=yuv420p[v]")
    run_ffmpeg(["-stream_loop", "-1", "-i", bg, "-f", "concat", "-safe", "0", "-i", lst,
                "-filter_complex", vf, "-map", "[v]", "-t", f"{duration:.3f}", "-an"]
               + _vcodec_args() + ["-pix_fmt", "yuv420p", "-r", "30", out_path])


def concat_videos(paths, out, tmp):
    lst = tmp / "segments.txt"
    lst.write_text("".join(f"file '{_q(p)}'\n" for p in paths), encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])


def mux(video, audio_wav, out):
    run_ffmpeg(["-i", video, "-i", audio_wav, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart", out])
