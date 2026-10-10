"""Where quiz questions come from, plus helpers for shuffling answer letters.

Default source is Open Trivia DB (free, no key). If ANTHROPIC_API_KEY is set, Claude
writes the questions instead, along with a video search phrase that matches each
question without giving away the answer.
"""
import hashlib
import json
import random
import re
import time
import urllib.parse

import requests

from config import BASE, env, is_mock

HISTORY_FILE = BASE / "history.json"
LETTERS = "ABCD"

STOP = set(
    """a an the of in on at to for from by with and or but is are was were be been being do does did
what which who whom whose where when why how many much this that these those it its as into than then
there their they them he she his her you your we our i me my first last most least commonly common
known called name named type types kind following would could should will can may might one two three
four also year years about after before during between among under over all any each other another
such only true false story things thing something someone""".split()
)

CATEGORY_QUERY = {
    "general knowledge": "library books",
    "science & nature": "nature science",
    "science: computers": "computer technology",
    "science: mathematics": "mathematics chalkboard",
    "science: gadgets": "gadgets technology",
    "geography": "world map travel",
    "history": "ancient ruins",
    "sports": "sports stadium",
    "animals": "wild animals",
    "vehicles": "cars driving",
    "mythology": "ancient temple",
    "art": "art gallery painting",
    "celebrities": "red carpet lights",
    "politics": "government building",
    "entertainment: film": "cinema movie theater",
    "entertainment: music": "concert lights",
    "entertainment: television": "television screen",
    "entertainment: video games": "gaming controller",
    "entertainment: books": "library books",
    "entertainment: board games": "board game",
    "entertainment: japanese anime & manga": "japan city night",
    "entertainment: cartoon & animations": "colorful cartoon",
    "entertainment: comics": "comic books",
    "entertainment: musicals & theatres": "theater stage",
}


# Categories that tend to have obscure questions the average viewer can't answer.
NICHE_CATEGORIES = {
    "entertainment: japanese anime & manga", "entertainment: board games", "entertainment: comics",
    "entertainment: musicals & theatres", "science: computers", "science: mathematics",
    "science: gadgets", "politics", "art", "celebrities", "vehicles", "mythology",
}


def _qid(text: str) -> str:
    return hashlib.sha1(text.strip().lower().encode("utf-8")).hexdigest()[:16]


def _load_history() -> dict:
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def mark_used(questions: list) -> None:
    h = _load_history()
    for q in questions:
        h[_qid(q["question"])] = q["question"]
    HISTORY_FILE.write_text(json.dumps(h), encoding="utf-8")


def category_query(category: str) -> str:
    c = (category or "").lower().strip()
    return CATEGORY_QUERY.get(c, c.split(":")[-1].strip())


EXTRA_STOP = set(
    """contain contains containing use used uses using famous original appear appears appeared released
release written wrote write made makes make become became becomes located found besides based term
word words referred refer main primary popular begin began begins end ends ended often usually
generally typically approximately roughly nickname known say says said tell tells told give gives
gave called call play plays played playing included include includes including belong belongs
belonged derived derive comes come came held hold take takes took taken get gets got
largest smallest biggest tallest highest lowest longest shortest fastest slowest oldest youngest
perform species system systems group member members period century number numbers kind part parts
solar person people place places thing event events""".split()
)


def keywords_from(question: str, correct: str, category: str) -> list:
    """Search words for stock footage, best first, never using words that give away the answer.

    Stock sites match single concrete words far better than long phrases, so this tries
    proper nouns first, then single nouns (longest first), then the topic, then a generic fallback.
    """
    # Words come from the question itself, so they can't spoil the answer.
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", question)
    caps, rest = [], []
    for i, w in enumerate(words):
        lw = w.lower().strip("'-")
        if lw in STOP or lw in EXTRA_STOP or len(lw) < 4:
            continue
        if lw.endswith("'s"):
            w = w[:-2]
        (caps if (w[0].isupper() and i > 0) else rest).append(w)
    rest.sort(key=len, reverse=True)
    queries = []
    if len(caps) >= 2:
        queries.append(" ".join(caps[:2]))
    for w in caps[:2]:
        queries.append(w)
    for w in rest[:3]:
        queries.append(w.lower())
    if len(rest) >= 2:
        queries.append(f"{rest[0].lower()} {rest[1].lower()}")
    cat = category_query(category)
    if cat:
        queries.append(cat)
    queries.append("abstract colorful background")
    out = []
    for q in queries:
        if q and q not in out:
            out.append(q)
    return out


def _usable(q: str, correct: str, wrong: list) -> bool:
    answers = [correct] + wrong
    if len(q) > 150 or any(len(a) > 40 for a in answers):
        return False
    if len({a.lower() for a in answers}) != 4:
        return False
    if re.search(r"(?i)\b(this image|pictured|shown|following (image|picture|photo|logo|clip))\b", q):
        return False
    if any(re.search(r"(?i)(of the above|both a|both b)", a) for a in answers):
        return False
    return True


