"""Works out what each question's footage should actually SHOW.

With a GEMINI_API_KEY (free tier available) or an ANTHROPIC_API_KEY in .env, an AI model reads each question (and its category, never the answer) and writes
visual search terms ("airport", "airplane runway" for a Manchester airport question). Without one, each content
word of the question is checked against Pixabay's own photo counts, so words that are really filmable
("airport") rank above words that are not ("abbreviation").
"""
import json
import re

import requests

import gemini

from config import flog, env, is_mock
from questions import EXTRA_STOP, GENERIC, STOP

_TOTALS: dict = {}


def _dedupe(items):
    out = []
    for x in items:
        x = (x or "").strip()
        if x and x.lower() not in [o.lower() for o in out]:
            out.append(x)
    return out


def _prompt(quiz):
    items = [{"i": i, "category": q.get("category", ""), "question": q["question"]} for i, q in enumerate(quiz)]
    return (
        "You choose stock-footage search terms for the background clip behind each trivia question in a vertical "
        "quiz video. The clip must make the viewer think of what the question is ABOUT the moment they see it, "
        "without giving away the answer. Write 4 search terms per question, built like this:\n"
        "1. The single most recognisable thing you can FILM that the question is about: its subject, place, object, "
        "animal, activity or scene (1-2 plain words, e.g. 'tokyo city', 'guitar playing', 'ocean waves').\n"
        "2. The same subject in a different shot or with a motion/visual word that stock sites tag clips with "
        "('sea aerial', 'coffee pour', 'mountain peak snow', 'city night').\n"
        "3. A broader scene from the same world ('planet space', 'stars night sky', 'art museum').\n"
        "4. A safe, general fallback in the same area ('nature landscape', 'city street', 'science laboratory').\n"
        "Rules: use the common everyday name of things, never jargon, model numbers or people's names (use the "
        "place, object or activity associated with them instead: a painter -> 'painting art museum'). Pick things "
        "with a clear look that a camera captures well; avoid words with several meanings that stock sites mis-tag "
        "(die, bat, bar, plant, mouse, pitcher, seal; say 'dice' not 'd20 die'). For abstract questions (maths, "
        "dates, grammar, abbreviations, famous quotes) film the nearest concrete world the topic lives in: "
        "numbers -> 'calculator numbers', language -> 'books library', history -> 'old map', computers -> "
        "'laptop keyboard'. The topic's subject is fine, but do NOT search for the correct answer itself when the "
        "question asks you to identify it (for 'Which city is nicknamed the Big Apple?' do not use 'new york city'; "
        "use 'city skyline night' and 'usa city street'). Never use words from the answer choices if they would "
        "give the answer away.\n"
        "Examples: 'What is the capital of Japan?' -> [\"japan\", \"asian city night\", \"city skyline\", \"travel city\"]; "
        "'How many strings does a standard guitar have?' -> [\"guitar playing\", \"guitar strings\", \"music studio\", "
        "\"concert stage\"]; 'What do honey bees make?' -> [\"honey bee\", \"bees on flowers\", \"beehive\", "
        "\"meadow flowers\"]; 'What is the abbreviation for Manchester Airport?' -> [\"airport\", \"airplane runway\", "
        "\"airport terminal\", \"airplane sky\"]; 'What does USB stand for?' -> [\"usb cable\", \"computer\", "
        "\"laptop keyboard\", \"technology desk\"]. Reply with ONLY a JSON array of arrays of strings, one inner "
        "array per question, in order.\n\n" + json.dumps(items)
    )


def _parse(text, n):
    data = json.loads(text[text.index("["): text.rindex("]") + 1])
    rows = [[str(x) for x in row][:4] for row in data if isinstance(row, list)]
    if len(rows) != n:
        raise ValueError(f"expected {n} rows of search terms, got {len(rows)}")
    return rows


def _claude_queries(quiz):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": env("CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 1500,
              "messages": [{"role": "user", "content": _prompt(quiz)}]},
        timeout=60,
    )
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", []))
    return _parse(text, len(quiz))


def _gemini_queries(quiz):
    return _parse(gemini.generate([{"text": _prompt(quiz)}]), len(quiz))


def _llm_provider():
    """FOOTAGE_LLM = gemini | claude | none. Unset: Gemini if its key exists, else Claude, else no AI."""
    choice = env("FOOTAGE_LLM").lower()
    if choice in ("none", "off", "no"):
        return None
    if choice == "gemini" or (not choice and env("GEMINI_API_KEY")):
        return ("Gemini", _gemini_queries) if env("GEMINI_API_KEY") else None
    if choice == "claude" or (not choice and env("ANTHROPIC_API_KEY")):
        return ("Claude", _claude_queries) if env("ANTHROPIC_API_KEY") else None
    return None


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
    provider = _llm_provider()
    if provider:
        name, fn = provider
        try:
            extra = fn(quiz)
            flog(f"[footage] {name} wrote the search terms")
        except Exception as e:
            flog(f"[footage] {name} search terms failed ({str(e)[:100]}); using Pixabay ranking")
    key = env("PIXABAY_API_KEY")
    for i, q in enumerate(quiz):
        if extra and i < len(extra) and extra[i]:
            front = extra[i]
        elif key:
            front = _ranked_words(q["question"], key)
        else:
            front = []
        q["video_queries"] = _dedupe(list(front) + list(q.get("video_queries", [])))
        flog(f"[footage] Q{i + 1} searches: {q['video_queries'][:4]}")
