"""Shows the search terms the AI planner writes for the 24 look-preview questions, next to the ones picked by hand.
Run on your Mac:  python3 try_footage_terms.py      (needs GEMINI_API_KEY in .env; uses one request)
"""
import footage_plan as fp
import preview_data

qs = [{"question": p["q"], "category": ""} for p in preview_data.PREVIEWS.values()]
rows = fp._gemini_queries(qs)
for (key, p), r in zip(preview_data.PREVIEWS.items(), rows):
    print(p["q"])
    print("   planner:", r)
    print("   by hand:", p["search"])
