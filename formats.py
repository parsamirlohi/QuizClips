"""Builds the non-trivia videos: personality quiz, would you rather, story, rankings, fun facts.

Same pipeline as the trivia video (script -> narration -> footage -> scenes -> mp4), but the script comes from
content.py and each format has its own scene layouts.
"""
import random
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import content
import looks
import render
from audio import Mixer, SR, bing, count_sfx, effects, pop, sparkle, tick, whoosh
from config import ASSETS_DIR, OUTPUT_DIR, WORK_DIR, env, flog
from questions import EXTRA_STOP, GENERIC, STOP
from pipeline import FRAME, INTRO_QUERIES, POP_ANIM, _intro_background, cleanup_disk, pause_after, pop_in
from render import concat_videos, mux, render_segment
from tts import synthesize_all
from videos import UsedSet, find_background, find_many

THINK_PERSONALITY = int(env("THINK_PERSONALITY_SECONDS", "15"))   # seconds to pick an answer
FOOTAGE_WORKERS = int(env("FOOTAGE_WORKERS", "5"))   # scenes (footage search + render) handled side by side
THINK_WYR = int(env("THINK_WYR_SECONDS", "11"))   # seconds to choose A or B
RANKS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
LETTERS = "ABCD"


def _lc(s: str) -> str:
    """Lower-case the first letter for reading aloud, but leave acronyms (USA, DJ) alone."""
    return s if s[:2].isupper() else s[:1].lower() + s[1:]


def _pops(frames, t, kind, base, key="anim"):
    frames[:] = [f for f in frames if not (f[0] >= t and key in f[2])]   # a pop that starts before the last one has finished takes over from it
    for k, a in enumerate(POP_ANIM):
        frames.append((round(t + FRAME * k, 4), kind, dict(base, **{key: a})))


def _intro(frames, kind, base, events, sfx, hs=True):
    frames += pop_in(0.0, kind, base)
    events += [(0.0, sfx["whoosh"], 1.0), (0.05, sfx["pop"], 1.0)]


# ------------------------------------------------------------------ scene plans
def _plan_title(spec, clips, sfx):
    """Chalkboard title card with the word being read highlighted."""
    clip = clips[0]
    words = spec["title"].upper().split()
    text = " ".join(words)
    weights = [len(w) + 1 for w in words]
    frames = pop_in(0.0, "hook", dict(text=text, hl=-1), start=0.7)
    t0, dur, acc = 0.4, len(clip) / SR, 0.0
    for k, wt in enumerate(weights):
        frames.append((t0 + dur * acc / sum(weights), "hook", dict(text=text, hl=k, hscale=1.0)))
        acc += wt
    frames.append((t0 + dur, "hook", dict(text=text, hl=-1, hscale=1.0)))
    events = [(0.0, sfx["whoosh"], 1.0), (0.05, sfx["pop"], 1.0), (t0, clip, 1.0)]
    return frames, t0 + dur + 0.9, events, False


def _plan_personality_q(spec, clips, sfx):
    q = spec["q"]
    base = dict(theme="purple", q_num=spec["i"] + 1, header=q["q"], choices=q["options"],
                label=f"QUESTION {spec['i'] + 1}/{spec['total']}", think=THINK_PERSONALITY)
    frames, events = [], [(0.4, clips[0], 1.0)]
    _intro(frames, "scene", dict(base, visible=0), events, sfx)
    t = 0.4 + len(clips[0]) / SR + 0.3
    for k in range(4):
        _pops(frames, t, "scene", dict(base, visible=k + 1))
        events.append((t, sfx["pop"], 1.0))
        t += 0.5
    t += 0.1
    for s_left in range(THINK_PERSONALITY, 0, -1):
        events.append((t, count_sfx(sfx, s_left), 1.0))
        frames.append((t, "scene", dict(base, visible=4, timer=s_left, smooth=True)))   # the bar itself is drawn smoothly by ffmpeg
        t += 1.0
    frames.append((t, "scene", dict(base, visible=4, timer=0.0)))
    return frames, t + 0.4, events, True


def _plan_card(spec, clips, sfx):
    """Header (name), footage, then a caption box that pops in while the sentence is read. Used by results, lists, facts."""
    base = dict(theme="purple", header=spec["header"], label=spec["label"], badge=spec["badge"])
    frames, events = [], [(0.4, clips[0], 1.0)]
    _intro(frames, "card", base, events, sfx)
    t = 0.4 + len(clips[0]) / SR + 0.25
    _pops(frames, t, "card", dict(base, caption=spec["line"]))
    events += [(t, sfx["pop"], 1.0), (t + 0.1, clips[1], 1.0)]
    if spec.get("reveal"):
        events.append((t, sfx["sparkle"], 1.0))
    dur = t + 0.1 + len(clips[1]) / SR + 1.1
    return frames, dur, events, True


