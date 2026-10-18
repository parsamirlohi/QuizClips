"""Turns waitlist.jsonl into waitlist.csv (open it in Excel or Google Sheets).  Run: python3 export_waitlist.py"""
import csv
import json
from pathlib import Path

src = Path(__file__).parent / "waitlist.jsonl"
if not src.exists():
    raise SystemExit("No sign-ups yet.")
rows = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
out = src.with_suffix(".csv")
with out.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["at", "email", "plan", "interest"])
    w.writeheader()
    w.writerows(rows)
print(f"{len(rows)} sign-ups written to {out.name}")
