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
dog cat horse cow pig sheep goat chicken duck goose rabbit rat squirrel fox wolf bear lion tiger
leopard cheetah elephant giraffe zebra hippo rhino monkey gorilla chimpanzee kangaroo koala panda penguin eagle
owl parrot hawk falcon shark whale dolphin octopus jellyfish turtle crocodile alligator snake lizard frog
spider ant bee butterfly dragonfly beetle scorpion camel deer moose bison buffalo walrus otter beaver
hedgehog flamingo peacock swan crab lobster fish salmon bird insect dinosaur
planet moon galaxy comet asteroid rocket astronaut telescope earth mars jupiter saturn venus
neptune uranus eclipse
mountain ocean sea river lake waterfall desert volcano island forest jungle glacier ice snow rain storm
lightning thunder cloud rainbow tornado earthquake beach coral cave canyon valley tree flower leaf grass

pyramid sphinx eiffel colosseum castle temple bridge tower skyscraper city village map globe compass lighthouse
statue museum cathedral palace
pizza burger bread cheese chocolate coffee tea wine beer apple banana lemon grape strawberry tomato
potato corn rice pasta egg milk honey sugar cake cookie candy
soccer football basketball baseball tennis golf hockey rugby volleyball swimming running marathon
boxing skiing skating surfing cycling gymnastics olympics stadium
guitar piano violin trumpet saxophone orchestra concert microphone singer
atom molecule chemistry laboratory microscope electricity magnet battery dna brain heart bone
computer keyboard phone camera clock watch car train airplane plane ship boat bicycle motorcycle bus truck
helicopter knight sword armor king queen throne viking pirate gold diamond skeleton
""".split())

# Footage themes per category: always related to the question's subject area.
CATEGORY_THEMES = {
    "general knowledge": ["library books", "globe", "old books", "classroom", "lightbulb idea"],
    "science & nature": ["science laboratory", "chemistry experiment", "microscope", "scientist", "stars space", "nature"],
    "geography": ["world map", "globe", "travel landscape", "aerial city", "airplane window"],
    "history": ["ancient ruins", "old castle", "museum", "statue", "old map"],
    "sports": ["sports stadium", "running", "soccer ball", "basketball", "crowd cheering"],
    "animals": ["wildlife", "safari animals", "forest animals", "birds", "ocean animals"],
    "entertainment: music": ["concert lights", "guitar", "piano", "music studio", "dj headphones"],
    "entertainment: film": ["film set", "cinema", "movie theater", "hollywood", "movie popcorn", "film director"],
    "entertainment: television": ["television", "watching tv", "tv studio", "remote control", "living room tv"],
    "entertainment: video games": ["playing video games", "gaming", "gamer", "video game controller", "esports"],
    "entertainment: cartoon & animations": ["cartoon", "animation drawing", "colorful animation", "drawing sketch"],
    "entertainment: books": ["library books", "reading book", "bookshelf", "old books"],
    "entertainment: musicals & theatres": ["theater stage", "stage lights", "theater curtain", "audience applause"],
    "entertainment: board games": ["board game", "chess", "playing cards", "dice"],
    "science: computers": ["computer code", "technology", "server room", "typing keyboard"],
    "science: mathematics": ["mathematics", "chalkboard equations", "numbers", "calculator"],
    "science: gadgets": ["gadgets", "technology", "smartphone", "electronics"],
    "mythology": ["ancient temple", "greek statue", "ancient ruins", "old marble"],
    "politics": ["government building", "flags", "capitol building", "voting"],
    "art": ["art gallery", "painting", "artist painting", "sculpture"],
    "celebrities": ["red carpet", "paparazzi flash", "city lights", "limousine"],
    "vehicles": ["cars driving", "highway traffic", "sports car", "motorcycle"],
    "entertainment: comics": ["comic books", "colorful comics", "drawing sketch", "superhero city"],
    "entertainment: japanese anime & manga": ["japan city night", "tokyo street", "cherry blossom", "drawing sketch"],
}
PROPER_OK = {"geography", "history", "sports", "general knowledge"}


def category_themes(category: str) -> list:
    c = (category or "").lower().strip()
    themes = list(CATEGORY_THEMES.get(c, [category_query(category)] if category else ["nature"]))
    random.shuffle(themes)
    return themes


def _concrete_base(word: str):
    """Return the concrete noun for a word, handling plurals safely (animals -> animal, never corner -> corn)."""
    forms = [word]
    if word.endswith("ies") and len(word) > 4:
        forms.append(word[:-3] + "y")
    elif word.endswith("es") and len(word) > 4:
        forms.append(word[:-2])
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        forms.append(word[:-1])
    return next((f for f in forms if f in CONCRETE), None)


GENERIC = {"famous", "country", "called", "known", "first", "largest", "biggest", "smallest", "between",
           "following", "would", "could", "often", "year", "years", "name", "named", "term", "most", "common",
           "commonly", "type", "kind", "original", "originally", "number", "capital", "city", "which", "wrote",
           "written", "invented", "discovered", "created", "found", "form", "part", "main", "major", "used",
           "people", "person", "world", "ever", "after", "before", "during", "since", "other", "another",
           "something", "really", "known", "popular", "current", "currently", "average", "typically", "usually"}


# Categories whose answers are real things you can film (a country, an animal, an element ...).
# For film/TV/music/people questions the answer is a name nobody has footage of, so we show the matching
# *setting* instead (film set, concert, gaming ...) via the category themes.
THING_CATS = {"geography", "animals", "science & nature", "sports", "general knowledge", "vehicles", "art"}


def subject_queries(question: str, correct: str, category: str = "") -> list:
    """The answer itself when it is something that can be filmed (a country, an animal, an element ...)."""
    return []  # footage is chosen from the question and category only, never from the answer
    if (category or "").lower().strip() not in THING_CATS:
        return []
    ans = re.sub(r"\s+", " ", (correct or "").strip())
    if (not ans or re.fullmatch(r"[\d.,\-%/ ]+", ans) or ans.lower() in ("true", "false")
            or len(ans.split()) > 3 or len(ans) > 28):
        return []
    return [ans]


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
        base = None if cat.startswith("entertainment") else _concrete_base(lw)
        if base and base not in queries:
            queries.append(base)
        elif (w[0].isupper() and i > 0 and lw not in STOP and lw not in EXTRA_STOP and len(lw) >= 4):
            caps.append(w[:-2] if w.lower().endswith("'s") else w)
    if cat in PROPER_OK:
        if len(caps) >= 2:
            queries.append(" ".join(caps[:2]))
        queries += caps[:2]
    queries = subject_queries(question, correct, category) + queries[:4] + category_themes(category) + ["abstract colorful background"]
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


# Every Open Trivia DB category the user can pick (id -> label shown on the page).
CATEGORY_LABELS = {
    9: "General Knowledge", 17: "Science & Nature", 22: "Geography", 23: "History", 21: "Sports",
    27: "Animals", 12: "Music", 11: "Film", 14: "Television", 15: "Video Games", 32: "Cartoons & Animation",
    10: "Books", 13: "Musicals & Theatre", 16: "Board Games", 18: "Computers", 19: "Mathematics",
    20: "Mythology", 24: "Politics", 25: "Art", 26: "Celebrities", 28: "Vehicles", 29: "Comics",
    30: "Gadgets", 31: "Anime & Manga",
}


def _fetch_category(cid: int, amount: int = 20):
    """Easy questions for one category. Small categories (Mythology, Art...) have fewer than `amount` easy
    questions and Open Trivia DB then returns nothing at all, so ask for less, then allow any difficulty."""
    base = f"https://opentdb.com/api.php?category={cid}&type=multiple&encode=url3986"
    attempts = [(amount, "easy"), (10, "easy"), (5, "easy"), (amount, None), (10, None), (5, None)]
    seen = set()
    for amt, diff in attempts:
        if (amt, diff) in seen:
            continue
        seen.add((amt, diff))
        url = f"{base}&amount={amt}" + (f"&difficulty={diff}" if diff else "")
        for _ in range(3):
            try:
                r = requests.get(url, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("response_code") == 0:
                        if diff is None:
                            print(f"[questions] category {cid}: too few easy questions, mixed in other difficulties",
                                  flush=True)
                        return data["results"]
                    if data.get("response_code") in (1, 2):  # not enough questions: try a smaller ask
                        break
            except requests.RequestException:
                pass
            time.sleep(6)  # Open Trivia DB allows one request per 5 seconds
        else:
            continue
        time.sleep(5.5)
    return []


def _from_opentdb(categories=None, avoid=()) -> list:
    """Questions from the chosen categories (empty/None = a mix of all of them)."""
    u = urllib.parse.unquote
    ids = [c for c in (categories or []) if c in CATEGORY_LABELS] or list(CATEGORY_LABELS)
    picked = random.sample(ids, min(3, len(ids)))
    amount = {1: 50, 2: 30}.get(len(picked), 20)
    out = []
    for n, cid in enumerate(picked):
        if n:
            time.sleep(5.5)
        for item in _fetch_category(cid, amount):
            q, correct = u(item["question"]), u(item["correct_answer"])
            wrong = [u(x) for x in item["incorrect_answers"]]
            cat = u(item["category"])
            if not _usable(q, correct, wrong):
                continue
            out.append({"question": q, "correct": correct, "wrong": wrong, "category": cat, "_cid": cid,
                        "video_queries": keywords_from(q, correct, cat)})
    if not out:
        raise RuntimeError("Could not fetch questions from Open Trivia DB. Try again in a few seconds.")
    return out


def _from_claude(n: int, avoid: list, categories=None) -> list:
    avoid_text = "\n".join(f"- {a}" for a in avoid) or "(none)"
    chosen = [CATEGORY_LABELS[c] for c in (categories or []) if c in CATEGORY_LABELS]
    topics = ("Use ONLY these topics: " + ", ".join(chosen) + ".") if chosen else \
        "Mix topics: science, history, geography, pop culture, animals, food, sports, space, etc."
    prompt = f"""Create {n + 4} diverse, fun trivia questions for a short TikTok quiz video.