def _wyr_base(spec, header="WOULD YOU RATHER..."):
    return dict(theme="purple", header=header, label=f"ROUND {spec['i'] + 1}/{spec['total']}",
                choices=[spec["a"], spec["b"]], letters="AB", num_label=str(spec["i"] + 1), bar_dy=150,
                think=THINK_WYR)


def _plan_wyr_a(spec, clips, sfx):
    """Both options are on screen from the first frame; the narrator reads 'Would you rather A...'"""
    base = _wyr_base(spec)
    frames, events = [], [(0.35, clips[0], 1.0), (0.0, sfx["whoosh"], 1.0), (0.05, sfx["pop"], 1.0)]
    frames += pop_in(0.0, "scene", dict(base, visible=2))
    return frames, 0.35 + len(clips[0]) / SR + 0.1, events, True


def _plan_wyr_b(spec, clips, sfx):
    """Continues straight on with '...or B?', then the only pause: the countdown to decide. Then the reveal."""
    base = _wyr_base(spec)
    frames, events = [(0.0, "scene", dict(base, visible=2))], [(0.0, sfx["whoosh"], 1.0), (0.05, clips[0], 1.0)]
    t = 0.05 + len(clips[0]) / SR + 0.25
    for s_left in range(THINK_WYR, 0, -1):  # countdown to decide
        events.append((t, count_sfx(sfx, s_left), 1.0))
        frames.append((t, "scene", dict(base, visible=2, timer=s_left, smooth=True)))   # the bar itself is drawn smoothly by ffmpeg
        t += 1.0
    reveal = dict(base, header="WHAT YOUR PICK SAYS", choices=[spec["trait_a"], spec["trait_b"]])
    reveal.pop("think")
    frames += pop_in(t, "scene", dict(reveal, visible=2), start=0.85)
    events += [(t, sfx["bing"], 1.0), (t, sfx["whoosh"], 1.0)]
    t += 0.45
    events.append((t, clips[1], 1.0))
    t += len(clips[1]) / SR + 0.15
    events.append((t, clips[2], 1.0))
    t += len(clips[2]) / SR + 1.4
    frames.sort(key=lambda f: f[0])
    return frames, t, events, True


def _story_base(spec):
    survive = spec["mode"] == "survive"
    return dict(theme="purple", header=spec["situation"], label=f"{'STAGE' if survive else 'CHAPTER'} {spec['i'] + 1}/{spec['total']}",
                choices=[spec["a"], spec["b"]], letters="AB", num_label=str(spec["i"] + 1), bar_dy=150, think=THINK_WYR)


def _plan_story_a(spec, clips, sfx):
    """The situation is read, then 'Do you A...'; both options are on screen from the first frame."""
    base = _story_base(spec)
    frames, events = [], [(0.35, clips[0], 1.0), (0.0, sfx["whoosh"], 1.0), (0.05, sfx["pop"], 1.0)]
    frames += pop_in(0.0, "story", dict(base, visible=2))
    return frames, 0.35 + len(clips[0]) / SR + 0.1, events, False


def _plan_story_b(spec, clips, sfx):
    """'...or B?', the countdown to decide, then both outcomes. In 'Would you survive?' a trap is then shown in red."""
    base = _story_base(spec)
    frames, events = [(0.0, "story", dict(base, visible=2))], [(0.0, sfx["whoosh"], 1.0), (0.05, clips[0], 1.0)]
    t = 0.05 + len(clips[0]) / SR + 0.25
    for s_left in range(THINK_WYR, 0, -1):
        events.append((t, count_sfx(sfx, s_left), 1.0))
        frames.append((t, "story", dict(base, visible=2, timer=s_left, smooth=True)))
        t += 1.0
    survive, trap = spec["mode"] == "survive", spec["trap"]
    # Both paths are read in the same order every time (A, then B) and look the same; only at the very end does the narrator
    # say whether one was a trap, so nothing is given away early.
    reveal = dict(base, header="WHERE EACH PATH LEADS", choices=[spec["out_a"], spec["out_b"]])
    reveal.pop("think")
    frames += pop_in(t, "story", dict(reveal, visible=1), start=0.85)
    events += [(t, sfx["bing"], 1.0), (t, sfx["whoosh"], 1.0)]
    t += 0.45
    events.append((t, clips[1], 1.0))
    t += len(clips[1]) / SR + 0.2
    _pops(frames, t, "story", dict(reveal, visible=2))
    events.append((t, sfx["pop"], 1.0))
    t += 0.3
    events.append((t, clips[2], 1.0))
    t += len(clips[2]) / SR + 0.5
    if len(clips) > 3:   # the verdict
        if trap:
            out = spec["fate"] or (spec["out_a"] if trap == "a" else spec["out_b"])
            dead = dict(base, theme="red", header="GAME OVER", choices=[out], letters=trap.upper(), visible=1)
            dead.pop("think")
            frames += pop_in(t, "story", dead, start=0.85)
            events += [(t, sfx["siren"], 1.0), (t, sfx["whoosh"], 1.0)]
            t += 0.3
        else:
            events.append((t, sfx["sparkle"], 1.0))
        events.append((t, clips[3], 1.0))
        t += len(clips[3]) / SR + 1.2
    else:
        t += 0.7
    frames.sort(key=lambda f: f[0])
    return frames, t, events, False


