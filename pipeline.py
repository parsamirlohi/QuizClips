"""Builds one complete quiz video: questions -> narration -> backgrounds -> scenes -> final mp4."""
import random
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from audio import SR, Mixer, bing, challenge_sting, pop, siren, sparkle, tick, whoosh
from chalkboard import ensure_chalkboard
from config import ASSETS_DIR, CACHE_DIR, OUTPUT_DIR, WORK_DIR, env
from videos import UsedSet, find_background, find_many
from questions import LETTERS, get_questions, keywords_from, mark_used, pick_letters
import looks
import render
from footage_plan import refine_queries
from render import concat_videos, mux, render_segment
from tts import synthesize_all

NUMWORD = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
INTRO_QUERIES = ["neon lights abstract", "colorful abstract background", "light particles",
                 "glowing lines", "bokeh lights", "abstract waves"]
PROMPTS = ["Pick your answer!", "Comment your guess!", "Lock it in!", "No cheating!", "Think fast!",
           "Shout it out in the comments!", "Which one is it?"]
THINK = int(env("THINK_SECONDS", "8"))
POP_ANIM = (0.55, 1.08, 0.96, 1.0)


def _intro_background(used):
    """Real chalkboard picture/video for the intro. Order: your own assets/intro_bg.* file, then a chalkboard
    video from Pixabay, then the built-in generated chalkboard picture."""
    for ext in ("mp4", "mov", "webm", "jpg", "jpeg", "png"):
        mine = ASSETS_DIR / f"intro_bg.{ext}"
        if mine.exists():
            return mine
    try:
        return find_background(["chalkboard writing", "chalkboard", "blackboard classroom"], used)[0]
    except Exception as e:  # no internet / no result: fall back to the offline picture
        print(f"[intro] using built-in chalkboard: {e}", flush=True)
        return ensure_chalkboard()


def _pops(frames, t, base, key="anim"):
    for k, a in enumerate(POP_ANIM):
        frames.append((t + 0.05 * k, "scene", dict(base, **{key: a})))


def _plan_hook(clip, n, sfx):
    """Chalkboard intro. The word being read is highlighted pink, moving along with the voice."""
    w = NUMWORD.get(n, str(n))
    words = ["ONLY", "A", "GENIUS", "CAN", "GET", f"{n}/{n}"]
    spoken = ["only", "a", "genius", "can", "get", f"{w} out of {w}"]
    weights = [len(x) + 1 for x in spoken]
    text = " ".join(words)
    frames = [(0.0, "hook", dict(text=text, hl=-1, hscale=0.7)), (0.06, "hook", dict(text=text, hl=-1, hscale=1.08)),
              (0.12, "hook", dict(text=text, hl=-1, hscale=1.0))]
    t0, dur = 0.4, len(clip) / SR
    acc = 0.0
    for k, wt in enumerate(weights):
        frames.append((t0 + dur * acc / sum(weights), "hook", dict(text=text, hl=k, hscale=1.0)))
        acc += wt
    frames.append((t0 + dur, "hook", dict(text=text, hl=-1, hscale=1.0)))
    events = [(0.0, sfx["whoosh"], 0.8), (0.05, sfx["pop"], 0.6), (t0, clip, 1.0)]
    return frames, t0 + dur + 0.9, events, False


def _plan_challenge(clip, sfx):
    """Slam-in title card: riser, two hits (CHALLENGE, ROUND), then the narrator. Smooth 24-30 fps animation."""
    dur = max(3.4, 1.25 + len(clip) / SR + 0.45)
    times, t = [], 0.0
    while t < dur:
        times.append(round(t, 4))
        t += 1 / 24 if t < 1.7 else 1 / 15
    frames = [(t, "challenge", dict(t=t, dur=dur)) for t in times]
    events = [(0.0, sfx["sting"], 0.95), (1.25, clip, 1.0)]
    return frames, dur, events, False


