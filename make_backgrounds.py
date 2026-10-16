"""Optional: pre-make every look's background loop now, so the first video with a new look isn't slower.
Run:  python3 make_backgrounds.py"""
import time

import looks

for key in looks.LOOKS:
    t0 = time.time()
    looks.ensure_background(key)
    print(f"{key}: ok ({time.time() - t0:.0f}s)", flush=True)
