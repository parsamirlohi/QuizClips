"""Writes the script for the non-trivia video formats from a topic.

Formats (the `kind` value):
  personality  "Which Disney character are you?"  questions whose choices each point to one result
  wyr          Would you rather: two options per round, a countdown, then a reveal of what each pick says
  toplist      Top N list counted down from N to 1, each item with a short line
  facts        "Did you know" facts, each with a short headline and one sentence

Gemini (free tier) does the writing. MOCK=1 returns fixed offline content so the whole pipeline can be tested.
"""
import json
import random

import gemini
from config import env, flog, is_mock

KINDS = {
    "personality": {"title": "Personality quiz", "noun": "questions", "min": 3, "max": 8, "default": 5,
                    "hint": "Which Hogwarts house are you?"},
    "wyr": {"title": "Would you rather", "noun": "rounds", "min": 3, "max": 10, "default": 5,
            "hint": "Superpowers and food"},
    "toplist": {"title": "Top list", "noun": "items", "min": 3, "max": 10, "default": 5,
                "hint": "Fastest animals"},
    "facts": {"title": "Did you know", "noun": "facts", "min": 3, "max": 10, "default": 5,
              "hint": "The ocean"},
}
EXAMPLES = {
    "personality": ["Which Hogwarts house are you?", "What kind of pizza are you?", "Which season matches you?",
                    "Which superhero are you?", "What is your spirit animal?", "Which planet are you?",
                    "What kind of coffee are you?", "Which villain are you?", "What is your ideal vacation?",
                    "Which cartoon sidekick are you?", "What kind of weather are you?", "Which fantasy creature are you?",
                    "What type of dessert are you?", "Which decade matches your style?"],
    "wyr": ["Superpowers", "Food and snacks", "Vacations", "School life", "Animals", "Money and fame", "Video games",
            "Space travel", "Living inside a movie", "Weird talents", "Time travel", "Sleepovers"],
    "toplist": ["Fastest animals", "Tallest buildings in the world", "Most visited countries", "Biggest dinosaurs",
                "Best-selling video games", "Strangest foods", "Longest rivers", "Deadliest animals",
                "Inventions that changed the world", "Highest mountains", "Largest cities", "Coolest sports cars"],
    "facts": ["The ocean", "Space", "The human body", "Ancient Egypt", "Dinosaurs", "Cats and dogs", "Food", "Volcanoes",
              "The weather", "Sleep and dreams", "The Olympics", "Robots"],
}

SEARCH_RULES = (
    "For every item give \"search\": 3 short stock-footage search terms (1-3 words each) naming concrete things a camera "
    "can film, most specific first. Never use brand, franchise, character or real people's names; describe what it looks "
    "like instead (for example 'lion cub' or 'castle at night')."
)


def _ask(prompt: str) -> dict:
    if not gemini.available():
        raise RuntimeError("These formats need a Gemini key. Add GEMINI_API_KEY to the .env file (free at aistudio.google.com).")
    last = None
    for attempt in range(2):
        try:
            text = gemini.generate([{"text": prompt}], timeout=60)
            data = json.loads(text[text.index("{"): text.rindex("}") + 1])
            if isinstance(data, dict):
                return data
        except gemini.RateLimited:
            raise
        except Exception as e:
            last = e
            flog(f"[content] attempt {attempt + 1} failed ({str(e)[:100]})")
    raise RuntimeError(f"Could not write the script just now ({str(last)[:80]}). Please try again in a minute.")


def _s(v, limit: int) -> str:
    s = " ".join(str(v or "").split())
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0].rstrip(",;:- ")
    return s


def _search(item, fallback: str) -> list:
    raw = item.get("search") if isinstance(item, dict) else None
    terms = [_s(t, 40) for t in (raw if isinstance(raw, list) else []) if _s(t, 40)]
    return terms[:3] or [fallback]


