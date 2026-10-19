"""Looks at a frame from each candidate clip and rejects footage that doesn't fit the question.

Stock sites tag loosely (a snowy white log cabin matches 'white house'), so tags alone can't tell. Gemini scores each
candidate picture 0-10 for how clearly it shows something a viewer would link to the question. It sees the question
text only, never the answer. Turn off with VISION_CHECK=0. Any failure just means 'skip the check'.
"""
import base64
import json
import threading
import time

import gemini
from config import env, flog

_last_call = [0.0]
_gate = threading.Lock()


def enabled() -> bool:
    return gemini.available() and env("VISION_CHECK", "1") != "0"


def _min_score() -> int:
    try:
        return int(env("VISION_MIN", "6"))
    except ValueError:
        return 6


def _gap() -> float:
    try:
        return float(env("VISION_GAP", "4.5"))   # seconds between picture checks; lower it if your Gemini key allows more requests per minute
    except ValueError:
        return 4.5


def _throttle():
    with _gate:   # several scenes look for footage at once; their picture checks still go out one at a time
        wait = _gap() - (time.time() - _last_call[0])  # keeps us under ~13 requests/minute on the free tier
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()


def choose(cands: list, question: str, term: str):
    """cands = [(hit, jpeg_bytes)]. Returns ("ok", hit, score), ("reject", None, best_score) or ("skip", None, None)."""
    prompt = (
        f"A quiz video shows this question on screen: \"{question}\"\n"
        f"The footage was searched for: \"{term}\".\n"
        f"Below are {len(cands)} candidate background pictures, in order. Score each from 0 to 10 for how clearly it "
        "shows something a viewer would naturally associate with the question's subject (a place, object, activity or "
        "scene about the topic). 0 = unrelated or misleading, 10 = obviously about this topic. Example: for 'Who was "
        "the 45th US president?' a White House exterior, US flag or Capitol scores high; a snowy log cabin, a random "
        "landscape or abstract lights score 0-2. Do not try to answer the question. A picture that only works as a symbol or metaphor (for example a peacock for a question about being confident or social) scores 0-3; people or a setting that actually match what the question describes score high. "
        f"Reply with ONLY a JSON array of {len(cands)} integers."
    )
    parts = [{"text": prompt}]
    for _, img in cands:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}})
    text = None
    for attempt in range(2):
        _throttle()
        try:
            text = gemini.generate(parts, timeout=30)
            break
        except gemini.RateLimited:
            if attempt == 0:
                time.sleep(8)
        except Exception as e:
            flog(f"[footage] picture check skipped ({str(e)[:90]})")
            return ("skip", None, None)
    if text is None:
        flog("[footage] picture check skipped (rate limit)")
        return ("skip", None, None)
    try:
        scores = [int(x) for x in json.loads(text[text.index("["): text.rindex("]") + 1])]
        if len(scores) != len(cands):
            raise ValueError("wrong number of scores")
    except Exception as e:
        flog(f"[footage] picture check skipped (bad reply: {str(e)[:60]})")
        return ("skip", None, None)
    best = max(range(len(scores)), key=lambda i: scores[i])
    flog(f"[footage]   picture scores {scores} for '{term}'")
    if scores[best] >= _min_score():
        return ("ok", cands[best][0], scores[best])
    flog(f"[footage]   none fit well enough (need {_min_score()}+), trying the next search")
    return ("reject", None, scores[best])