def _plan_question(i, total, q, clips, sfx, challenge=False):
    """Question read aloud, choices pop in (pop sound each), short prompt, countdown, then ONLY the answer."""
    cq, cp, cr = clips
    theme = "red" if challenge else "purple"
    base = dict(theme=theme, q_num=i + 1, header=q["question"], choices=q["choices"], correct_idx=q["correct_idx"],
                label=f"QUESTION {i + 1}/{total}", think=THINK)
    frames = [(0.0, "scene", dict(base, visible=0, hscale=0.8)), (0.05, "scene", dict(base, visible=0, hscale=1.06)),
              (0.1, "scene", dict(base, visible=0))]
    events = [(0.0, sfx["whoosh"], 0.8), (0.05, sfx["pop"], 0.6), (0.4, cq, 1.0)]
    t = 0.4 + len(cq) / SR + 0.3
    for k in range(len(q["choices"])):
        _pops(frames, t, dict(base, visible=k + 1))
        events.append((t, sfx["pop"], 0.6))
        t += 0.5
    t += 0.1
    events.append((t, cp, 1.0))
    for s_left in range(THINK, 0, -1):
        events.append((t, sfx["tick"], 0.4))
        for sub in range(6):
            frames.append((t + sub / 6, "scene", dict(base, visible=len(q["choices"]), timer=s_left - sub / 6)))
        t += 1.0
    full = dict(base, visible=len(q["choices"]), reveal=True)
    frames.append((t, "scene", full))
    events += [(t, sfx["bing"], 0.9), (t + 0.05, sfx["sparkle"], 0.7), (t + 0.5, cr, 1.0)]
    t += 0.5 + len(cr) / SR + 1.2
    return frames, t, events, True


def _plan_outro(clip, sfx):
    base = dict(theme="purple", header="How did you do?", num_label=False, label="COMMENT YOUR SCORE",
                letters="SAB", choices=["All correct: Quiz Master", "Most correct: Sharp Mind", "Few correct: Keep Trying"])
    frames = [(0.0, "scene", dict(base, lit=0, hscale=0.8)), (0.05, "scene", dict(base, lit=0, hscale=1.06)),
              (0.1, "scene", dict(base, lit=0))]
    events = [(0.0, sfx["whoosh"], 0.8), (0.05, sfx["pop"], 0.5), (0.4, clip, 1.0)]
    dur = 0.4 + len(clip) / SR + 1.0
    for k in range(3):
        t = 0.9 + 0.6 * k
        _pops(frames, t, dict(base, lit=3, visible=k + 1))
        events.append((t, sfx["pop"], 0.6))
    frames.sort(key=lambda f: f[0])
    return frames, max(dur, 3.0), events, True