def _need(cond, msg="the script came back incomplete"):
    if not cond:
        raise RuntimeError(f"Could not write the script just now ({msg}). Please try again.")


PEOPLE_RULE = (
    "When a question or option is about the viewer's own habits, feelings, personality, social life, choices or "
    "preferences (for example 'What is your social style?' or 'How do you spend a free weekend?'), film the real human "
    "situation it describes: 'friends laughing', 'group of friends', 'people at a party', 'person reading a book', "
    "'city commute', 'cooking dinner'. Never use an animal, object or symbol as a metaphor for a trait (no peacock for "
    "confidence, no butterfly for being social, no owl for being wise) unless the quiz theme itself is about that animal."
)


# ---------------------------------------------------------------- personality
def _personality(topic: str, n: int) -> dict:
    p = (
        f"Write a fun personality quiz for a short vertical video. Topic: \"{topic}\".\n"
        f"Return ONLY a JSON object: {{\"title\": ..., \"questions\": [...], \"results\": [...]}}\n"
        f"- title: the quiz title as a question, max 7 words (for example 'Which season are you?').\n"
        f"- questions: exactly {n} items {{\"q\": ..., \"options\": [4 strings], \"search\": [...]}}. q is max 70 characters. Each option is "
        "max 28 characters, vivid and fun. Option 1 always leads to result 1, option 2 to result 2, option 3 to result 3, "
        "option 4 to result 4, so the four options of a question must reflect the four different results.\n"
        "- results: exactly 4 items {\"name\": ..., \"description\": ..., \"search\": [...]}. name max 4 words. "
        "description is 1-2 upbeat sentences, max 140 characters, written as 'You are ...' or 'You're ...'.\n"
        f"Footage rules (very important): the quiz theme is \"{topic}\". The footage for every question AND every result "
        "must show something from the world of that theme, shaped by what that specific question or result is about. "
        "Example: for the theme 'Which Hogwarts house are you?', a question about a pet gets search terms like 'harry potter owl' "
        "then 'snowy owl'; a question about a favorite place gets 'wizard castle' then 'candlelit library'; a result for a "
        "brave house gets 'lion' or 'torch fire'. Every question and every result has a \"search\" list of 3 short "
        "stock-footage search terms (1-3 words each) naming concrete things a camera can film, most specific first: the "
        "first term may combine the theme's franchise or world with the subject if stock sites would likely have it, the "
        "rest are plainer filmable terms. Never use the names of real people or fictional characters.\n"
        f"{PEOPLE_RULE}\n"
        "Keep everything family friendly."
    )
    d = _ask(p)
    qs, rs = d.get("questions"), d.get("results")
    _need(isinstance(qs, list) and isinstance(rs, list) and len(rs) >= 4)
    results = [{"name": _s(r.get("name"), 36), "description": _s(r.get("description"), 160),
                "search": _search(r, _s(r.get("name"), 36))} for r in rs[:4]]
    questions = []
    for q in qs[:n]:
        opts = [_s(o, 30) for o in (q.get("options") or [])][:4]
        if len(opts) == 4 and all(opts) and _s(q.get("q"), 80):
            questions.append({"q": _s(q.get("q"), 80), "options": opts, "search": _search(q, topic)})
    _need(len(questions) >= 3 and all(r["name"] and r["description"] for r in results))
    return {"title": _s(d.get("title"), 60) or topic, "questions": questions, "results": results}


