"""Makes the Studio phone preview for the Story video type.

A Story video shows the stock footage across the whole screen, so its preview is one shared full-screen clip with the
story graphics (in the chosen look's colors) laid over it:

  static/looks/story/clip.mp4    the full-screen stock clip, looping
  static/looks/story/clip.jpg    its first frame (shown while the video loads)
  static/looks/story/<key>.webp  the story graphics for each look, full size and sharp, with a see-through picture area

Run:  python3 tools/make_story_preview.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import looks
import render
from config import BASE, run_ffmpeg

OUT = BASE / "static" / "looks" / "story"
SOURCE = BASE / "static" / "looks" / "clips" / "sunburst.mp4"
SAMPLE = dict(header="A storm rolls in over the ridge", label="CHAPTER 1/5", choices=["Keep walking", "Find shelter"])

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-stream_loop", "-1", "-i", str(SOURCE), "-t", "12", "-an", "-vf",
                "scale=720:1280:force_original_aspect_ratio=increase:flags=lanczos,crop=720:1280,setsar=1,fps=24,"
                "eq=brightness=-0.10:saturation=0.9", "-c:v", "libx264", "-crf", "24", "-preset", "slow",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT / "clip.mp4")])
    run_ffmpeg(["-i", str(OUT / "clip.mp4"), "-frames:v", "1", "-q:v", "3", str(OUT / "clip.jpg")])
    render.WATERMARK = ""
    render.BORDER_RADIUS = render.PREVIEW_RADIUS   # rounded border: these pictures sit in the phone preview
    for key, look in looks.LOOKS.items():
        render.apply_skin(look["skin"])
        img = render.draw_story(theme="purple", visible=2, num_label="1", bar_dy=150, **SAMPLE)
        img.save(OUT / f"{key}.webp", lossless=True, method=6)
        print("made", key, flush=True)
    render.reset_skin()