def cleanup_disk() -> None:
    """Keep disk use small: clear downloaded stock clips and (optionally) trim old finished videos."""
    if env("KEEP_CACHE") != "1":
        for f in CACHE_DIR.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
    keep = int(env("MAX_KEEP_VIDEOS", "0") or 0)  # 0 = keep every finished video
    if keep > 0:
        vids = sorted(OUTPUT_DIR.glob("quiz_*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in vids[keep:]:
            try:
                old.unlink()
            except OSError:
                pass


def build_quiz(n_questions: int = 5, voice: str = "en-US-AriaNeural", progress=lambda msg, frac: None,
               categories=None, watermark: str = "", style: str = looks.DEFAULT, custom=None, colors=None) -> dict:
    """custom = the person's own questions: [{"question", "choices", "correct_idx"}]. colors = their colour changes."""
    render.WATERMARK = watermark or ""
    look = looks.with_colors(looks.resolve(style), colors)
    render.apply_skin(look["skin"])
    job_dir = WORK_DIR / uuid.uuid4().hex[:8]
    job_dir.mkdir(parents=True)
    try:
        progress("Preparing the look...", 0.02)
        look_info = {"bg": looks.ensure_background(look["key"]), "blur": look["blur"]}
        if custom:
            progress("Reading your questions...", 0.03)
            quiz = []
            for c in custom:
                correct = c["choices"][c["correct_idx"]]
                quiz.append({"question": c["question"], "correct": correct, "choices": list(c["choices"]),
                             "correct_idx": c["correct_idx"], "wrong": [x for x in c["choices"] if x != correct],
                             "category": "", "video_queries": keywords_from(c["question"], correct, "")})
            n = len(quiz)
            challenge = False   # the "challenge round" is only for the generated quizzes
        else:
            progress("Picking questions...", 0.03)
            raw = get_questions(n_questions, categories)
            quiz = []
            for q, ci in zip(raw, pick_letters(n_questions)):
                others = list(q["wrong"][:3])
                random.shuffle(others)
                quiz.append({**q, "choices": others[:ci] + [q["correct"]] + others[ci:], "correct_idx": ci})
            n = n_questions
            challenge = n >= 5
        word = NUMWORD.get(n, str(n))
        prompts = random.sample(PROMPTS, min(len(PROMPTS), n))
        texts = [f"Only a genius can get {word} out of {word}!"]
        for i, q in enumerate(quiz):
            if challenge and i == n - 1:
                texts.append("Challenge round! This one is tough.")
            texts += [q["question"], prompts[i % len(prompts)], q["correct"]]
        texts.append("How many did you get right? Comment your score, and follow for more quizzes!")

        # Narration is recorded while the search terms are planned; then each scene is rendered as soon as its own
        # footage is in, several scenes at a time.
        progress("Recording narration...", 0.08)
        used = UsedSet()
        gate = threading.Lock()
        box = {}
        sfx = {"bing": bing(), "tick": tick(), "pop": pop(), "whoosh": whoosh(), "sparkle": sparkle(), "siren": siren(), "sting": challenge_sting()}
        # one entry per scene, in order: what its background is
        kinds = [("intro", None)]
        for i in range(n):
            if challenge and i == n - 1:
                kinds.append(("challenge", None))
            kinds.append(("q", i))
        kinds.append(("outro", None))

        def get_plans():   # needs the narration (clip lengths), so it waits for it
            with gate:
                if "plans" not in box:
                    clips = box["tts"].result()
                    plans, ci = [_plan_hook(clips[0], n, sfx)], 1
                    for i, q in enumerate(quiz):
                        is_ch = challenge and i == n - 1
                        if is_ch:
                            plans.append(_plan_challenge(clips[ci], sfx))
                            ci += 1
                        plans.append(_plan_question(i, n, q, clips[ci:ci + 3], sfx, is_ch))
                        ci += 3
                    plans.append(_plan_outro(clips[ci], sfx))
                    box["plans"] = plans
                return box["plans"]

        def scene(si):
            kind, i = kinds[si]
            bg = None
            if kind == "intro":
                bg = _intro_background(used)
            elif kind == "q":
                bg, quiz[i]["footage"] = find_background(quiz[i]["video_queries"], used, quiz[i]["question"])
            elif kind == "outro":
                bg = find_background(random.sample(INTRO_QUERIES, 2) + ["abstract background"], used)[0]
            frames, dur, events, has_clip = get_plans()[si]
            render_segment(bg if has_clip else None, frames, dur, job_dir / f"seg_{si:02d}.mp4", job_dir,
                           full=bg if frames[0][1] == "hook" else None, look=look_info)

        with ThreadPoolExecutor(max_workers=1) as tts_pool:
            box["tts"] = tts_pool.submit(synthesize_all, texts, voice)
            progress("Planning the footage searches...", 0.12)
            try:
                refine_queries(quiz)
            except Exception as e:  # never let search-term planning break the video
                print(f"[footage] search planning skipped: {e}", flush=True)
            progress("Finding footage and rendering...", 0.14)
            find_many([(lambda si=si: scene(si)) for si in range(len(kinds))], int(env("FOOTAGE_WORKERS", "5")),
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

        if not custom:
            mark_used(quiz)
        return {
            "look": look["title"],
            "file": name,
            "duration": round(total, 1),
            "questions": [{"question": q["question"], "answer": f"{LETTERS[q['correct_idx']]}. {q['correct']}",
                           "footage": q.get("footage", "")}
                          for q in quiz],
        }
    finally:
        render.reset_skin()
        shutil.rmtree(job_dir, ignore_errors=True)
        cleanup_disk()
