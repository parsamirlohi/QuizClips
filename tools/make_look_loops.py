"""Makes the looping preview videos of the looks (animated background + stock clip + the question overlay).

  static/looks/loops/hd/<key>.mp4      one per look, for the big phone (home page and Studio): the moving background and the
                                       stock clip ONLY, without the question graphics
  static/looks/overlay/<key>.webp      the question graphics on their own, full size and sharp, with a see-through picture
                                       box. The page lays this over the video, so the text and edges stay crisp.
  static/looks/loops/strip/<key>.mp4   one per look, small: plays in a tile of the scrolling strip only while you point at it

Run:  python3 tools/make_look_loops.py            (makes any that are missing)
      python3 tools/make_look_loops.py --all      (re-makes everything)
      python3 tools/make_look_loops.py --all --only hd      (or --only strip)

Needs the stock clips from tools/make_look_thumbs.py --clips (static/looks/clips/<key>.mp4); a look without one
shows just its animated background. 
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so the app's modules import from here
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image

import looks
import preview_data
import render
from config import BASE, run_ffmpeg

LOOPS = BASE / "static" / "looks" / "loops"
CLIPS = BASE / "static" / "looks" / "clips"
SECONDS = 12            # the background loops every 6 s and the clip every 4 s, so 12 s joins up cleanly
TILE_W, TILE_H = 360, 640   # a strip tile is 150 px wide on the page, so this is sharp on a 2x screen
HD_W, HD_H = 900, 1600


def make_tile(key, look, tmp, W, H, out, crf, still=False, graphics=True):
    S = W / 1080
    p = preview_data.PREVIEWS[key]
    clip = CLIPS / (f"{key}.jpg" if still else f"{key}.mp4")   # still: the stock picture is held as one frame
    has_clip = clip.exists()
    loop_in = ["-loop", "1", "-framerate", "24"] if still else ["-stream_loop", "-1"]
    render.BORDER_RADIUS = render.PREVIEW_RADIUS   # rounded border: these pictures sit in the phone preview
    render.apply_skin(look["skin"])
    overlay = render.draw_scene(theme="purple", header=p["q"], label="QUESTION 1/5", choices=list(p["a"]),
                                visible=4, anim=1.0, q_num=1, num_label="1")
    png = tmp / f"{key}_{W}.png"
    overlay.resize((W, H), Image.LANCZOS).save(png)
    if not graphics:   # the phone: the graphics are kept apart, full size, and laid over the video by the page
        ovdir = BASE / "static" / "looks" / "overlay"
        ovdir.mkdir(parents=True, exist_ok=True)
        overlay.save(ovdir / f"{key}.webp", lossless=True, method=6)
    cw, ch = render.CLIP[2] - render.CLIP[0], render.CLIP[3] - render.CLIP[1]
    cx, cy = round(render.CLIP[0] * S), round(render.CLIP[1] * S)
    cw2, ch2 = round(cw * S), round(ch * S)

    blur = look.get("blur") if has_clip else None
    inputs, parts = [], []
    if blur:   # like the real video: the clip itself, blown up, blurred and darkened
        inputs += loop_in + ["-i", str(clip)]
        parts.append("[0:v]split=2[s1][s2];")
        bg = (f"[s1]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,setsar=1,fps=24,gblur=sigma=8,"
              f"eq=brightness={-blur.get('dark', 0.3):.2f}:saturation={blur.get('sat', 0.9):.2f}")
        if blur.get("tint"):
            bg += f",drawbox=x=0:y=0:w=iw:h=ih:color=0x{blur['tint']}@{blur.get('alpha', 0.35)}:t=fill"
        parts.append(bg + f",scale={W}:{H}:flags=bicubic[bg];")
        src, nxt = "s2", 1
    else:
        inputs += ["-stream_loop", "-1", "-i", str(looks.ensure_background(key))]
        parts.append(f"[0:v]scale={W}:{H}:flags=bicubic,setsar=1,fps=24[bg];")
        src, nxt = None, 1
        if has_clip:
            inputs += loop_in + ["-i", str(clip)]
            src, nxt = "1:v", 2
    if has_clip:
        parts.append(f"[{src}]scale={cw2}:{ch2}:force_original_aspect_ratio=increase:flags=lanczos,crop={cw2}:{ch2},setsar=1,fps=24[c];")
        parts.append(f"[bg][c]overlay={cx}:{cy}[b2];")
        base = "b2"
    else:
        base = "bg"
    if graphics:
        inputs += ["-i", str(png)]
        parts.append(f"[{nxt}:v]format=rgba[ov];[{base}][ov]overlay=0:0:format=auto,format=yuv420p[v]")
    else:
        parts.append(f"[{base}]format=yuv420p[v]")
    run_ffmpeg(inputs + ["-filter_complex", "".join(parts), "-map", "[v]", "-t", str(SECONDS), "-an",
                         "-c:v", "libx264", "-crf", str(crf), "-preset", "slow", "-pix_fmt", "yuv420p",
                         "-r", "24", "-movflags", "+faststart", str(out)])
    print(f"  tile {key}: {out.stat().st_size // 1024} KB" + ("" if has_clip else "  (no stock clip yet)"), flush=True)


if __name__ == "__main__":
    redo = "--all" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    keys = list(looks.LOOKS)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        if only in (None, "hd"):
            (LOOPS / "hd").mkdir(parents=True, exist_ok=True)
            for key in keys:
                out = LOOPS / "hd" / f"{key}.mp4"
                if out.exists() and not redo:
                    print("already there: hd", key, flush=True)
                    continue
                try:
                    make_tile(key, looks.LOOKS[key], tmp, HD_W, HD_H, out, 22, graphics=False)
                except Exception as e:
                    print(f"could not make {key}: {str(e)[:300]}", flush=True)
        if only in (None, "strip"):
            (LOOPS / "strip").mkdir(parents=True, exist_ok=True)
            for key in keys:
                out = LOOPS / "strip" / f"{key}.mp4"
                if out.exists() and not redo:
                    print("already there: strip", key, flush=True)
                    continue
                try:
                    make_tile(key, looks.LOOKS[key], tmp, TILE_W, TILE_H, out, 22)
                except Exception as e:
                    print(f"could not make {key}: {str(e)[:300]}", flush=True)
    render.reset_skin()