# ---------------------------------------------------------------- would you rather
def _wyr(topic: str, n: int) -> dict:
    p = (
        f"Write {n} 'Would you rather' rounds for a short vertical video. Topic: \"{topic}\".\n"
        "Return ONLY a JSON object: {\"title\": ..., \"rounds\": [...]}\n"
        "- title: max 6 words.\n"
        "- rounds: each {\"a\": ..., \"b\": ..., \"trait_a\": ..., \"trait_b\": ..., \"search_a\": [...], \"search_b\": [...]}.\n"
        "  a and b are the two options, each max 40 characters, written so that 'Would you rather' + a reads naturally "
        "(start with a verb such as 'Be able to fly'). Make both options tempting and about equally hard to choose.\n"
        "  trait_a and trait_b say what choosing that option says about you: 2-4 words starting with 'a' or 'an', "
        "max 26 characters, playful and flattering (for example 'a bold adventurer').\n"
        "  search_a and search_b: 3 short stock-footage search terms each (1-3 words), concrete things a camera can film, "
        "most specific first, no brand, franchise or real people's names. Film the situation the option describes "
        "(the place, activity or scene), not a symbol for it.\n"
        "Keep everything family friendly."
    )
    d = _ask(p)
    rounds = []
    for r in (d.get("rounds") or [])[:n]:
        a, b = _s(r.get("a"), 46), _s(r.get("b"), 46)
        if a and b:
            rounds.append({"a": a, "b": b, "trait_a": _s(r.get("trait_a"), 30) or "a bold pick",
                           "trait_b": _s(r.get("trait_b"), 30) or "a smart pick",
                           "search_a": _search({"search": r.get("search_a")}, a),
                           "search_b": _search({"search": r.get("search_b")}, b)})
    _need(len(rounds) >= 3)
    return {"title": _s(d.get("title"), 50) or "Would you rather", "rounds": rounds}


# ---------------------------------------------------------------- top list / facts
def _items(kind: str, topic: str, n: int) -> dict:
    if kind == "toplist":
        p = (
            f"Write a 'Top {n}' countdown list for a short vertical video. Topic: \"{topic}\".\n"
            "Return ONLY a JSON object: {\"title\": ..., \"items\": [...]}\n"
            f"- title: starts with 'Top {n}', max 7 words.\n"
            f"- items: exactly {n} entries ordered from number {n} down to number 1 (the best or most impressive last). "
            "Each is {\"name\": ..., \"line\": ..., \"search\": [...]}. name max 4 words. line is one short, surprising "
            "sentence with a real, accurate detail, max 110 characters.\n"
            f"{SEARCH_RULES}\nOnly include facts you are confident are true."
        )
    else:
        p = (
            f"Write {n} surprising 'Did you know' facts for a short vertical video. Topic: \"{topic}\".\n"
            "Return ONLY a JSON object: {\"title\": ..., \"items\": [...]}\n"
            "- title: max 7 words, for example 'Wild facts about the ocean'.\n"
            f"- items: exactly {n} entries, each {{\"name\": ..., \"line\": ..., \"search\": [...]}}. name is a punchy "
            "headline of max 5 words. line is one clear sentence stating the fact with a specific detail, max 130 "
            f"characters.\n{SEARCH_RULES}\nOnly include facts you are confident are true and widely documented."
        )
    d = _ask(p)
    items = []
    for it in (d.get("items") or [])[:n]:
        name, line = _s(it.get("name"), 40), _s(it.get("line"), 150)
        if name and line:
            items.append({"name": name, "line": line, "search": _search(it, name)})
    _need(len(items) >= 3)
    default = f"Top {len(items)} {topic}" if kind == "toplist" else f"Did you know? {topic}"
    return {"title": _s(d.get("title"), 60) or default, "items": items}


