"""Builds the non-trivia videos: personality quiz, would you rather, top list, did-you-know facts.

Same pipeline as the trivia video (script -> narration -> footage -> scenes -> mp4), but the script comes from
content.py and each format has its own scene layouts.
"""
import random
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import content
import looks
import render
from audio import Mixer, SR, bing, effects, pop, sparkle, tick, whoosh
from config import OUTPUT_DIR, WORK_DIR, env
from pipeline import INTRO_QUERIES, POP_ANIM, _intro_background, cleanup_disk
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
    for k, a in enumerate(POP_ANIM):
        frames.append((t + 0.05 * k, kind, dict(base, **{key: a})))


def _intro(frames, kind, base, events, sfx, hs=True):
    frames += [(0.0, kind, dict(base, hscale=0.8)), (0.05, kind, dict(base, hscale=1.06)), (0.1, kind, dict(base))]
    events += [(0.0, sfx["whoosh"], 1.0), (0.05, sfx["pop"], 1.0)]


# ------------------------------------------------------------------ scene plans
def _plan_title(spec, clips, sfx):
    """Chalkboard title card with the word being read highlighted."""
    clip = clips[0]
    words = spec["title"].upper().split()
    text = " ".join(words)
    weights = [len(w) + 1 for w in words]
    frames = [(0.0, "hook", dict(text=text, hl=-1, hscale=0.7)), (0.06, "hook", dict(text=text, hl=-1, hscale=1.08)),
              (0.12, "hook", dict(text=text, hl=-1, hscale=1.0))]
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
        events.append((t, sfx["tick"], 1.0))
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
    frames += [(0.0, "scene", dict(base, visible=2, hscale=0.8)), (0.05, "scene", dict(base, visible=2, hscale=1.06)),
               (0.1, "scene", dict(base, visible=2))]
    return frames, 0.35 + len(clips[0]) / SR + 0.1, events, True


def _plan_wyr_b(spec, clips, sfx):
    """Continues straight on with '...or B?', then the only pause: the countdown to decide. Then the reveal."""
    base = _wyr_base(spec)
    frames, events = [(0.0, "scene", dict(base, visible=2))], [(0.05, clips[0], 1.0)]
    t = 0.05 + len(clips[0]) / SR + 0.25
    for s_left in range(THINK_WYR, 0, -1):  # countdown to decide
        events.append((t, sfx["tick"], 1.0))
        frames.append((t, "scene", dict(base, visible=2, timer=s_left, smooth=True)))   # the bar itself is drawn smoothly by ffmpeg
        t += 1.0
    reveal = dict(base, header="WHAT YOUR PICK SAYS", choices=[spec["trait_a"], spec["trait_b"]])
    reveal.pop("think")
    frames += [(t, "scene", dict(reveal, visible=2, hscale=0.85)), (t + 0.05, "scene", dict(reveal, visible=2, hscale=1.05)),
               (t + 0.1, "scene", dict(reveal, visible=2))]
    events += [(t, sfx["bing"], 1.0), (t, sfx["whoosh"], 1.0)]
    t += 0.45
    events.append((t, clips[1], 1.0))
    t += len(clips[1]) / SR + 0.15
    events.append((t, clips[2], 1.0))
    t += len(clips[2]) / SR + 1.4
    frames.sort(key=lambda f: f[0])
    return frames, t, events, True


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


PLANNERS = {"title": _plan_title, "pq": _plan_personality_q, "card": _plan_card, "wyr_a": _plan_wyr_a,
            "wyr_b": _plan_wyr_b, "end": _plan_end}


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
            specs.append(dict(t="end", header="Did you know?", label="COMMENT BELOW", letters="123",
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
def build_video(kind: str, topic: str, n: int, voice: str = "en-US-AriaNeural", progress=lambda msg, frac: None,
                watermark: str = "", style: str = looks.DEFAULT, colors=None, custom=None) -> dict:
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
            data = dict(content.add_terms(kind, custom), kind=kind, topic="")
        else:
            progress("Writing the script...", 0.03)
            data = content.generate(kind, topic, n)
        specs = _specs(data)

        # Narration, footage and rendering overlap: narration is recorded while the first footage searches run, and
        # each scene is rendered as soon as its own footage is in (scenes are handled several at a time).
        progress("Recording narration...", 0.08)
        flat = [t for s in specs for t in s["texts"]]
        sfx = effects()
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
                    box["plans"] = [PLANNERS[s["t"]](s, s["clips"], sfx) for s in specs]
                return box["plans"]

        last = len(specs) - 1

        def scene(si):
            s = specs[si]
            if si == 0:
                s["bg"] = _intro_background(used)
            elif si == last:
                s["bg"] = find_background(random.sample(INTRO_QUERIES, 2) + ["abstract background"], used)[0]
            elif s["search"]:
                s["bg"], s["matched"] = _footage(s, used)
            frames, dur, events, has_clip = get_plans()[si]
            bg = s.get("bg")
            render_segment(bg if has_clip else None, frames, dur, job_dir / f"seg_{si:02d}.mp4", job_dir,
                           full=bg if frames[0][1] == "hook" else None, look=look_info)

        progress("Finding footage and rendering...", 0.14)
        with ThreadPoolExecutor(max_workers=1) as tts_pool:
            box["tts"] = tts_pool.submit(narration)
            find_many([(lambda si=si: scene(si)) for si in range(len(specs))], FOOTAGE_WORKERS,
                      lambda d, t: progress(f"Finding footage and rendering {d} of {t}...", 0.14 + 0.74 * d / max(1, t)))
        plans = get_plans()
        total = sum(p[1] for p in plans)
        mixer, seg_paths, offset = Mixer(total), [], 0.0
        for si, (frames, dur, events, has_clip) in enumerate(plans):
            seg_paths.append(job_dir / f"seg_{si:02d}.mp4")
            for t, clip, gain in events:
                mixer.add(offset + t, clip, gain)
            offset += dur

        progress("Mixing audio and finishing...", 0.92)
        audio_wav = job_dir / "audio.wav"
        mixer.save(audio_wav, total)
        video_only = job_dir / "video.mp4"
        concat_videos(seg_paths, video_only, job_dir)
        name = f"quiz_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        mux(video_only, audio_wav, OUTPUT_DIR / name)

        rows = []
        for si, s in enumerate(specs):
            if s.get("row"):
                foot = s.get("matched", "")
                if s["t"] == "wyr_a":
                    foot = f"A: {foot} | B: {specs[si + 1].get('matched', '')}"
                rows.append({"question": s["row"][0], "answer": s["row"][1], "footage": foot})
        return {"look": look["title"], "file": name, "duration": round(total, 1), "title": data["title"], "questions": rows}
    finally:
        render.reset_skin()
        shutil.rmtree(job_dir, ignore_errors=True)
        cleanup_disk()
