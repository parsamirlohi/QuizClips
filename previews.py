"""Draws the graphics of the Studio phone preview on demand, in the look's colors plus any colors the person picked.

The same samples are used by tools/make_type_previews.py to make the ready-made pictures, so the two always match.
Nothing here runs while a video is being made (render keeps its colors in one place), see the check in app.py.
"""
import emojis
import looks
import preview_data
import render

KINDS = ("trivia", "personality", "wyr", "toplist", "facts", "odd", "story", "clip", "missing")


def _args(kind: str, key: str):
    """(how to draw it, arguments) for one video type on one look."""
    t = preview_data.TYPE_PREVIEWS[key]
    if kind == "trivia":
        p = preview_data.PREVIEWS[key]
        return "scene", dict(header=p["q"], label="QUESTION 1/5", choices=list(p["a"]), visible=4, anim=1.0, q_num=1, num_label="1")
    if kind == "personality":
        q, answers = t["personality"]
        return "scene", dict(header=q, label="QUESTION 1/5", visible=4, anim=1.0, num_label="1", choices=answers)
    if kind == "wyr":
        a, b = t["wyr"]
        return "scene", dict(header="WOULD YOU RATHER...", label="ROUND 1/5", visible=2, anim=1.0, num_label="1", letters="AB",
                             bar_dy=150, choices=[a, b])
    if kind == "odd":
        return "scene", dict(header="WHICH ONE DOESN'T BELONG?", label="ROUND 1/5", visible=4, anim=1.0, num_label="1",
                             choices=preview_data.ODD_PREVIEWS[key])
    if kind == "toplist":
        name, rank, line = t["toplist"]
        return "card", dict(header=name, label=f"#{rank}", badge=str(rank), caption=line)
    if kind == "facts":
        head, fact = t["facts"]
        return "card", dict(header=head, label="FACT 1", badge="1", caption=fact)
    if kind == "story":
        return "story", dict(header="A storm rolls in over the ridge", label="CHAPTER 1/5", choices=["Keep walking", "Find shelter"],
                             visible=2, num_label="1", bar_dy=150)
    if kind == "clip":
        return "story", dict(header="WHAT IS THIS?", label="ROUND 1/5", visible=4, num_label="1", bar_dy=-80, head_y=300,
                             head_size=120, choices=["A hiker", "A camel", "A runner", "A monk"], letters="ABCD")
    return "missing", dict(header="WHAT'S MISSING?", label="ROUND 1/5", grid=list(emojis.THEMES["animals"])[:9], hole=4, visible=3,
                           num_label="1", choices=["Bee", "Lion", "Fish"], letters="ABC")


def draw(kind: str, key: str, colors=None):
    """The graphics layer (RGBA, 1080 x 1920, see-through where the footage shows) for a video type on a look."""
    look = looks.with_colors(looks.LOOKS[key], colors)
    how, args = _args(kind, key)
    old = render.WATERMARK
    render.WATERMARK = ""
    render.apply_skin(look["skin"])
    try:
        fn = {"scene": render.draw_scene, "card": render.draw_card, "story": render.draw_story, "missing": render.draw_missing}[how]
        return fn(theme="purple", **args)
    finally:
        render.reset_skin()
        render.WATERMARK = old
