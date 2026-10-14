"""Works out what each question's footage should actually SHOW.

With an ANTHROPIC_API_KEY in .env, Claude reads each question (and its category, never the answer) and writes
visual search terms ("airport", "airplane runway" for a Manchester airport question). Without one, each content
word of the question is checked against Pixabay's own photo counts, so words that are really filmable
("airport") rank above words that are not ("abbreviation").
"""
import json
import re

import requests

from config import env, is_mock
from questions import EXTRA_STOP, GENERIC, STOP

_TOTALS: dict = {}


def _dedupe(items):
    out = []
    for x in items:
        x = (x or "").strip()
        if x and x.lower() not in [o.lower() for o in out]:
            out.append(x)
    return out


def _claude_queries(quiz):
    items = [{"i": i, "category": q.get("category", ""), "question": q["question"]} for i, q in enumerate(quiz)]
    prompt = (
        "For each trivia question, give 3 stock-footage search terms for a short background clip that shows what "
        "the question is ABOUT, so a viewer sees something clearly related. Rules: 1-3 plain words each, concrete "
        "things you can film (an object, place, animal, activity or scene), ordered from most specific to most "
        "general but still related. Prefer the real-world subject over names. Examples: 'What is the abbreviation "
        "for Manchester Airport?' -> [\"airport\", \"airplane runway\", \"airport terminal\"]; 'Who voiced Batman?' -> "
        "[\"film set\", \"movie camera\", \"cinema\"]; 'What does USB stand for?' -> [\"usb cable\", \"computer\", "
        "\"laptop keyboard\"]. Reply with ONLY a JSON array of arrays of strings, one inner array per question, in "
        "order.\n\n" + json.dumps(items)
    )
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": env("CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 1500,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", []))
    data = json.loads(text[text.index("["): text.rindex("]") + 1])
    return [[str(x) for x in row][:3] for row in data]


def _total(word, key):
    if word in _TOTALS:
        return _TOTALS[word]
    n = 0
    try:
        r = requests.get("https://pixabay.com/api/", params={"key": key, "q": word, "image_type": "photo",
                                                              "per_page": 3, "safesearch": "true"}, timeout=20)
        if r.status_code == 200:
            n = int(r.json().get("totalHits", 0))
    except Exception:
        n = 0
    _TOTALS[word] = n
    return n


def _ranked_words(question, key):
    words = []
    for w in re.findall(r"[A-Za-z][A-Za-z'\-]+", question):
        lw = w.lower().strip("'-")
        if lw.endswith("'s"):
            lw = lw[:-2]
        if len(lw) >= 4 and lw not in STOP and lw not in EXTRA_STOP and lw not in GENERIC and lw not in words:
            words.append(lw)
    scored = sorted(((_total(w, key), w) for w in words[:6]), reverse=True)
    return [w for n, w in scored if n >= 300][:2]


def refine_queries(quiz):
    """Put better, picture-minded searches in front of each question's existing ones."""
    if is_mock():
        return
    extra = None
    if env("ANTHROPIC_API_KEY"):
        try:
            extra = _claude_queries(quiz)
            print("[footage] Claude wrote the search terms", flush=True)
        except Exception as e:
            print(f"[footage] Claude search terms failed ({str(e)[:80]}); using Pixabay ranking", flush=True)
    key = env("PIXABAY_API_KEY")
    for i, q in enumerate(quiz):
        if extra and i < len(extra) and extra[i]:
            front = extra[i]
        elif key:
            front = _ranked_words(q["question"], key)
        else:
            front = []
        q["video_queries"] = _dedupe(list(front) + list(q.get("video_queries", [])))
        print(f"[footage] Q{i + 1} searches: {q['video_queries'][:4]}", flush=True)