def _plan_odd(spec, clips, sfx):
    """The question is asked, the four things pop in one after another (not read out), a countdown, then the odd one out is
    named and shown in green."""
    cq, cr = clips
    base = dict(theme="purple", header="WHICH ONE DOESN'T BELONG?", label=f"ROUND {spec['i'] + 1}/{spec['total']}",
                choices=spec["items"], correct_idx=spec["odd"], num_label=str(spec["i"] + 1), think=THINK_WYR)
    frames = pop_in(0.0, "scene", dict(base, visible=0))
    events = [(0.0, sfx["whoosh"], 1.0), (0.05, sfx["pop"], 1.0), (0.4, cq, 1.0)]
    when = 0.4 + len(cq) / SR + 0.3
    for k in range(len(spec["items"])):
        _pops(frames, when, "scene", dict(base, visible=k + 1))
        events.append((when, sfx["pop"], 1.0))
        when += 0.5
    t = when + 0.1
    for s_left in range(THINK_WYR, 0, -1):
        events.append((t, count_sfx(sfx, s_left), 1.0))
        frames.append((t, "scene", dict(base, visible=4, timer=s_left, smooth=True)))
        t += 1.0
    frames.append((t, "scene", dict(base, visible=4, reveal=True)))
    frames.sort(key=lambda f: f[0])
    events += [(t, sfx["bing"], 1.0), (t + 0.05, sfx["sparkle"], 1.0), (t + 0.5, cr, 1.0)]
    t += 0.5 + len(cr) / SR + 1.2
    return frames, t, events, True


def _plan_clip(spec, clips, sfx):
    """Full-screen footage that starts as big blocks and gets sharper in steps while the options sit below.
    The reveal shows the footage sharp, with the answer."""
    (cr,) = clips   # only the answer is spoken; "What is this?" is on the screen
    base = dict(theme="purple", header="WHAT IS THIS?", label=f"ROUND {spec['i'] + 1}/{spec['total']}", choices=spec["options"],
                letters="ABCD", num_label=str(spec["i"] + 1), bar_dy=-80, head_y=300, head_size=120, think=THINK_WYR)
    frames = pop_in(0.0, "story", dict(base, visible=4))
    events = [(0.0, sfx["whoosh"], 1.0), (0.05, sfx["pop"], 1.0)]
    t = 1.2   # a moment to see the blocky picture and the options before the countdown starts
    t0 = t
    for s_left in range(THINK_WYR, 0, -1):
        events.append((t, count_sfx(sfx, s_left), 1.0))
        frames.append((t, "story", dict(base, visible=4, timer=s_left, smooth=True)))
        t += 1.0
    k = spec["correct_idx"]
    rev = dict(base, theme="green", header=f"IT'S {spec['answer'].upper()}!", choices=[spec["options"][k]], letters="ABCD"[k], visible=1)
    rev.pop("think")
    frames += pop_in(t, "story", rev, start=0.85)
    events += [(t, sfx["bing"], 1.0), (t + 0.05, sfx["sparkle"], 1.0), (t + 0.5, cr, 1.0)]
    # still blocky right up to the reveal so it stays hard to guess; it only becomes clear when the answer shows
    spec["pixel"] = [(0.0, 64), (t0 + 0.1 * THINK_WYR, 48), (t0 + 0.22 * THINK_WYR, 36), (t0 + 0.34 * THINK_WYR, 28),
                     (t0 + 0.46 * THINK_WYR, 22), (t, 1)]   # 22 stays for the last half of the thinking time
    t += 0.5 + len(cr) / SR + 1.2   # (the real end of a round is set by pause_after in formats.py / pipeline.py)
    return frames, t, events, False


