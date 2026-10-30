"""Builds one complete quiz video: questions -> narration -> backgrounds -> scenes -> final mp4."""
import random
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from audio import Mixer, SR, bing, challenge_sting, count_sfx, effects, pop, siren, sparkle, tick, whoosh
from chalkboard import ensure_chalkboard
from config import ASSETS_DIR, CACHE_DIR, OUTPUT_DIR, WORK_DIR, env, flog
from videos import UsedSet, find_background, find_many
from questions import LETTERS, get_hard_question, get_questions, keywords_from, mark_used, pick_letters
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
FRAME_RATE = 30
FRAME = 1 / FRAME_RATE   # one video frame. Pop-ins step in whole frames, so every frame of the motion is different and none is shown twice


def pop_curve(start=0.55, n=8, c1=2.6):
    """Sizes for a pop-in: grows from `start`, overshoots a little, settles at exactly 1.0 (an ease-out-back curve)."""
    c3 = c1 + 1
    out = []
    for k in range(n - 1):
        x = k / (n - 1) - 1
        out.append(round(start + (1 - start) * (1 + c3 * x ** 3 + c1 * x ** 2), 4))
    return tuple(out) + (1.0,)


POP_ANIM = pop_curve(0.55, 8)   # an answer choice popping in (size and fade together)


def pop_in(t, kind, args, start=0.8, n=7):
    """Frames for a whole graphic popping in at time t: one picture per video frame, ending at its normal size."""
    return [(round(t + k * FRAME, 4), kind, dict(args, hscale=v)) for k, v in enumerate(pop_curve(start, n))]


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
    frames[:] = [f for f in frames if not (f[0] >= t and key in f[2])]   # a pop that starts before the last one has finished takes over from it
    for k, a in enumerate(POP_ANIM):
        frames.append((round(t + FRAME * k, 4), "scene", dict(base, **{key: a})))


def _plan_hook(clip, n, sfx):
    """Chalkboard intro. The word being read is highlighted pink, moving along with the voice."""
    w = NUMWORD.get(n, str(n))
    words = ["ONLY", "A", "GENIUS", "CAN", "GET", f"{n}/{n}"]
    spoken = ["only", "a", "genius", "can", "get", f"{w} out of {w}"]
    weights = [len(x) + 1 for x in spoken]
    text = " ".join(words)
    frames = pop_in(0.0, "hook", dict(text=text, hl=-1), start=0.7)
    t0, dur = 0.4, len(clip) / SR
    acc = 0.0
    for k, wt in enumerate(weights):
        frames.append((t0 + dur * acc / sum(weights), "hook", dict(text=text, hl=k, hscale=1.0)))
        acc += wt
    frames.append((t0 + dur, "hook", dict(text=text, hl=-1, hscale=1.0)))
    events = [(0.0, sfx["whoosh"], 1.0), (0.05, sfx["pop"], 1.0), (t0, clip, 1.0)]
    return frames, t0 + dur + 0.9, events, False


def _plan_challenge(clip, sfx):
    """Slam-in title card: riser, two hits (CHALLENGE, ROUND), then the narrator. A new picture for every video frame (30 per
    second); it used to step at 24 and then 15 per second, which does not divide evenly into 30 and so moved unevenly."""
    dur = max(3.4, 1.25 + len(clip) / SR + 0.45)
    times = [round(k / FRAME_RATE, 4) for k in range(int(dur * FRAME_RATE) + 1) if k / FRAME_RATE < dur]
    frames = [(t, "challenge", dict(t=t, dur=dur)) for t in times]
    events = [(0.0, sfx["sting"], 1.0), (0.0, sfx["whoosh"], 1.0), (1.25, clip, 1.0)]
    return frames, dur, events, False


GAP = render.frame_ceil(float(env("TRANSITION_SECONDS", "1.0")))   # between two scenes only the text is gone for this long (the whoosh starts it); the same for every video type
PAUSE_AFTER = float(env("PAUSE_AFTER_SECONDS", "1.5"))   # seconds from the narrator finishing the answer until the whoosh; the same for every video type


def pause_after(frames, events, pause: float = PAUSE_AFTER) -> float:
    """The scene's length when it must end `pause` seconds after the last sound (never before its last picture has settled)."""
    audio_end = max((t + len(c) / SR for t, c, _ in events), default=0.0)
    last_frame = max((f[0] for f in frames), default=0.0)
    return max(audio_end + pause, last_frame + 0.6)


