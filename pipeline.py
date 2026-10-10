"""Builds one complete quiz video: questions -> narration -> backgrounds -> scenes -> final mp4."""
import random
import shutil
import time
import uuid

from audio import SR, Mixer, bing, pop, tick
from config import CACHE_DIR, OUTPUT_DIR, WORK_DIR, env
from videos import find_background
from questions import LETTERS, get_questions, mark_used, pick_letters
from render import concat_videos, mux, render_segment
from tts import synthesize_all

NUMWORD = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
INTRO_QUERIES = ["neon lights abstract", "colorful abstract background", "light particles",
                 "glowing lines", "bokeh lights", "abstract waves"]
THINK = int(env("THINK_SECONDS", "5"))


def _plan_title(clip, title, subtitle, pop_clip):
    d = max(2.5, 0.3 + len(clip) / SR + 0.8)
    frames = [(0.0, "title", dict(title=title, subtitle=subtitle))]
    events = [(0.1, pop_clip, 0.3), (0.3, clip, 1.0)]
    return frames, d, events


def _plan_question(i, total, q, clips, sfx):
    """Narration: the question, then (after the countdown) the answer. Choices appear silently."""
    cq, cr = clips
    base = dict(q_num=i + 1, total=total, question=q["question"], choices=q["choices"],
                correct_idx=q["correct_idx"], category=q.get("category", ""), think=THINK, seed=i)
    frames = [(0.0, "quiz", dict(base, visible=0))]
    events = [(0.05, sfx["pop"], 0.3), (0.35, cq, 1.0)]
    t = 0.35 + len(cq) / SR + 0.35
    for k in range(4):                                   # each choice slides in with a pop
        for step, a in enumerate((0.25, 0.6, 1.0)):
            frames.append((t + 0.06 * step, "quiz", dict(base, visible=k + 1, anim=a)))
        events.append((t, sfx["pop"], 0.35))
        t += 0.55
    t += 0.15
    for s_left in range(THINK, 0, -1):                   # smooth countdown ring, 4 frames per second
        events.append((t, sfx["tick"], 0.5))
        for sub in range(4):
            frames.append((t + 0.25 * sub, "quiz", dict(base, visible=4, timer=s_left - 0.25 * sub)))
        t += 1.0
    frames.append((t, "quiz", dict(base, visible=4, reveal=True)))
    events += [(t, sfx["bing"], 0.9), (t + 0.45, cr, 1.0)]
    t += 0.45 + len(cr) / SR + 1.3
    return frames, t, events


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


def build_quiz(n_questions: int = 5, voice: str = "en-US-AriaNeural", progress=lambda msg, frac: None) -> dict:
    job_dir = WORK_DIR / uuid.uuid4().hex[:8]
    job_dir.mkdir(parents=True)
    try:
        progress("Picking questions...", 0.03)
        raw = get_questions(n_questions)
        quiz = []
        for q, ci in zip(raw, pick_letters(n_questions)):
            others = list(q["wrong"][:3])
            random.shuffle(others)
            quiz.append({**q, "choices": others[:ci] + [q["correct"]] + others[ci:], "correct_idx": ci})

        word = NUMWORD.get(n_questions, str(n_questions))
        texts = [f"Can you get all {word} questions right? Let's find out!"]
        for i, q in enumerate(quiz):
            texts.append(f"Question {i + 1}. {q['question']}")
            texts.append(f"The answer is {LETTERS[q['correct_idx']]}. {q['correct']}.")
        texts.append("How many did you get right? Comment your score, and follow for more quizzes!")

        progress("Recording narration...", 0.08)
        clips = synthesize_all(texts, voice)

        used, bgs = set(), []
        progress("Finding background videos...", 0.14)
        bgs.append(find_background(random.sample(INTRO_QUERIES, 2) + ["abstract background"], used)[0])
        for i, q in enumerate(quiz):
            progress(f"Finding video for question {i + 1} of {n_questions}...", 0.14 + 0.24 * i / n_questions)
            path, matched = find_background(q["video_queries"], used)
            q["footage"] = matched
            bgs.append(path)
        bgs.append(find_background(random.sample(INTRO_QUERIES, 2) + ["abstract background"], used)[0])

        sfx = {"bing": bing(), "tick": tick(), "pop": pop()}
        plans = [_plan_title(clips[0], f"CAN YOU GET {n_questions}/{n_questions}?", "Trivia Quiz Challenge", sfx["pop"])]
        for i, q in enumerate(quiz):
            plans.append(_plan_question(i, n_questions, q, clips[1 + i * 2: 3 + i * 2], sfx))
        plans.append(_plan_title(clips[-1], "HOW DID YOU DO?", "Comment your score & follow for more!", sfx["pop"]))

        total = sum(p[1] for p in plans)
        mixer, seg_paths, offset = Mixer(total), [], 0.0
        for si, ((frames, dur, events), bg) in enumerate(zip(plans, bgs)):
            progress(f"Rendering scene {si + 1} of {len(plans)}...", 0.40 + 0.48 * si / len(plans))
            seg = job_dir / f"seg_{si:02d}.mp4"
            render_segment(bg, frames, dur, seg, job_dir)
            seg_paths.append(seg)
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

        mark_used(quiz)
        return {
            "file": name,
            "duration": round(total, 1),
            "questions": [{"question": q["question"], "answer": f"{LETTERS[q['correct_idx']]}. {q['correct']}",
                           "footage": q.get("footage", "")}
                          for q in quiz],
        }
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)
        cleanup_disk()