MEMORIZE_SECONDS = 4


def _plan_missing(spec, clips, sfx):
    """Look at the pictures (a short countdown), then one is gone: pick which, countdown, and it comes back with a frame."""
    c_look, c_ask, c_ans = clips
    base = dict(theme="purple", label=f"ROUND {spec['i'] + 1}/{spec['total']}", grid=spec["grid"], num_label=str(spec["i"] + 1))
    look = dict(base, header="MEMORIZE THESE!", think=MEMORIZE_SECONDS)
    frames = pop_in(0.0, "missing", look)
    events = [(0.0, sfx["whoosh"], 1.0), (0.05, sfx["pop"], 1.0), (0.35, c_look, 1.0)]
    t = 0.35 + len(c_look) / SR + 0.2
    for s_left in range(MEMORIZE_SECONDS, 0, -1):
        events.append((t, count_sfx(sfx, s_left), 1.0))
        frames.append((t, "missing", dict(look, timer=s_left, smooth=True)))
        t += 1.0
    ask = dict(base, header="WHAT'S MISSING?", hole=spec["hole"], choices=spec["options"], letters="ABC", think=THINK_WYR)
    frames += pop_in(t, "missing", dict(ask, visible=0), start=0.85)
    events += [(t, sfx["whoosh"], 1.0), (t + 0.3, c_ask, 1.0)]
    t += 0.3 + len(c_ask) / SR + 0.25
    for k in range(3):
        _pops(frames, t, "missing", dict(ask, visible=k + 1))
        events.append((t, sfx["pop"], 1.0))
        t += 0.5
    t += 0.1
    for s_left in range(THINK_WYR, 0, -1):
        events.append((t, count_sfx(sfx, s_left), 1.0))
        frames.append((t, "missing", dict(ask, visible=3, timer=s_left, smooth=True)))
        t += 1.0
    k = spec["correct_idx"]
    rev = dict(base, theme="green", header=f"IT WAS THE {spec['answer'].upper()}!", hi=spec["hole"], choices=[spec["options"][k]],
               letters="ABC"[k], visible=1)
    frames += pop_in(t, "missing", rev, start=0.85)
    events += [(t, sfx["bing"], 1.0), (t + 0.05, sfx["sparkle"], 1.0), (t + 0.5, c_ans, 1.0)]
    t += 0.5 + len(c_ans) / SR + 1.3
    frames.sort(key=lambda f: f[0])
    return frames, t, events, False


def _plan_end(spec, clips, sfx):
    base = dict(theme="purple", header=spec["header"], num_label=False, label=spec["label"], letters=spec["letters"],
                choices=spec["choices"])
    frames, events = [], [(0.4, clips[0], 1.0)]
    _intro(frames, "scene", dict(base, lit=0), events, sfx)
    for k in range(len(spec["choices"])):
        t = 0.9 + 0.6 * k
        _pops(frames, t, "scene", dict(base, lit=3, visible=k + 1))
        events.append((t, sfx["pop"], 1.0))
    frames.sort(key=lambda f: f[0])
    return frames, max(0.4 + len(clips[0]) / SR + 1.0, 3.0), events, True


# Scenes that finish a round (the first half of a would-you-rather or a story step flows straight into the second half)
from pipeline import GAP   # the same transition length as every other video type
ROUND_ENDS = {"pq", "card", "wyr_b", "story_b", "odd", "clip", "missing"}

PLANNERS = {"title": _plan_title, "pq": _plan_personality_q, "card": _plan_card, "wyr_a": _plan_wyr_a,
            "wyr_b": _plan_wyr_b, "story_a": _plan_story_a, "story_b": _plan_story_b, "odd": _plan_odd, "clip": _plan_clip, "missing": _plan_missing, "end": _plan_end}


