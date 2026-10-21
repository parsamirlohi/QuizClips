"""The little pictures used by the 'What's missing' video (Twemoji graphics, see assets/emoji/LICENSE.txt).

Each entry: file name (the emoji's code) -> display name, grouped by theme.
"""
import random

THEMES = {
    "food": {
        "1f34e": "Apple", "1f34c": "Banana", "1f347": "Grapes", "1f353": "Strawberry", "1f352": "Cherries", "1f351": "Peach",
        "1f34d": "Pineapple", "1f349": "Watermelon", "1f34b": "Lemon", "1f955": "Carrot", "1f33d": "Corn", "1f354": "Burger",
        "1f355": "Pizza", "1f35f": "Fries", "1f32d": "Hot dog", "1f369": "Donut", "1f36a": "Cookie", "1f366": "Ice cream",
        "1f370": "Cake", "1f36b": "Chocolate", "1f37f": "Popcorn", "1f951": "Avocado", "1f344": "Mushroom",
    },
    "animals": {
        "1f436": "Dog", "1f431": "Cat", "1f42d": "Mouse", "1f430": "Rabbit", "1f98a": "Fox", "1f43b": "Bear", "1f43c": "Panda",
        "1f981": "Lion", "1f42f": "Tiger", "1f438": "Frog", "1f435": "Monkey", "1f427": "Penguin", "1f422": "Turtle",
        "1f419": "Octopus", "1f420": "Fish", "1f98b": "Butterfly", "1f41d": "Bee", "1f41e": "Ladybug", "1f984": "Unicorn",
        "1f418": "Elephant", "1f992": "Giraffe", "1f433": "Whale",
    },
    "objects": {
        "26bd": "Soccer ball", "1f3c0": "Basketball", "1f3c8": "Football", "1f3be": "Tennis ball", "1f3b8": "Guitar",
        "1f3b9": "Piano", "1f941": "Drum", "1f3a8": "Paint palette", "1f4da": "Books", "1f511": "Key", "1f4a1": "Light bulb",
        "23f0": "Alarm clock", "1f388": "Balloon", "1f381": "Gift", "1f451": "Crown", "1f3a7": "Headphones", "1f4f7": "Camera",
    },
    "travel": {
        "1f697": "Car", "1f68c": "Bus", "1f680": "Rocket", "1f6b2": "Bicycle", "26f5": "Sailboat", "1f3e0": "House",
        "1f308": "Rainbow", "2b50": "Star", "1f319": "Moon", "1f525": "Fire", "1f335": "Cactus", "1f33b": "Sunflower",
        "1f332": "Tree", "2744": "Snowflake",
    },
}
KEYWORDS = {"food": ("food", "snack", "eat", "fruit", "dessert", "meal", "kitchen"),
            "animals": ("animal", "pet", "zoo", "wild", "bird", "ocean", "farm"),
            "objects": ("object", "thing", "sport", "game", "music", "toy", "school", "play"),
            "travel": ("travel", "vehicle", "transport", "nature", "weather", "city", "space", "trip")}


def pool(topic: str) -> dict:
    """code -> name for the theme the topic points at, or a mix of everything."""
    t = (topic or "").lower()
    for theme, words in KEYWORDS.items():
        if any(w in t for w in words):
            return dict(THEMES[theme])
    return {c: n for group in THEMES.values() for c, n in group.items()}


def make_round(topic: str, size: int = 9) -> dict:
    """{'grid': [codes], 'hole': index of the one that goes missing, 'options': [3 names], 'correct_idx', 'answer'}"""
    names = pool(topic)
    codes = random.sample(list(names), size)
    hole = random.randrange(size)
    gone = codes[hole]
    seen = [c for i, c in enumerate(codes) if i != hole]
    other = random.choice(seen)                                          # was in the picture, still is
    never = random.choice([c for c in names if c not in codes] or [c for c in seen if c != other])   # never was there
    opts = [gone, other, never]
    random.shuffle(opts)
    return {"grid": codes, "hole": hole, "options": [names[c] for c in opts], "correct_idx": opts.index(gone),
            "answer": names[gone]}


def all_names() -> dict:
    """code -> name for every picture there is."""
    return {c: n for group in THEMES.values() for c, n in group.items()}


def round_from(codes: list, hole: int) -> dict:
    """Like make_round, but for pictures the person picked: codes (9 of them) and the index that goes missing. The
    answer choices are the missing one, one that stays on screen and one that was never there."""
    names = all_names()
    gone = codes[hole]
    seen = [c for i, c in enumerate(codes) if i != hole]
    other = random.choice(seen)
    never = random.choice([c for c in names if c not in codes] or [c for c in seen if c != other])
    opts = [gone, other, never]
    random.shuffle(opts)
    return {"grid": list(codes), "hole": hole, "options": [names[c] for c in opts], "correct_idx": opts.index(gone),
            "answer": names[gone]}