Rules:
- {topics}
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


def _interleave(items: list) -> list:
    """Shuffle, then take one question from each category in turn so every chosen category is represented."""
    groups = {}
    for q in items:
        groups.setdefault(q.get("_cid", q.get("category")), []).append(q)
    lists = list(groups.values())
    for g in lists:
        random.shuffle(g)
    random.shuffle(lists)
    out = []
    while any(lists):
        for g in lists:
            if g:
                out.append(g.pop())
    return out


def get_questions(n: int, categories=None) -> list:
    history = _load_history()
    if is_mock():
        pool = _mock_pool()
    else:
        source = (env("QUESTION_SOURCE") or ("claude" if env("ANTHROPIC_API_KEY") else "opentdb")).lower()
        pool = None
        if source == "claude":
            try:
                pool = _from_claude(n, list(history.values())[-40:], categories)
            except Exception as e:
                print(f"[questions] Claude failed ({e}); falling back to Open Trivia DB")
        if not pool:
            pool = _from_opentdb(categories)
    fresh = [q for q in pool if _qid(q["question"]) not in history]
    stale = [q for q in pool if _qid(q["question"]) in history]
    picked = (_interleave(fresh) + _interleave(stale))[:n]
    random.shuffle(picked)  # the categories are mixed in order too, not grouped
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