# ------------------------------------------------------------------ script -> scene specs
def _specs(data: dict) -> list:
    kind = data["kind"]
    specs = [dict(t="title", title=data["title"], texts=[data["title"]], search=None)]
    if kind == "personality":
        qs, rs = data["questions"], data["results"]
        for i, q in enumerate(qs):
            specs.append(dict(t="pq", i=i, total=len(qs), q=q, texts=[q["q"]], search=q["search"],
                              check=f'Quiz "{data["title"]}". This scene goes with the question: {q["q"]}',
                              row=(q["q"], " | ".join(f"{LETTERS[k]}. {o}" for k, o in enumerate(q["options"])))))
        for k, r in enumerate(rs):
            specs.append(dict(t="card", header=r["name"], label=f"MOSTLY {LETTERS[k]}", line=r["description"],
                              badge=LETTERS[k], reveal=True, texts=[f"Mostly {LETTERS[k]}. {r['name']}!", r["description"]],
                              search=r["search"],
                              check=f'Quiz "{data["title"]}". Result: {r["name"]}. {r["description"]}',
                              row=(f"Mostly {LETTERS[k]}: {r['name']}", r["description"])))
        specs.append(dict(t="end", header="Which one are you?", label="COMMENT YOUR RESULT", letters=LETTERS,
                          choices=[r["name"] for r in rs], search=None,
                          texts=["Which one did you get? Comment your result, and follow for more quizzes!"]))
    elif kind == "wyr":
        rounds = data["rounds"]
        for i, r in enumerate(rounds):
            common = dict(i=i, total=len(rounds), a=r["a"], b=r["b"], trait_a=r["trait_a"], trait_b=r["trait_b"])
            specs.append(dict(common, t="wyr_a", texts=[f"Would you rather {_lc(r['a'])}..."], search=r["search_a"],
                              check=r["a"], row=(f"{r['a']}  vs  {r['b']}", f"A: {r['trait_a']}  |  B: {r['trait_b']}")))
            specs.append(dict(common, t="wyr_b", texts=[f"or {_lc(r['b'])}?", f"Pick A if you're {r['trait_a']}.",
                                                       f"Pick B if you're {r['trait_b']}."],
                              search=r["search_b"], check=r["b"], row=None))
        specs.append(dict(t="end", header="A or B?", label="COMMENT YOUR PICKS", letters="ABC",
                          choices=["Mostly A", "Mostly B", "Half and half"], search=None,
                          texts=["Which did you pick most? Comment A or B, and follow for more!"]))
    elif kind == "missing":
        rounds = data["rounds"]
        for i, r in enumerate(rounds):
            specs.append(dict(t="missing", i=i, total=len(rounds), grid=r["grid"], hole=r["hole"], options=r["options"],
                              correct_idx=r["correct_idx"], answer=r["answer"],
                              texts=["Memorize these pictures!", "What's missing?", f"{r['answer']}!"],
                              search=None, row=(" | ".join(r["options"]), f"Missing: {LETTERS[r['correct_idx']]}. {r['answer']}")))
        specs.append(dict(t="end", header="How many did you find?", label="COMMENT YOUR SCORE", letters="123",
                          choices=["Found them all", "Found most", "Need a hint"], search=None,
                          texts=["How many did you find? Comment your score, and follow for more!"]))
    elif kind == "odd":
        rounds = data["rounds"]
        for i, r in enumerate(rounds):
            items = r["items"]
            odd = items[r["odd"]]
            specs.append(dict(t="odd", i=i, total=len(rounds), items=items, odd=r["odd"], reason=r["reason"],
                              texts=["Which one doesn't belong?", f"{odd}!"], search=r["search"], check=" ".join(items),
                              row=(" | ".join(items), f"Odd one: {odd}. {r['reason']}")))
        specs.append(dict(t="end", header="How many did you spot?", label="COMMENT YOUR SCORE", letters="123",
                          choices=["Spotted them all", "Most of them", "Only a few"], search=None,
                          texts=["How many did you spot? Comment your score, and follow for more!"]))
    elif kind == "clip":
        rounds = data["rounds"]
        for i, r in enumerate(rounds):
            o = r["options"]
            specs.append(dict(t="clip", i=i, total=len(rounds), options=o, correct_idx=r["correct_idx"], answer=r["answer"],
                              texts=[f"{r['answer']}!"],   # the question is on screen, not read out; just the answer, no "It's"
                              search=r["search"], check=r["answer"],
                              row=(" | ".join(o), f"Answer: {LETTERS[r['correct_idx']]}. {r['answer']}")))
        specs.append(dict(t="end", header="How many did you get?", label="COMMENT YOUR SCORE", letters="123",
                          choices=["Got them all", "Got most", "Need glasses"], search=None,
                          texts=["How many did you guess? Comment your score, and follow for more!"]))
    elif kind == "story":
        steps, mode = data["steps"], data.get("mode", "path")
        for i, st in enumerate(steps):
            trap = st["trap"] if mode == "survive" else ""
            common = dict(i=i, total=len(steps), mode=mode, situation=st["situation"], a=st["a"], b=st["b"],
                          out_a=st["out_a"], out_b=st["out_b"], trap=trap, fate=st.get("fate", ""))
            lines = [f"Pick A. {st['out_a']}", f"Pick B. {st['out_b']}"]   # both paths read in order, the verdict comes last
            if trap:
                fate = st.get("fate") or (st["out_a"] if trap == "a" else st["out_b"])
                lines.append(f"But {trap.upper()} was the trap! {fate} Game over!")
            elif mode == "survive":
                lines.append("Both paths were safe! You live to see the next one.")
            specs.append(dict(common, t="story_a", texts=[f"{st['situation']} Do you {_lc(st['a'])}..."], search=st["search"],
                              check=st["situation"],
                              row=(st["situation"], f"A: {st['a']} -> {st['out_a']} | B: {st['b']} -> {st['out_b']}"
                                   + (f"  [TRAP: {trap.upper()}]" if trap else ""))))
            specs.append(dict(common, t="story_b", texts=[f"or {_lc(st['b'])}?"] + lines, search=st["search_out"],
                              check=st["out_b"] if trap == "b" else st["out_a"], row=None))
        if mode == "survive":
            specs.append(dict(t="end", header="Did you survive?", label="COMMENT YOUR SCORE", letters="123",
                              choices=["Survived every trap", "Barely made it", "Fell for one"], search=None,
                              texts=["How many traps did you survive? Comment your score, and follow for more!"]))
        else:
            specs.append(dict(t="end", header="Which path?", label="COMMENT YOUR PICKS", letters="ABC",
                              choices=["Mostly A", "Mostly B", "Mixed"], search=None,
                              texts=["Which path would you take? Comment your picks, and follow for more!"]))
    else:
        items = data["items"]
        n = len(items)
        for idx, it in enumerate(items):
            if kind == "toplist":
                rank = n - idx
                head = f"Number {RANKS.get(rank, rank)}. {it['name']}."
                label, badge = f"#{rank}", str(rank)
            else:
                head = f"{it['name']}!"
                label, badge = f"FACT {idx + 1}", str(idx + 1)
            specs.append(dict(t="card", header=it["name"], label=label, line=it["line"], badge=badge,
                              texts=[head, it["line"]], search=it["search"], check=f"{it['name']}. {it['line']}",
                              row=(it["name"], it["line"])))
        if kind == "toplist":
            top = list(reversed(items[-3:]))
            specs.append(dict(t="end", header="Your number one?", label="COMMENT YOUR PICK", letters="123",
                              choices=[t["name"] for t in top], search=None,
                              texts=["Do you agree with this list? Comment your number one, and follow for more!"]))
        else:
            specs.append(dict(t="end", header="Learn something?", label="COMMENT BELOW", letters="123",
                              choices=["I knew that", "Learned something", "Mind blown"], search=None,
                              texts=["Did you learn something new? Follow for more facts!"]))
    return specs


