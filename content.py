"""Writes the script for the non-trivia video formats from a topic.

Formats (the `kind` value):
  personality  "Which Disney character are you?"  questions whose choices each point to one result
  wyr          Would you rather: two options per round, a countdown, then a reveal of what each pick says
  toplist      Top N list counted down from N to 1, each item with a short line
  facts        "Fun facts", each with a short headline and one sentence
  story        you are the hero: decisions with two options each; either both outcomes are shown ("Choose your path")
               or some options are deadly traps ("Would you survive?")
  odd          odd one out: four things, three belong together, viewers spot the one that doesn't
  clip         guess the clip: a pixelated video gets sharper while viewers pick what it shows

Gemini (free tier) does the writing. MOCK=1 returns fixed offline content so the whole pipeline can be tested.
"""
import json
import random

import gemini
from config import env, flog, is_mock

KINDS = {
    "personality": {"title": "Personality quiz", "noun": "questions", "min": 3, "max": 8, "default": 5,
                    "hint": "Which Hogwarts house are you?"},
    "odd": {"title": "Odd one out", "noun": "rounds", "min": 3, "max": 8, "default": 5,
            "hint": "Fruits, animals, countries"},
    "clip": {"title": "Guess the clip", "noun": "rounds", "min": 3, "max": 8, "default": 5,
             "hint": "Zoo animals"},
    "missing": {"title": "What's missing", "noun": "rounds", "min": 3, "max": 8, "default": 5,
                "hint": "Animals, food, travel"},
    "story": {"title": "Story", "noun": "decisions", "min": 3, "max": 8, "default": 5,
              "hint": "Lost in a haunted mansion"},
    "wyr": {"title": "Would you rather", "noun": "rounds", "min": 3, "max": 10, "default": 5,
            "hint": "Superpowers and food"},
    "toplist": {"title": "Rankings", "noun": "items", "min": 3, "max": 10, "default": 5,
                "hint": "Fastest animals"},
    "facts": {"title": "Fun facts", "noun": "facts", "min": 3, "max": 10, "default": 5,
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
    "odd": ["Fruits and snacks", "Animals", "Countries and cities", "Things in a kitchen", "Sports and games",
            "Space", "Things with wheels", "Musical instruments", "Ocean life", "Things in a school bag"],
    "clip": ["Zoo animals", "Famous landmarks", "Things in the kitchen", "Sports", "Ocean life", "Vehicles",
             "Weather", "Farm animals", "Things you find at the beach", "Musical instruments"],
    "missing": ["Animals", "Food and snacks", "Things and sports", "Travel and nature", "A bit of everything"],
    "story": ["Lost in a haunted mansion", "Stranded on a desert island", "Zombie apocalypse", "Escaping a pirate ship",
              "Trapped in a video game", "A night in the jungle", "Surviving a space station", "Lost in a snowstorm",
              "Exploring an ancient tomb", "A haunted school trip"],
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




# ---------------------------------------------------------------- odd one out / guess the clip
def _odd(topic: str, n: int) -> dict:
    p = (
        f"Write {n} 'odd one out' puzzles for a short vertical video. Theme: \"{topic}\".\n"
        "Return ONLY a JSON object: {\"title\": ..., \"rounds\": [...]}\n"
        "- title: max 6 words.\n"
        "- rounds: each {\"items\": [4 strings], \"odd\": 0-3, \"reason\": ..., \"search\": [...]}. Three items clearly belong "
        "to the same group and one does not. items are 1-3 words each, max 22 characters, easy to picture. odd is the index "
        "(0-3) of the one that does not belong; vary which position it is. Make it fun and fair: a clear, single answer "
        "(for example apple, banana, grape and hammer). reason is one short sentence saying why, max 70 characters, "
        "for example 'The others are fruit, a hammer is a tool.'\n"
        "  search: 3 short stock-footage search terms (1-3 words each) showing the group the three belong to, or the "
        "setting, concrete and filmable, no brand or real people's names.\n"
        "Keep everything family friendly."
    )
    d = _ask(p)
    rounds = []
    for r in (d.get("rounds") or [])[:n]:
        items = [_s(x, 24) for x in (r.get("items") or [])][:4]
        odd = r.get("odd")
        if len(items) == 4 and all(items) and len({x.lower() for x in items}) == 4 and isinstance(odd, int) and 0 <= odd < 4 \
                and _s(r.get("reason"), 80):
            rounds.append({"items": items, "odd": odd, "reason": _s(r.get("reason"), 80), "search": _search(r, topic)})
    _need(len(rounds) >= 3)
    return {"title": _s(d.get("title"), 50) or "Odd one out", "rounds": rounds}


def _clip(topic: str, n: int) -> dict:
    p = (
        f"Write {n} rounds of a 'guess what this video shows' game for a short vertical video. Theme: \"{topic}\".\n"
        "Return ONLY a JSON object: {\"title\": ..., \"rounds\": [...]}\n"
        "- title: max 6 words, about the theme only; it must NEVER name or hint at any answer.\n"
        "- rounds: each {\"answer\": ..., \"wrong\": [3 strings], \"search\": [...]}. The answer is one clearly recognizable "
        "thing a camera can film (a noun phrase starting with 'a', 'an' or 'the' where natural, for example 'a lion'), max 22 "
        "characters. wrong has 3 believable but different things from the same theme, max 22 characters each, so the "
        "choices are hard to tell apart when the picture is blurry. search: 3 short stock-footage search terms (1-3 words "
        "each) that find that exact thing, most specific first, no brand or real people's names.\n"
        "Keep everything family friendly."
    )
    d = _ask(p)
    rounds = []
    for r in (d.get("rounds") or [])[:n]:
        ans = _s(r.get("answer"), 24)
        wrong = [_s(x, 24) for x in (r.get("wrong") or [])][:3]
        if ans and len(wrong) == 3 and all(wrong) and len({x.lower() for x in wrong + [ans]}) == 4:
            opts = wrong[:]
            idx = random.randrange(4)
            opts.insert(idx, ans)
            rounds.append({"answer": ans, "options": opts, "correct_idx": idx, "search": _search(r, ans)})
    _need(len(rounds) >= 3)
    return {"title": "Can you guess the clip?", "rounds": rounds}   # fixed: a model-written title can give an answer away


# ---------------------------------------------------------------- story
MODES = ("path", "survive")


def trap_plan(n: int) -> dict:
    """Which decisions are deadly in 'Would you survive?': {step index: 'a' or 'b'}. Never the first decision."""
    k = 1 if n < 5 else 2 if n < 8 else 3
    return {i: random.choice("ab") for i in random.sample(range(1, n), min(k, n - 1))}


def _story(topic: str, n: int, mode: str) -> dict:
    traps = trap_plan(n) if mode == "survive" else {}
    if mode == "survive":
        rule = ("This is a survival game: the viewer is eliminated if they pick a deadly option. These decisions have a "
                "deadly option (the others have none, so both options there are survivable, either one works):\n" +
                "\n".join(f"  decision {i + 1}: option {side.upper()} is a deadly trap" for i, side in sorted(traps.items())) +
                "\nA deadly option must look tempting, and its outcome says clearly how the hero's run ends (family friendly, "
                "for example 'The floor gives way. Game over.'). Every other outcome says how the hero gets through, with a small twist.")
    else:
        rule = ("Both options of every decision are fine and lead to different, surprising outcomes. Nothing is a wrong "
                "answer; each outcome is a fun consequence that makes people want to try the other path.")
    p = (
        f"Write an interactive story for a short vertical video. Theme: \"{topic}\". The viewer is the hero and makes {n} "
        "decisions in a row.\n"
        "Return ONLY a JSON object: {\"title\": ..., \"steps\": [...]}\n"
        "- title: max 7 words" + (", a question like 'Would you survive the haunted mansion?'.\n" if mode == "survive" else ".\n") +
        f"- steps: exactly {n} items {{\"situation\": ..., \"a\": ..., \"b\": ..., \"out_a\": ..., \"out_b\": ..., "
        "\"search\": [...], \"search_out\": [...]}. The steps follow one story, in order, getting more tense.\n"
        "  situation: what the hero faces, present tense, max 60 characters (for example 'You hear scratching behind the wall').\n"
        "  a and b: the two choices, max 32 characters, each starting with a verb, both tempting.\n"
        "  out_a and out_b: what happens if the hero picks that choice, one short sentence, max 70 characters, starting with 'You'.\n"
        f"  {rule}\n"
        "  search: 3 short stock-footage search terms (1-3 words each) for the situation; search_out: 3 terms for what "
        "happens in the outcome (for a deadly option, the danger; otherwise the first option's outcome). Concrete filmable "
        "things, most specific first, no brand, franchise or real people's names.\n"
        "Keep everything family friendly."
    )
    d = _ask(p)
    steps = []
    for i, r in enumerate((d.get("steps") or [])[:n]):
        sit, a, b = _s(r.get("situation"), 70), _s(r.get("a"), 38), _s(r.get("b"), 38)
        oa, ob = _s(r.get("out_a"), 80), _s(r.get("out_b"), 80)
        if sit and a and b and oa and ob:
            steps.append({"situation": sit, "a": a, "b": b, "out_a": oa, "out_b": ob, "trap": traps.get(i, ""),
                          "search": _search(r, sit), "search_out": _search({"search": r.get("search_out")}, sit)})
    _need(len(steps) >= 3)
    if mode == "survive":   # the script may have come back shorter than asked: keep at least one trap, never first
        if not any(s["trap"] for s in steps):
            steps[random.randrange(1, len(steps))]["trap"] = random.choice("ab")
    return {"title": _s(d.get("title"), 60) or topic, "steps": steps}


# ---------------------------------------------------------------- rankings / facts
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
    default = f"Top {len(items)} {topic}" if kind == "toplist" else f"Fun facts: {topic}"
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
    if kind == "odd":
        return {"title": t, "rounds": [{"items": ["Apple", "Banana", "Grape", "Hammer"], "odd": 3,
                                        "reason": "The others are fruit, a hammer is a tool.", "search": ["fruit"]} for i in range(n)]}
    if kind == "clip":
        return {"title": t, "rounds": [{"answer": "A lion", "options": ["A tiger", "A lion", "A bear", "A wolf"], "correct_idx": 1,
                                        "search": ["lion"]} for i in range(n)]}
    if kind == "story":
        traps = trap_plan(n)
        return {"title": f"Would you survive {t}?", "steps": [
            {"situation": f"Mock situation {i + 1}: something happens", "a": "Run away", "b": "Hide and wait",
             "out_a": "The floor gives way. Game over." if traps.get(i) == "a" else "You sprint off and find a safe path.",
             "out_b": "The floor gives way. Game over." if traps.get(i) == "b" else "You wait it out and stay unseen.",
             "trap": traps.get(i, ""), "search": ["forest"], "search_out": ["night"]} for i in range(n)]}
    items = [{"name": f"Item {i + 1}", "line": f"A short mock line about item {i + 1} of the list.", "search": ["abstract"]}
             for i in range(n)]
    return {"title": f"Top {n} {t}" if kind == "toplist" else f"Fun facts: {t}", "items": items}


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
    "odd": "a set of 'odd one out' puzzles (the topic is the theme of the groups)",
    "clip": "a 'guess what the video shows' game (the topic is what kinds of things appear)",
    "missing": "a memory game (the topic picks the pictures: animals, food, things, travel)",
    "story": "an adventure where the viewer makes decisions, like 'Lost in a haunted mansion' or 'Stranded on a desert island'",
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


def generate(kind: str, topic: str, n: int, mode: str = "path") -> dict:
    if kind not in KINDS:
        raise RuntimeError("Unknown video type.")
    spec = KINDS[kind]
    n = max(spec["min"], min(spec["max"], int(n)))
    topic = _s(topic, 80)
    if topic:
        import safety
        safety.check(topic, "topic")   # the endpoint already ran the full check (rules + AI review); this keeps other callers safe
    topic = topic or ("" if kind == "missing" else random_topic(kind))
    mode = mode if mode in MODES else "path"
    if kind == "missing":   # no AI needed: the pictures come from our own set (emojis.py)
        import emojis
        return {"title": "What's missing?", "rounds": [emojis.make_round(topic) for _ in range(n)], "kind": kind,
                "topic": topic, "mode": "path"}
    import safety
    for attempt in range(2):   # what the AI wrote goes through the safety rules; if it slipped, write it once more
        data = _mock(kind, topic, n) if is_mock() else (
            _personality(topic, n) if kind == "personality" else _wyr(topic, n) if kind == "wyr"
            else _story(topic, n, mode) if kind == "story" else _odd(topic, n) if kind == "odd"
            else _clip(topic, n) if kind == "clip" else _items(kind, topic, n))
        try:
            safety.check_output(data)
            break
        except safety.Blocked as e:
            flog(f"[content] generated script rejected ({e.category}), attempt {attempt + 1}")
            if attempt:
                raise RuntimeError("We couldn't write a script for that topic that fits our family friendly rules. "
                                   "Please try a different topic.")
    data["kind"], data["topic"], data["mode"] = kind, topic, mode
    return data


# ---------------------------------------------------------------- the person's own content ("I'll write it")
def _text(v, limit: int, what: str, required: bool = True) -> str:
    s = " ".join(str(v or "").split())
    if not s:
        if required:
            raise ValueError(f"{what} is empty.")
        return ""
    if len(s) > limit:
        raise ValueError(f"{what} is too long (most is {limit} characters).")
    import safety
    try:
        safety.check(s, "custom")   # the rules for every field, right away; the AI review runs once on all of it (clean_custom)
    except safety.Blocked as e:
        raise ValueError(f"{what}: {e}")
    return s


def _rows(v, lo: int, hi: int, what: str) -> list:
    if not isinstance(v, list) or len(v) < lo:
        raise ValueError(f"Add at least {lo} {what}.")
    if len(v) > hi:
        raise ValueError(f"Most is {hi} {what}.")
    return v


def clean_custom(kind: str, c, mode: str = "path") -> object:
    """Check what the person typed. Trivia returns a list of questions, every other type returns the same kind of
    dict the script writer makes (minus the footage searches). Raises ValueError with a message for the person."""
    if not isinstance(c, dict):
        raise ValueError("Nothing to build from yet.")
    if kind == "trivia":
        out = []
        for i, q in enumerate(_rows(c.get("questions"), 1, 10, "questions"), 1):
            q = q if isinstance(q, dict) else {}
            text = _text(q.get("question"), 220, f"Question {i}")
            raw = q.get("choices")
            choices = [_text(x, 90, f"Question {i}, an answer") for x in (raw if isinstance(raw, list) else [])]
            if not 2 <= len(choices) <= 4:
                raise ValueError(f"Question {i} needs 2 to 4 answers.")
            if len({x.lower() for x in choices}) != len(choices):
                raise ValueError(f"Question {i} has two answers that are the same.")
            idx = q.get("correct_idx")
            if not isinstance(idx, int) or not 0 <= idx < len(choices):
                raise ValueError(f"Question {i}: pick which answer is right.")
            out.append({"question": text, "choices": choices, "correct_idx": idx})
        return out
    if kind == "wyr":
        rounds = []
        for i, r in enumerate(_rows(c.get("rounds"), 3, 10, "rounds"), 1):
            r = r if isinstance(r, dict) else {}
            rounds.append({"a": _text(r.get("a"), 46, f"Round {i}, option A"), "b": _text(r.get("b"), 46, f"Round {i}, option B"),
                           "trait_a": _text(r.get("trait_a"), 30, f"Round {i}, what A says", False) or "a bold pick",
                           "trait_b": _text(r.get("trait_b"), 30, f"Round {i}, what B says", False) or "a smart pick"})
        return {"title": _text(c.get("title"), 50, "The title", False) or "Would you rather", "rounds": rounds}
    if kind == "story":
        steps = []
        for i, r in enumerate(_rows(c.get("steps"), 3, 8, "decisions"), 1):
            r = r if isinstance(r, dict) else {}
            trap = r.get("trap") if r.get("trap") in ("a", "b") else ""
            steps.append({"situation": _text(r.get("situation"), 70, f"Decision {i}, what happens"),
                          "a": _text(r.get("a"), 38, f"Decision {i}, option A"), "b": _text(r.get("b"), 38, f"Decision {i}, option B"),
                          "out_a": _text(r.get("out_a"), 80, f"Decision {i}, what A leads to"),
                          "out_b": _text(r.get("out_b"), 80, f"Decision {i}, what B leads to"), "trap": trap})
        if mode == "survive" and not any(s["trap"] for s in steps):
            raise ValueError("Mark at least one option as a trap, or switch to Choose your path.")
        if mode == "survive" and steps[0]["trap"]:
            raise ValueError("The first decision can't be a trap, everyone needs a chance to play.")
        return {"title": _text(c.get("title"), 60, "The title", False) or "Your story", "steps": steps}
    if kind in ("toplist", "facts"):
        items = []
        word = "Item" if kind == "toplist" else "Fact"
        for i, it in enumerate(_rows(c.get("items"), 3, 10, "items" if kind == "toplist" else "facts"), 1):
            it = it if isinstance(it, dict) else {}
            items.append({"name": _text(it.get("name"), 40, f"{word} {i}, the name" if kind == "toplist" else f"{word} {i}, the headline"),
                          "line": _text(it.get("line"), 150, f"{word} {i}, the sentence")})
        default = f"Top {len(items)} list" if kind == "toplist" else "Fun facts"
        return {"title": _text(c.get("title"), 60, "The title", False) or default, "items": items}
    if kind == "personality":
        results = []
        for k, r in enumerate(_rows(c.get("results"), 4, 4, "results"), 1):
            r = r if isinstance(r, dict) else {}
            results.append({"name": _text(r.get("name"), 36, f"Result {k}, the name"),
                            "description": _text(r.get("description"), 160, f"Result {k}, the description")})
        qs = []
        for i, q in enumerate(_rows(c.get("questions"), 3, 8, "questions"), 1):
            q = q if isinstance(q, dict) else {}
            opts = q.get("options") if isinstance(q.get("options"), list) else []
            if len(opts) != 4:
                raise ValueError(f"Question {i} needs 4 answers, one for each result.")
            qs.append({"q": _text(q.get("q"), 80, f"Question {i}"),
                       "options": [_text(o, 30, f"Question {i}, an answer") for o in opts]})
        return {"title": _text(c.get("title"), 60, "The quiz title"), "questions": qs, "results": results}
    if kind == "odd":
        rounds = []
        for i, r in enumerate(_rows(c.get("rounds"), 3, 8, "rounds"), 1):
            r = r if isinstance(r, dict) else {}
            raw = r.get("items") if isinstance(r.get("items"), list) else []
            items = [_text(x, 24, f"Round {i}, an item") for x in raw]
            if len(items) != 4:
                raise ValueError(f"Round {i} needs 4 items.")
            if len({x.lower() for x in items}) != 4:
                raise ValueError(f"Round {i} has two items that are the same.")
            odd = r.get("odd")
            if not isinstance(odd, int) or not 0 <= odd < 4:
                raise ValueError(f"Round {i}: pick which item doesn't belong.")
            reason = _text(r.get("reason"), 80, f"Round {i}, why it doesn't belong", False) or f"{items[odd]} doesn't belong with the others."
            term = _text(r.get("search"), 40, f"Round {i}, the footage search", False)
            rounds.append({"items": items, "odd": odd, "reason": reason, "search": [term] if term else []})
        return {"title": _text(c.get("title"), 50, "The title", False) or "Odd one out", "rounds": rounds}
    if kind == "clip":
        rounds = []
        for i, r in enumerate(_rows(c.get("rounds"), 3, 8, "rounds"), 1):
            r = r if isinstance(r, dict) else {}
            ans = _text(r.get("answer"), 24, f"Round {i}, the answer")
            raw = r.get("wrong") if isinstance(r.get("wrong"), list) else []
            wrong = [_text(x, 24, f"Round {i}, a wrong choice") for x in raw]
            if len(wrong) != 3:
                raise ValueError(f"Round {i} needs 3 wrong choices.")
            if len({x.lower() for x in wrong + [ans]}) != 4:
                raise ValueError(f"Round {i} has two choices that are the same.")
            term = _text(r.get("search"), 40, f"Round {i}, the footage search", False)
            idx = random.randrange(4)
            opts = wrong[:]
            opts.insert(idx, ans)
            rounds.append({"answer": ans, "options": opts, "correct_idx": idx, "search": [term] if term else []})
        # a title the person wrote could give an answer away, so it is always the same
        return {"title": "Can you guess the clip?", "rounds": rounds}
    if kind == "missing":
        import emojis
        known = emojis.all_names()
        rounds = []
        for i, r in enumerate(_rows(c.get("rounds"), 3, 8, "rounds"), 1):
            r = r if isinstance(r, dict) else {}
            grid = r.get("grid") if isinstance(r.get("grid"), list) else []
            if len(grid) != 9 or not all(isinstance(x, str) and x in known for x in grid):
                raise ValueError(f"Round {i} needs 9 pictures.")
            if len(set(grid)) != 9:
                raise ValueError(f"Round {i} uses the same picture twice.")
            hole = r.get("hole")
            if not isinstance(hole, int) or not 0 <= hole < 9:
                raise ValueError(f"Round {i}: pick which picture disappears.")
            rounds.append(emojis.round_from(grid, hole))
        return {"title": "What's missing?", "rounds": rounds}
    raise ValueError("Unknown video type.")


def review_custom(cleaned, ip: str = "") -> None:
    """The AI review of everything the person typed (the rules already ran on each field). Raises ValueError."""
    import safety
    rounds = cleaned.get("rounds") if isinstance(cleaned, dict) else None
    if rounds and isinstance(rounds[0], dict) and "grid" in rounds[0]:
        return   # What's missing: only pictures from our own set, nothing was typed
    try:
        safety.review(safety.strings(cleaned), "custom", ip)
    except safety.Blocked as e:
        raise ValueError(str(e))


def _terms_for(texts: list, theme: str = "") -> list:
    """3 footage searches for each text: written by Gemini when it is available, otherwise plain keywords."""
    from questions import keywords_from
    base = [[w for w in keywords_from(t, "", "")[:3] if w] or [_s(t, 30)] for t in texts]
    if is_mock() or not gemini.available() or not texts:
        return base
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    p = (f"A short vertical video shows these items one at a time{(' (theme: ' + theme + ')') if theme else ''}:\n{numbered}\n"
         f"{SEARCH_RULES}\n{PEOPLE_RULE}\n"
         "Return ONLY a JSON object: {\"terms\": [[3 terms for item 1], [3 terms for item 2], ...]} with exactly "
         f"{len(texts)} lists, in order.")
    try:
        d = _ask(p)
        terms = d.get("terms")
        if isinstance(terms, list) and len(terms) == len(texts):
            out = []
            for t, fallback in zip(terms, base):
                got = [_s(x, 40) for x in (t if isinstance(t, list) else []) if _s(x, 40)][:3]
                out.append(got or fallback)
            return out
    except Exception as e:
        flog(f"[content] search terms for your own content fell back to keywords ({str(e)[:80]})")
    return base


def add_terms(kind: str, data: dict) -> dict:
    """Give the person's own content its footage searches (the script writer does this for generated content)."""
    if kind == "wyr":
        texts = [x for r in data["rounds"] for x in (r["a"], r["b"])]
        t = _terms_for(texts, data["title"])
        for i, r in enumerate(data["rounds"]):
            r["search_a"], r["search_b"] = t[2 * i], t[2 * i + 1]
    elif kind == "story":
        texts = [x for st in data["steps"] for x in (st["situation"], st["out_a"] if st["trap"] != "b" else st["out_b"])]
        t = _terms_for(texts, data["title"])
        for i, st in enumerate(data["steps"]):
            st["search"], st["search_out"] = t[2 * i], t[2 * i + 1]
    elif kind in ("toplist", "facts"):
        t = _terms_for([f'{it["name"]}. {it["line"]}' for it in data["items"]], data["title"])
        for it, s in zip(data["items"], t):
            it["search"] = s
    elif kind == "odd":
        todo = [r for r in data["rounds"] if not r["search"]]
        t = _terms_for([" ".join(x for j, x in enumerate(r["items"]) if j != r["odd"]) for r in todo], data["title"])
        for r, s in zip(todo, t):
            r["search"] = s
    elif kind == "clip":
        todo = [r for r in data["rounds"] if not r["search"]]
        t = _terms_for([r["answer"] for r in todo], "")
        for r, s in zip(todo, t):
            r["search"] = s
    elif kind == "personality":
        texts = [q["q"] for q in data["questions"]] + [f'{r["name"]}. {r["description"]}' for r in data["results"]]
        t = _terms_for(texts, data["title"])
        for q, s in zip(data["questions"], t):
            q["search"] = s
        for r, s in zip(data["results"], t[len(data["questions"]):]):
            r["search"] = s
    return data