def _plan_question(i, total, q, clips, sfx, challenge=False):
    """Question read aloud, choices pop in (pop sound each), short prompt, countdown, then ONLY the answer."""
    cq, cp, cr = clips
    theme = "red" if challenge else "purple"
    base = dict(theme=theme, q_num=i + 1, header=q["question"], choices=q["choices"], correct_idx=q["correct_idx"],
                label=f"QUESTION {i + 1}/{total}", think=THINK)
    frames = pop_in(0.0, "scene", dict(base, visible=0))
    events = [(0.0, sfx["whoosh"], 1.0), (0.05, sfx["pop"], 1.0), (0.4, cq, 1.0)]
    t = 0.4 + len(cq) / SR + 0.3
    for k in range(len(q["choices"])):
        _pops(frames, t, dict(base, visible=k + 1))
        events.append((t, sfx["pop"], 1.0))
        t += 0.5
    t += 0.1
    events.append((t, cp, 1.0))
    for s_left in range(THINK, 0, -1):
        events.append((t, count_sfx(sfx, s_left), 1.0))
        frames.append((t, "scene", dict(base, visible=len(q["choices"]), timer=s_left, smooth=True)))   # the bar itself is drawn smoothly by ffmpeg
        t += 1.0
    full = dict(base, visible=len(q["choices"]), reveal=True)
    frames.append((t, "scene", full))
    events += [(t, sfx["bing"], 1.0), (t + 0.05, sfx["sparkle"], 1.0), (t + 0.5, cr, 1.0)]
    t += 0.5 + len(cr) / SR + 1.2
    return frames, t, events, True


def _plan_outro(clip, sfx):
    base = dict(theme="purple", header="How did you do?", num_label=False, label="COMMENT YOUR SCORE",
                letters="SAB", choices=["All correct: Quiz Master", "Most correct: Sharp Mind", "Few correct: Keep Trying"])
    frames = pop_in(0.0, "scene", dict(base, lit=0))
    events = [(0.0, sfx["whoosh"], 1.0), (0.05, sfx["pop"], 1.0), (0.4, clip, 1.0)]
    dur = 0.4 + len(clip) / SR + 1.0
    for k in range(3):
        t = 0.9 + 0.6 * k
        _pops(frames, t, dict(base, lit=3, visible=k + 1))
        events.append((t, sfx["pop"], 1.0))
    frames.sort(key=lambda f: f[0])
    return frames, max(dur, 3.0), events, True


def cleanup_disk() -> None:
    """Keep disk use small: clear downloaded stock clips (old finished videos are trimmed by app.py, see MAX_KEEP_VIDEOS)."""
    if env("KEEP_CACHE") != "1":
        for f in CACHE_DIR.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass


def build_quiz(n_questions: int = 5, voice: str = "en-US-AriaNeural", progress=lambda msg, frac: None,
               categories=None, watermark: str = "", style: str = looks.DEFAULT, custom=None, colors=None,
               timer_sound: str = "ticks", pop_sound: str = "pop", mix=None) -> dict:
    """custom = the person's own questions: [{"question", "choices", "correct_idx"}]. colors = their colour changes."""
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
            if challenge:   # the last question is the challenge round: swap it for a hard one
                hard = get_hard_question(categories, [q["question"] for q in quiz])
                if hard:
                    others = list(hard["wrong"][:3])
                    random.shuffle(others)
                    ci = quiz[-1]["correct_idx"]
                    quiz[-1] = {**hard, "choices": others[:ci] + [hard["correct"]] + others[ci:], "correct_idx": ci}
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
        sfx = effects(timer_sound, pop_sound)
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
                        qf, qd, qe, qh = _plan_question(i, n, q, clips[ci:ci + 3], sfx, is_ch)
                        plans.append((qf, pause_after(qf, qe), qe, qh))
                        ci += 3
                    plans.append(_plan_outro(clips[ci], sfx))
                    # every scene is a whole number of video frames long, so the audio placed by adding the lengths stays in step
                    box["plans"] = [(f, render.frame_ceil(d), e, h) for f, d, e, h in plans]
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
            full_bg = bg if frames[0][1] == "hook" else None
            render_segment(bg if has_clip else None, frames, dur, job_dir / f"seg_{si:02d}.mp4", job_dir,
                           full=full_bg, look=look_info)
            if si < len(kinds) - 1:   # everything leaves the screen for a moment: just the background, while the whoosh plays
                render_segment(bg if has_clip else None, [(0.0, "empty", {})], GAP, job_dir / f"gap_{si:02d}.mp4", job_dir,
                               full=full_bg, look=look_info, hide_clip=True,   # the full-screen intro video stays and carries on; only its text leaves
                               skip=render.frames_for(dur) / render.FPS)

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
        t_scenes = time.time()
        total = sum(p[1] for p in plans) + GAP * (len(plans) - 1)
        mixer, seg_paths, offset = Mixer(total), [], 0.0
        for si, (frames, dur, events, has_clip) in enumerate(plans):
            seg_paths.append(job_dir / f"seg_{si:02d}.mp4")
            for t, clip, gain in events:
                if clip is sfx["whoosh"] and t == 0.0:   # the scene-change whoosh plays in the gap instead (below)
                    continue
                mixer.add(offset + t, clip, gain)
            offset += dur
            if si < len(plans) - 1:
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

        if not custom:
            mark_used(quiz)
        flog(f"[timing] trivia: narration, footage and scenes {t_scenes - t_begin:.0f}s | mixing and finishing "
             f"{time.time() - t_scenes:.0f}s | total {time.time() - t_begin:.0f}s for a {total:.0f}s video")
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