def _footage(spec, used):
    """(path, matched search). Never fails the whole video over one scene: falls back to an abstract background."""
    try:
        return find_background(list(spec["search"]), used, spec.get("check", ""))
    except Exception as e:
        print(f"[footage] {e}; using an abstract background", flush=True)
        return find_background(random.sample(INTRO_QUERIES, 2) + ["abstract background"], used)


# ------------------------------------------------------------------ build
INTRO_BY_KIND = {
    "personality": ["neon lights abstract", "light particles", "bokeh lights"],
    "wyr": ["colorful abstract background", "split screen light", "glowing lines"],
    "toplist": ["podium spotlight", "stage lights", "confetti"],
    "facts": ["galaxy stars", "light bulb idea", "space nebula"],
    "story": ["misty forest", "dark cinematic landscape", "foggy mountains"],
    "odd": ["colorful shapes abstract", "geometric patterns", "bokeh lights"],
    "clip": ["mystery fog", "light rays", "fog"],
    "missing": ["colorful shapes abstract", "bokeh lights", "glowing particles"],
}


_NOT_A_SUBJECT = {"quiz", "personality", "test", "guess", "trivia", "ultimate", "video", "videos", "fun", "best", "top",
                  "rather", "versus", "pick", "choose", "chapter", "episode", "story", "game", "facts", "fact", "ranking",
                  "rankings", "amazing", "mind", "blowing", "five", "ten", "seven", "fastest", "biggest", "greatest",
                  "spirit", "soul", "vibe", "vibes", "aura", "energy", "type", "kind", "mood", "personality"}