# ---------------------------------------------------------------- offline mock
def _mock(kind: str, topic: str, n: int) -> dict:
    t = topic or "Mock topic"
    if kind == "personality":
        names = ["The Dreamer", "The Explorer", "The Leader", "The Artist"]
        return {"title": f"Which {t} are you?",
                "questions": [{"q": f"Mock question {i + 1}: what do you pick?",
                               "options": ["Stay home", "Go outside", "Take charge", "Make something"],
                               "search": ["clouds", "mountains"]} for i in range(n)],
                "results": [{"name": nm, "description": f"You're {nm.lower()}, full of surprising energy and good ideas.",
                             "search": ["abstract", "lights"]} for nm in names]}
    if kind == "wyr":
        return {"title": t, "rounds": [{"a": f"Fly like a bird {i + 1}", "b": "Swim like a fish",
                                        "trait_a": "a free spirit", "trait_b": "a calm thinker",
                                        "search_a": ["sky"], "search_b": ["ocean"]} for i in range(n)]}
    items = [{"name": f"Item {i + 1}", "line": f"A short mock line about item {i + 1} of the list.", "search": ["abstract"]}
             for i in range(n)]
    return {"title": f"Top {n} {t}" if kind == "toplist" else f"Did you know? {t}", "items": items}


AREAS = [
    "deep sea creatures", "space and planets", "street food around the world", "90s cartoons", "medieval castles",
    "dinosaurs", "board games", "video game worlds", "ancient Egypt", "volcanoes and earthquakes", "pizza and pasta",
    "superhero powers", "pirates", "the Olympics", "Halloween", "rainforests", "robots and AI", "famous bridges",
    "coffee and tea", "summer road trips", "hip hop history", "fairy tales", "desert survival", "the human brain",
    "tiny houses", "magic and wizards", "roller coasters", "ice cream flavors", "mythical creatures", "extreme weather",
    "cats and dogs", "school life", "the Wild West", "mountain climbing", "candy", "zombie apocalypse", "winter holidays",
    "ocean islands", "inventions that changed the world", "birds", "movie villains", "theme parks", "camping", "the 80s",
    "fashion through history", "snacks", "world capitals", "spy gadgets", "farm animals", "the moon", "sneakers",
    "festivals around the world", "bugs and insects", "musical instruments", "sleepovers", "treasure hunts", "airplanes",
    "cooking disasters", "sharks", "ancient Rome", "time travel", "tiny animals", "sports legends", "cartoon sidekicks",
    "arctic life", "breakfast foods", "haunted places", "fantasy kingdoms", "social media trends", "backyard science",
]
_WHAT = {
    "personality": "a personality quiz whose title is a question like 'Which season are you?' or 'What kind of pizza are you?'",
    "wyr": "a round of 'Would you rather' dilemmas (the topic is the theme of the dilemmas)",
    "toplist": "a Top 5 countdown list (the topic is what gets ranked, like 'Fastest animals')",
    "facts": "a set of 'Did you know' facts (the topic is the subject of the facts)",
}


def random_topic(kind: str) -> str:
    """A fresh topic every time: a random area is picked here, then Gemini invents something specific from it."""
    area = random.choice(AREAS)
    if is_mock() or not gemini.available():
        return area
    p = (f"Invent ONE fresh, fun, specific topic for {_WHAT[kind]}. Take loose inspiration from \"{area}\" but make it "
         "something unexpected, not the first idea that comes to mind. Family friendly. Max 8 words. "
         "Reply with ONLY a JSON object: {\"topic\": \"...\"}")
    try:
        text = gemini.generate([{"text": p}], timeout=30, temperature=1.2)
        t = _s(json.loads(text[text.index("{"): text.rindex("}") + 1]).get("topic"), 80)
        if t:
            flog(f"[content] random topic: {t}")
            return t
    except Exception as e:
        flog(f"[content] random topic fell back to '{area}' ({str(e)[:80]})")
    return area


def generate(kind: str, topic: str, n: int) -> dict:
    if kind not in KINDS:
        raise RuntimeError("Unknown video type.")
    spec = KINDS[kind]
    n = max(spec["min"], min(spec["max"], int(n)))
    topic = _s(topic, 80) or random_topic(kind)
    data = _mock(kind, topic, n) if is_mock() else (
        _personality(topic, n) if kind == "personality" else _wyr(topic, n) if kind == "wyr" else _items(kind, topic, n))
    data["kind"], data["topic"] = kind, topic
    return data
