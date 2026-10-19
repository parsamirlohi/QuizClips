"""Shows the search terms the AI planner writes for the 24 look-preview questions, next to the ones picked by hand.
Run on your Mac:  python3 tools/try_footage_terms.py      (needs GEMINI_API_KEY in .env; uses one request)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so the app's modules import from here
import footage_plan as fp
import preview_data

qs = [{"question": p["q"], "category": ""} for p in preview_data.PREVIEWS.values()]
rows = fp._gemini_queries(qs)
for (key, p), r in zip(preview_data.PREVIEWS.items(), rows):
    print(p["q"])
    print("   planner:", r)
    print("   by hand:", p["search"])