def topic_words(text):
    """The words of a title or topic that name something you could film ('Which soccer player are you?' -> soccer, player)."""
    out = []
    for w in re.findall(r"[A-Za-z][A-Za-z'\-]+", text or ""):
        lw = w.lower().strip("'-")
        if len(lw) < 3 or lw in STOP or lw in EXTRA_STOP or lw in GENERIC or lw in _NOT_A_SUBJECT or lw in out:
            continue
        out.append(lw)
    return out


def intro_queries(kind, topic, title, scene_terms=()):
    """Footage searches for the first scene, best first: the video's own subject as clean keywords (never the whole title as
    a sentence, which matches stock tags badly), then the footage terms its own scenes use, then the type's mood footage,
    then an abstract background. The guessing games stay generic so the intro never hints at an answer."""
    queries = []
    if kind not in ("clip", "odd", "missing"):
        words = topic_words(topic) or topic_words(title)
        if len(words) >= 2:
            queries.append(" ".join(words[:2]))
        extra = [t[:40] for t in scene_terms if t]
        if extra:
            queries.append(extra.pop(0))   # a specific scene term beats a lone generic word ('animals')
        if words:
            queries.append(words[0])
        queries += extra
        seen = set()
        queries = [q for q in queries if not (q.lower() in seen or seen.add(q.lower()))]
    return queries[:6] + INTRO_BY_KIND.get(kind, []) + ["abstract background"]


def _themed_intro(kind, topic, title, used, scene_terms=()):
    """First-scene footage for every type except trivia: matches the theme/story (never the answers of a guessing
    game), falling back to the type's mood footage, then an abstract background."""
    queries = intro_queries(kind, topic, title, scene_terms)
    check = "" if kind in ("clip", "odd", "missing") else f'Opening clip for a video called "{title}" (subject: {topic or title}). It should show that subject.'
    try:
        return find_background(queries, used, check)[0]
    except Exception as e:
        print(f"[intro] themed intro failed: {e}", flush=True)
        return _intro_background(used)