def _from_opentdb() -> list:
    url = "https://opentdb.com/api.php?amount=50&type=multiple&difficulty=easy&encode=url3986"
    data = None
    for _ in range(3):
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if data.get("response_code") == 0:
                    break
        except requests.RequestException:
            pass
        time.sleep(6)  # Open Trivia DB allows one request per 5 seconds
    if not data or data.get("response_code") != 0:
        raise RuntimeError("Could not fetch questions from Open Trivia DB. Try again in a few seconds.")
    u = urllib.parse.unquote
    out = []
    for item in data["results"]:
        q, correct = u(item["question"]), u(item["correct_answer"])
        wrong = [u(x) for x in item["incorrect_answers"]]
        cat = u(item["category"])
        if cat.lower() in NICHE_CATEGORIES or not _usable(q, correct, wrong):
            continue
        out.append(
            {"question": q, "correct": correct, "wrong": wrong, "category": cat,
             "video_queries": keywords_from(q, correct, cat)}
        )
    return out


def _from_claude(n: int, avoid: list) -> list:
    avoid_text = "\n".join(f"- {a}" for a in avoid) or "(none)"
    prompt = f"""Create {n + 4} diverse, fun trivia questions for a short TikTok quiz video.

Rules:
- Mix topics: science, history, geography, pop culture, animals, food, sports, space, etc.
- EASY, widely known questions that most people could answer (school-level or everyday general knowledge). No obscure trivia, niche fandoms, or specific dates/statistics.
- Exactly one clearly correct answer.
- Question under 110 characters. Each answer under 28 characters.
- No "all of the above" / "none of the above" and nothing that needs an image.
- "video_query": 2-3 words describing real stock footage that visually fits the question's topic
  WITHOUT revealing the answer (for "Which planet has the most moons?" use "night sky stars").
- Do not repeat these earlier questions:
{avoid_text}

Return ONLY a JSON array of objects with keys:
"question", "correct_answer", "wrong_answers" (exactly 3 strings), "category", "video_query"."""
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": env("CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 4000,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=90,
    )
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", []))
    m = re.search(r"\[.*\]", text, re.S)
    items = json.loads(m.group(0))
    out = []
    for it in items:
        q, correct = it["question"].strip(), it["correct_answer"].strip()
        wrong = [w.strip() for w in it["wrong_answers"]][:3]
        if len(wrong) != 3 or not _usable(q, correct, wrong):
            continue
        cat = it.get("category", "")
        queries = [it.get("video_query", "")] + keywords_from(q, correct, cat)
        out.append({"question": q, "correct": correct, "wrong": wrong, "category": cat,
                    "video_queries": [x for x in queries if x]})
    return out


_MOCK_BANK = [
    ("What is the capital of France?", "Paris", ["Berlin", "Madrid", "Rome"], "Geography", "city skyline"),
    ("Which planet is known as the Red Planet?", "Mars", ["Venus", "Jupiter", "Saturn"], "Science", "night sky"),
    ("How many legs does a spider have?", "Eight", ["Six", "Ten", "Twelve"], "Animals", "forest nature"),
    ("What is the largest ocean on Earth?", "Pacific", ["Atlantic", "Indian", "Arctic"], "Geography", "ocean waves"),
    ("Which gas do plants absorb from the air?", "Carbon dioxide", ["Oxygen", "Helium", "Neon"], "Science", "green leaves"),
    ("Who painted the Mona Lisa?", "Leonardo da Vinci", ["Michelangelo", "Raphael", "Picasso"], "Art", "art museum"),
    ("What is the hardest natural substance?", "Diamond", ["Gold", "Iron", "Quartz"], "Science", "crystals"),
    ("Which animal is the tallest in the world?", "Giraffe", ["Elephant", "Horse", "Camel"], "Animals", "savanna"),
    ("How many continents are there?", "Seven", ["Five", "Six", "Eight"], "Geography", "world map"),
    ("What do bees make?", "Honey", ["Silk", "Wax paper", "Sugar"], "Animals", "flowers garden"),
    ("Which sport uses a shuttlecock?", "Badminton", ["Tennis", "Squash", "Golf"], "Sports", "sports hall"),
    ("What is frozen water called?", "Ice", ["Steam", "Fog", "Dew"], "Science", "winter snow"),
]


def _mock_pool() -> list:
    return [{"question": q, "correct": c, "wrong": w, "category": cat,
             "video_queries": [vq, "abstract background"]} for q, c, w, cat, vq in _MOCK_BANK]


def get_questions(n: int) -> list:
    history = _load_history()
    if is_mock():
        pool = _mock_pool()
    else:
        source = (env("QUESTION_SOURCE") or ("claude" if env("ANTHROPIC_API_KEY") else "opentdb")).lower()
        pool = None
        if source == "claude":
            try:
                pool = _from_claude(n, list(history.values())[-40:])
            except Exception as e:
                print(f"[questions] Claude failed ({e}); falling back to Open Trivia DB")
        if not pool:
            pool = _from_opentdb()
    fresh = [q for q in pool if _qid(q["question"]) not in history]
    stale = [q for q in pool if _qid(q["question"]) in history]
    random.shuffle(fresh)
    random.shuffle(stale)
    picked = (fresh + stale)[:n]
    if len(picked) < n:
        raise RuntimeError(f"Only found {len(picked)} usable questions, needed {n}. Try again.")
    return picked


def pick_letters(n: int) -> list:
    """Index (0-3) of the correct answer for each question: varied, never the same twice in a row."""
    out = []
    while len(out) < n:
        cycle = [0, 1, 2, 3]
        random.shuffle(cycle)
        if out and cycle[0] == out[-1]:
            cycle.append(cycle.pop(0))
        out += cycle
    return out[:n]
