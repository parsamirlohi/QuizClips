"""Optional: pre-make every look's background loop now, so the first video with a new look isn't slower.
Run:  python3 tools/make_backgrounds.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so the app's modules import from here
import time

import looks

for key in looks.LOOKS:
    t0 = time.time()
    looks.ensure_background(key)
    print(f"{key}: ok ({time.time() - t0:.0f}s)", flush=True)