def build_video(kind: str, topic: str, n: int, voice: str = "en-US-AriaNeural", progress=lambda msg, frac: None,
                watermark: str = "", style: str = looks.DEFAULT, colors=None, custom=None, mode: str = "path",
                timer_sound: str = "ticks", pop_sound: str = "pop", mix=None) -> dict:
    t_begin = time.time()
    render.WATERMARK = watermark or ""
    look = looks.with_colors(looks.resolve(style), colors)
    render.apply_skin(look["skin"])
    job_dir = WORK_DIR / uuid.uuid4().hex[:8]
    job_dir.mkdir(parents=True)
    try:
        progress("Preparing the look...", 0.02)
        look_info = {"bg": looks.ensure_background(look["key"]), "blur": look["blur"]}
        if custom:
            progress("Reading your content...", 0.03)
            data = dict(content.add_terms(kind, custom), kind=kind, topic="", mode=mode)
        else:
            progress("Writing the script...", 0.03)
            data = content.generate(kind, topic, n, mode)
        specs = _specs(data)
        t_script = time.time()

        # Narration, footage and rendering overlap: narration is recorded while the first footage searches run, and
        # each scene is rendered as soon as its own footage is in (scenes are handled several at a time).
        progress("Recording narration...", 0.08)
        flat = [t for s in specs for t in s["texts"]]
        sfx = effects(timer_sound, pop_sound)
        used = UsedSet()
        gate = threading.Lock()
        box = {}

        def narration():
            all_clips = synthesize_all(flat, voice)
            pos = 0
            for s in specs:
                s["clips"] = all_clips[pos:pos + len(s["texts"])]
                pos += len(s["texts"])

        def get_plans():   # needs the narration (clip lengths), so it waits for it
            with gate:
                if "plans" not in box:
                    box["tts"].result()
                    # every scene is a whole number of video frames long, so the audio placed by adding the lengths stays in step
                    plans = []
                    for s in specs:
                        f, d, e, h = PLANNERS[s["t"]](s, s["clips"], sfx)
                        if s["t"] in ROUND_ENDS:   # the end of a round: the answer stays up for a quiet moment before the next one starts
                            d = pause_after(f, e)
                        plans.append((f, render.frame_ceil(d), e, h))
                    box["plans"] = plans
                return box["plans"]

        last = len(specs) - 1

        def has_gap(si):   # after every scene except the last, and except where one scene runs straight on into the next
            return si < last and specs[si]["t"] not in ("wyr_a", "story_a")

        def scene(si):
            s = specs[si]
            if si == 0:
                mine = ASSETS_DIR / f"intro_{kind}.mp4"
                if kind in ("story", "personality", "toplist", "wyr", "clip") and mine.exists():   # these types always open with their own clip
                    s["bg"] = mine
                elif kind == "trivia":
                    s["bg"] = _intro_background(used)
                else:   # the video's real subject (also when the topic was picked for you), plus the footage terms its own scenes use
                    own = [(x.get("search") or [None])[0] if isinstance(x.get("search"), list) else x.get("search") for x in specs[1:4]]
                    if kind == "personality":   # a question about music would give a piano: the quiz's own subject is in its results
                        own = [(r.get("search") or [None])[0] for r in (data.get("results") or [])[:4] if isinstance(r, dict)]
                    s["bg"] = _themed_intro(kind, data.get("topic") or topic, s["title"], used, [t for t in own if isinstance(t, str)])
            elif si == last:
                s["bg"] = find_background(random.sample(INTRO_QUERIES, 2) + ["abstract background"], used)[0]
            elif s["search"]:
                s["bg"], s["matched"] = _footage(s, used)
            frames, dur, events, has_clip = get_plans()[si]
            bg = s.get("bg")
            full_bg = bg if frames[0][1] in ("hook", "story") else None
            render_segment(bg if has_clip else None, frames, dur, job_dir / f"seg_{si:02d}.mp4", job_dir,
                           full=full_bg, look=look_info, pixel=s.get("pixel"))
            if has_gap(si):   # everything leaves the screen for a moment: just the background, while the whoosh plays
                # a full-screen footage scene (the intro, Guess the clip): the footage stays and carries on playing while only the text leaves
                render_segment(bg if has_clip else None, [(0.0, "empty", {})], GAP, job_dir / f"gap_{si:02d}.mp4", job_dir,
                               full=full_bg, look=look_info, hide_clip=True, skip=render.frames_for(dur) / render.FPS)   # a full-screen video (the intro) goes away with its text

        progress("Finding footage and rendering...", 0.14)
        with ThreadPoolExecutor(max_workers=1) as tts_pool:
            box["tts"] = tts_pool.submit(narration)
            find_many([(lambda si=si: scene(si)) for si in range(len(specs))], FOOTAGE_WORKERS,
                      
                      lambda d, t: progress(f"Finding footage and rendering {d} of {t}...", 0.14 + 0.74 * d / max(1, t)))
        plans = get_plans()
        t_scenes = time.time()
        total = sum(p[1] for p in plans) + sum(GAP for si in range(len(plans)) if has_gap(si))
        mixer, seg_paths, offset = Mixer(total), [], 0.0
        for si, (frames, dur, events, has_clip) in enumerate(plans):
            seg_paths.append(job_dir / f"seg_{si:02d}.mp4")
            for t, clip, gain in events:
                if clip is sfx["whoosh"] and t == 0.0:   # the scene-change whoosh plays in the gap instead (below)
                    continue
                mixer.add(offset + t, clip, gain)
            offset += dur
            if has_gap(si):
                seg_paths.append(job_dir / f"gap_{si:02d}.mp4")
                mixer.add(offset, sfx["whoosh"], 1.0)   # starts the moment the scene clears away
                offset += GAP

        progress("Mixing audio and finishing...", 0.92)
        audio_wav = job_dir / "audio.wav"
        mixer.save(audio_wav, total, mix)
        video_only = job_dir / "video.mp4"
        concat_videos(seg_paths, video_only, job_dir)
        name = f"quiz_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        mux(video_only, audio_wav, OUTPUT_DIR / name)

        rows = []
        for si, s in enumerate(specs):
            if s.get("row"):
                foot = s.get("matched", "")
                if s["t"] in ("wyr_a", "story_a"):
                    foot = f"{foot} | then: {specs[si + 1].get('matched', '')}"
                rows.append({"question": s["row"][0], "answer": s["row"][1], "footage": foot})
        flog(f"[timing] {kind}: script {t_script - t_begin:.0f}s | narration, footage and scenes {t_scenes - t_script:.0f}s | "
             f"mixing and finishing {time.time() - t_scenes:.0f}s | total {time.time() - t_begin:.0f}s for a {total:.0f}s video")
        return {"look": look["title"], "file": name, "duration": round(total, 1), "title": data["title"], "questions": rows}
    finally:
        render.reset_skin()
        shutil.rmtree(job_dir, ignore_errors=True)
        cleanup_disk()
