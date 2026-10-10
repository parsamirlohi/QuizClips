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
solar person people place places thing event events
world united states president country nation countries government war""".split()
)


CONCRETE = frozenset("""
dog cat horse cow pig sheep goat chicken duck goose turkey rabbit mouse rat squirrel fox wolf bear lion tiger
leopard cheetah elephant giraffe zebra hippo rhino monkey gorilla chimpanzee kangaroo koala panda penguin eagle
owl parrot hawk falcon bat shark whale dolphin octopus jellyfish turtle crocodile alligator snake lizard frog
spider ant bee butterfly dragonfly beetle scorpion camel deer moose bison buffalo seal walrus otter beaver
hedgehog flamingo peacock swan crab lobster fish salmon bird insect dinosaur
planet moon sun star galaxy comet asteroid rocket astronaut telescope earth mars jupiter saturn venus mercury
neptune uranus pluto eclipse
mountain ocean sea river lake waterfall desert volcano island forest jungle glacier ice snow rain storm
lightning thunder cloud rainbow tornado earthquake beach coral cave canyon valley tree flower rose leaf grass
fire water wave
pyramid sphinx eiffel colosseum castle temple bridge tower skyscraper city village map globe compass lighthouse
statue museum cathedral palace
pizza burger bread cheese chocolate coffee tea wine beer apple banana orange lemon grape strawberry tomato
potato corn rice pasta egg milk honey sugar salt pepper cake cookie candy
soccer football basketball baseball tennis golf hockey rugby cricket volleyball swimming running marathon
boxing skiing skating surfing cycling gymnastics olympics stadium
guitar piano drum violin trumpet saxophone orchestra concert microphone singer band
atom molecule chemistry laboratory microscope electricity magnet battery bulb dna cell brain heart bone
computer keyboard phone camera clock watch car train airplane plane ship boat bicycle motorcycle bus truck
helicopter plant plants knight sword armor king queen crown throne viking pirate gold diamond coin money skeleton
""".split())

# Footage themes per category: always related to the question's subject area.
CATEGORY_THEMES = {
    "general knowledge": ["library books", "globe", "old books", "classroom", "lightbulb idea"],
    "science & nature": ["nature", "laboratory", "microscope", "stars space", "chemistry experiment"],
    "geography": ["world map", "globe", "travel landscape", "aerial city", "airplane window"],
    "history": ["ancient ruins", "old castle", "museum", "statue", "old map"],
    "sports": ["sports stadium", "running", "soccer ball", "basketball", "crowd cheering"],
    "animals": ["wildlife", "safari animals", "forest animals", "birds", "ocean animals"],
    "entertainment: music": ["concert lights", "guitar", "piano", "music studio", "dj headphones"],
    "entertainment: film": ["film set", "movie camera", "cinema", "movie theater", "clapperboard", "film reel"],
    "entertainment: television": ["television", "watching tv", "tv studio", "remote control", "living room tv"],
    "entertainment: video games": ["playing video games", "gaming", "gamer", "video game controller", "esports"],
    "entertainment: cartoon & animations": ["cartoon", "animation drawing", "colorful animation", "drawing sketch"],
}
PROPER_OK = {"geography", "history", "sports", "general knowledge"}


def category_themes(category: str) -> list:
    c = (category or "").lower().strip()
    themes = list(CATEGORY_THEMES.get(c, [category_query(category)] if category else ["nature"]))
    random.shuffle(themes)
    return themes


def keywords_from(question: str, correct: str, category: str) -> list:
    """Footage searches, best first. Only real, concrete things are searched by name; anything else
    falls back to footage themed to the question's category, so it is never random."""
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", question)
    cat = (category or "").lower().strip()
    queries, caps = [], []
    for i, w in enumerate(words):
        lw = w.lower().strip("'-")
        if lw.endswith("'s"):
            lw = lw[:-2]
        base = next((c for c in (lw, lw[:-1], lw[:-2]) if c in CONCRETE), None)
        if base and base not in queries:
            queries.append(base)
        elif (w[0].isupper() and i > 0 and lw not in STOP and lw not in EXTRA_STOP and len(lw) >= 4):
            caps.append(w)
    if cat in PROPER_OK:
        if len(caps) >= 2:
            queries.append(" ".join(caps[:2]))
        queries += caps[:2]
    queries = queries[:4] + category_themes(category) + ["abstract colorful background"]
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


# Open Trivia DB category ids. Anything stock footage can't show literally gets themed footage instead.
VISUAL_CATEGORIES = {9: "General Knowledge", 17: "Science & Nature", 22: "Geography", 23: "History",
                     21: "Sports", 27: "Animals", 12: "Entertainment: Music", 11: "Entertainment: Film",
                     14: "Entertainment: Television", 15: "Entertainment: Video Games",
                     32: "Entertainment: Cartoon & Animations"}


def _fetch_category(cid: int):
    url = f"https://opentdb.com/api.php?amount=20&category={cid}&type=multiple&difficulty=easy&encode=url3986"
    for _ in range(3):
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if data.get("response_code") == 0:
                    return data["results"]
        except requests.RequestException:
            pass
        time.sleep(6)  # Open Trivia DB allows one request per 5 seconds
    return []


def _from_opentdb() -> list:
    u = urllib.parse.unquote
    out = []
    for n, cid in enumerate(random.sample(list(VISUAL_CATEGORIES), 3)):
        if n:
            time.sleep(5.5)
        for item in _fetch_category(cid):
            q, correct = u(item["question"]), u(item["correct_answer"])
            wrong = [u(x) for x in item["incorrect_answers"]]
            cat = u(item["category"])
            if cat.lower() in NICHE_CATEGORIES or not _usable(q, correct, wrong):
                continue
            out.append({"question": q, "correct": correct, "wrong": wrong, "category": cat,
                        "video_queries": keywords_from(q, correct, cat)})
    if not out:
        raise RuntimeError("Could not fetch questions from Open Trivia DB. Try again in a few seconds.")
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
