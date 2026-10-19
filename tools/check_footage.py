"""Optional diagnostic: shows what Pixabay returns for every footage search the app can use.

Run:  python3 tools/check_footage.py
Writes footage_report.txt next to this file (about 1-2 minutes, ~60 requests).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so the app's modules import from here
import time

import config
import questions
import videos

key = config.env("PIXABAY_API_KEY")
if not key:
    raise SystemExit("No PIXABAY_API_KEY found. Run: python3 tools/set_key.py")

searches = []
for cat, themes in questions.CATEGORY_THEMES.items():
    for t in themes:
        searches.append((f"theme: {cat}", t))
for w in ["shark", "planet", "guitar", "zebra", "Australia", "Egypt", "bird", "city"]:
    searches.append(("word", w))
for w in ["neon lights abstract", "bokeh lights", "abstract colorful background"]:
    searches.append(("intro", w))

lines = []
for i, (kind, q) in enumerate(searches, 1):
    try:
        hits = videos._pixabay_hits(q, key)
    except Exception as e:  # keep going so one failure doesn't hide the rest
        lines.append(f"[{kind}] '{q}': ERROR {str(e)[:100]}")
        continue
    ok = [h for h in hits if not videos._is_junk(h)]
    matched = [h for h in ok if videos.tag_score(h, q) > 0]
    lines.append(f"[{kind}] '{q}': {len(hits)} results, {len(ok)} not junk, {len(matched)} with matching tags")
    for h in (matched or ok)[:3]:
        lines.append(f"      tags: {h.get('tags', '')[:90]}")
    print(f"{i}/{len(searches)} {q}", flush=True)
    time.sleep(0.7)

out = config.BASE / "footage_report.txt"
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\nDone. Report saved to {out}")
