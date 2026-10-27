"""Audio helpers: decoding, mixing, and the synthesized sound effects (bing, tick, pop)."""
import subprocess
import wave

import numpy as np

from config import ASSETS_DIR, CACHE_DIR, env, ffmpeg_exe

SR = 44100
CEILING = 0.95      # the loudest moment of a finished video sits here (just under clipping)
TARGET_RMS = 0.25   # the average level every finished video is brought to, whatever its type (was 0.2: a bit over 3 dB louder)
MAX_BOOST = 5.0     # never lift a mix by more than this
KNEE = 0.7          # above this a peak is eased down (see finish) instead of cutting off
MASTER_VOLUME = float(env("MASTER_VOLUME", "0.72"))   # the whole mix, after everything else (0.72 = 28% quieter than the raw mix)
VOICE_GAIN = 1.275   # the narrator, relative to the sound effects
# How loud the sound effects are, in ONE place so every video type has the same levels. Every effect peaks at the same level
# as the timer tick, so none of them is louder or quieter than another. A long, steady sound (the siren) is also held to a
# maximum average level, otherwise being as tall as a click would make it drown the narrator.
EFFECT_PEAK = 0.68
EFFECT_MAX_RMS = 0.16
POP_PEAK = 0.7   # the classic pop, at a comfortable level (the Mix lever turns it up or down)
OTHER_POP_TRIM = 0.55   # the other choice sounds are brighter, so they sit lower than the classic pop
BING_GAIN = 0.5   # the ding, turned up well past the other effects
WHOOSH_GAIN = 1.0   # the scene-change whoosh, turned up so it is clearly heard
BEEP_TRIM = 0.9  # the last-three-seconds notes, a little above the ticks so the end is noticed
TIMER_BOOST = 2.2    # the ticks, louder
END_NOTES = 0.42     # the last three notes, back down a little from the ticks
TICK_TRIM = 0.6   # the timer tick a little lower than the other effects (the original level)


def decode_audio(path) -> np.ndarray:
    """Any audio file -> mono float32 at 44.1 kHz."""
    cmd = [ffmpeg_exe(), "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("Could not decode audio: " + p.stderr.decode(errors="ignore")[-500:])
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0

VOICE_FILTER = ("highpass=f=75,equalizer=f=3400:t=q:w=1.2:g=2,treble=g=2.5:f=8000,"
                "alimiter=limit=0.95:attack=2:release=40,aresample=resampler=soxr:precision=28")


def decode_voice(path) -> np.ndarray:
    """Narration -> mono float32 at 44.1 kHz, with a little clarity added. The Microsoft voices arrive as a 24 kHz, 48 kbit/s mp3,
    which sounds a bit dull and boxy; this lifts the speech presence and the top end gently, removes rumble, and resamples with the
    high-quality (soxr) resampler. Falls back to plain decoding if the filter can't run."""
    cmd = [ffmpeg_exe(), "-v", "error", "-i", str(path), "-af", VOICE_FILTER, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0 or not p.stdout:
        return decode_audio(path)
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0



def trim_silence(a: np.ndarray, thr: float = 0.012, pad: float = 0.04) -> np.ndarray:
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx) == 0:
        return a
    s = max(0, idx[0] - int(pad * SR))
    e = min(len(a), idx[-1] + int(pad * SR))
    return a[s:e]


class Tagged(np.ndarray):
    """A sound that knows which Mix lever it belongs to (narrator, pop, ding, whoosh, timer), so the Mixer can keep the levers apart."""
    group = None

    def __array_finalize__(self, obj):
        self.group = getattr(obj, "group", None)


def tag(a: np.ndarray, group: str) -> np.ndarray:
    t = np.asarray(a, dtype=np.float32).view(Tagged)
    t.group = group
    return t


class Mixer:
    """Collects every sound of a video, one track per Mix lever, then mixes them down in one go (see mix_down)."""

    def __init__(self, seconds: float):
        self.n = int(seconds * SR) + SR
        self.tracks: dict = {}

    def add(self, at: float, clip: np.ndarray, gain: float = 1.0) -> None:
        s = int(at * SR)
        if s < 0 or s >= self.n:
            return
        g = getattr(clip, "group", None) or "other"
        buf = self.tracks.get(g)
        if buf is None:
            buf = self.tracks[g] = np.zeros(self.n, dtype=np.float32)
        e = min(self.n, s + len(clip))
        buf[s:e] += np.asarray(clip[: e - s]) * gain

    def mix_down(self, seconds: float, mix=None) -> np.ndarray:
        return mix_down({k: v[: int(seconds * SR)] for k, v in self.tracks.items()}, mix)

    def save(self, path, seconds: float, mix=None) -> None:
        a = self.mix_down(seconds, mix)
        pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16)
        stereo = np.repeat(pcm[:, None], 2, axis=1)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(stereo.tobytes())


FIT_PEAK = float(env("FIT_PEAK", "0.55"))   # the loudest ordinary peak of a finished video (rare, sharper peaks go past it and are limited)


def mix_down(tracks: dict, mix=None) -> np.ndarray:
    """The final mix. Every Mix lever really moves its own sound: the sounds are scaled by the levers, and then the whole video is
    fitted to the loudness ceiling with ONE gain, so a lever never fights an automatic leveler or a limiter that flattens the loud
    parts. The loudness of a video comes from its recommended mix, so at the recommended levers it sounds like it always has. Raising
    a lever past the ceiling turns the other sounds down by the same amount (the balance still moves exactly as shown); the Overall
    lever moves the whole mix; a clean limiter catches only the rare sharpest peaks."""
    if not tracks:
        return np.zeros(0, dtype=np.float32)
    n = max(len(v) for v in tracks.values())
    lv = mix_levels(mix)
    rec = mix_levels(None)
    ref = np.zeros(n, dtype=np.float32)
    for k, v in tracks.items():
        ref[: len(v)] += v * rec.get(k, 1.0)
    peak = float(np.max(np.abs(ref)))
    if peak <= 0:
        return ref
    active = ref[np.abs(ref) > 0.01]
    rms = float(np.sqrt(np.mean(active ** 2))) if len(active) else 0.0
    gain = min(TARGET_RMS / rms if rms > 0 else CEILING / peak, MAX_BOOST)
    lev = np.zeros(n, dtype=np.float32)
    for k, v in tracks.items():
        lev[: len(v)] += v * lv.get(k, 1.0) * gain
    hi = float(np.percentile(np.abs(lev), 99.95))   # the ordinary loudest level, not the one sharpest click
    fit = min(1.0, FIT_PEAK / hi) if hi > 0 else 1.0
    out = lev * fit * lv["master"]
    return _limit(out).astype(np.float32)


def finish(a: np.ndarray, master: float = 1.0) -> np.ndarray:
    """Final loudness: ONE volume change applied to the whole mix, so the balance between the narrator, the ticking, the
    pops and the ding is exactly what EFFECT_PEAK and VOICE_GAIN say, in every video type. The mix is brought up toward a
    target average level but never past the point where its loudest moment would clip, so nothing is distorted."""
    peak = float(np.max(np.abs(a))) if len(a) else 0.0
    if peak <= 0:
        return a
    active = a[np.abs(a) > 0.01]
    rms = float(np.sqrt(np.mean(active ** 2))) if len(active) else 0.0
    # The volume follows the average level, not the single loudest sound: a short pop used to set the limit and hold the whole
    # video down. Peaks above the knee are eased down smoothly (a soft limiter) so they never clip.
    gain = TARGET_RMS / rms if rms > 0 else CEILING / peak
    y = (a * min(gain, MAX_BOOST) * master).astype(np.float32)   # `master` = the person's Overall slider, applied before the limiter
    y = _limit(y)
    return (y * MASTER_VOLUME).astype(np.float32)


def _limit(y: np.ndarray, ceiling: float = CEILING, radius: int = 1100) -> np.ndarray:
    """A clean peak limiter. Instead of bending the waveform (which sounds like static on a loud moment), it turns the whole mix
    down smoothly around any peak that would pass the ceiling, then lets it back up, so the sound itself stays undistorted."""
    ay = np.abs(y)
    if not len(y) or float(ay.max()) <= ceiling:
        return y
    need = np.ones(len(y), dtype=np.float32)
    hot = ay > ceiling
    need[hot] = ceiling / ay[hot]
    m = need
    span = 1
    while span < 2 * radius + 1:   # hold the lowest gain over a window (running minimum, in log steps)
        step = min(span, 2 * radius + 1 - span)
        sh = np.concatenate([m[step:], np.ones(step, dtype=np.float32)])
        m = np.minimum(m, sh)
        span += step
    m = np.concatenate([np.ones(radius, dtype=np.float32), m])[: len(y)]   # centre the window
    # smooth the gain with a moving average, so there are no clicks
    n = 2 * radius + 1
    pad = np.concatenate([np.ones(radius, dtype=np.float32), m, np.ones(radius, dtype=np.float32)])
    c = np.cumsum(np.concatenate([[0.0], pad]), dtype=np.float64)
    g = ((c[n:] - c[:-n]) / n).astype(np.float32)[: len(y)]
    return (y * np.minimum(g, 1.0)).astype(np.float32)


def _tones(parts, dur, decay, attack=0.002) -> np.ndarray:
    t = np.arange(int(SR * dur)) / SR
    s = sum(amp * np.sin(2 * np.pi * f * t) for f, amp in parts)
    env = np.exp(-decay * t) * np.minimum(1.0, t / attack)
    return (s * env).astype(np.float32)


def _override(name: str):
    """Drop assets/bing.wav or tick.wav (or .mp3/.ogg) into the assets folder to use your own sound."""
    for ext in ("wav", "mp3", "ogg"):
        p = ASSETS_DIR / f"{name}.{ext}"
        if p.exists():
            a = decode_audio(p)
            peak = float(np.max(np.abs(a))) or 1.0
            return a / peak * 0.8
    return None


def bing() -> np.ndarray:
    custom = _override("bing")
    if custom is not None:
        return custom
    # a soft glass-bell chime: a lower, rounder pitch (E6) with real bell partials, each decaying at its own rate,
    # a gentle attack (no click) and a short airy tail, then a light low-pass so nothing is shrill
    f = 1318.51
    dur = 2.0
    t = np.arange(int(SR * dur)) / SR
    partials = [(1.0, 1.0, 2.6), (2.0, 0.42, 3.6), (2.76, 0.22, 5.0), (4.07, 0.10, 7.5), (5.4, 0.05, 10.0)]
    y = sum(amp * np.sin(2 * np.pi * f * r * t + 0.3 * r) * np.exp(-dec * t) for r, amp, dec in partials)
    y = y * np.minimum(1.0, t / 0.006)
    # a soft octave shimmer underneath makes it sound full instead of thin
    y = y + 0.28 * np.sin(2 * np.pi * (f / 2) * t) * np.exp(-3.2 * t) * np.minimum(1.0, t / 0.01)
    tail = np.zeros_like(y)
    for d, g in ((0.045, 0.30), (0.097, 0.20), (0.161, 0.12), (0.233, 0.07)):
        k = int(SR * d)
        tail[k:] += g * y[:-k]
    y = (y + tail).astype(np.float32)
    alpha = 0.55   # one-pole low-pass, takes the edge off the top
    out = np.empty_like(y)
    acc = 0.0
    for i in range(len(y)):
        acc += alpha * (y[i] - acc)
        out[i] = acc
    fade = np.minimum(1.0, (dur - t) / 0.15)
    out = out * fade
    return (out / float(np.max(np.abs(out))) * 0.8).astype(np.float32)


def _click(rng, modes, ring, body=0.0, body_f=190.0, dur=0.09) -> np.ndarray:
    """One mechanical click: a hard 'tk' of filtered noise followed by a short wooden/metal ring."""
    n = int(SR * dur)
    t = np.arange(n) / SR
    noise = np.diff(rng.standard_normal(n + 1)).astype(np.float32)   # differenced noise = bright, no rumble
    tk = noise * np.exp(-900 * t)
    tone = sum(a * np.sin(2 * np.pi * f * t) for f, a in modes) * np.exp(-ring * t)
    thump = body * np.sin(2 * np.pi * body_f * t) * np.exp(-70 * t)
    out = (0.55 * tk + 0.5 * tone + thump).astype(np.float32)
    out *= np.minimum(1.0, t / 0.0004)
    return out / (float(np.max(np.abs(out))) or 1.0)


def _soft_click(freq, ring, noise_amt=0.25, dur=0.12, seed=1) -> np.ndarray:
    """A rounded clock 'tock': a short wooden knock (a low sine with a quick decay) plus a very soft, dull puff of noise.
    No bright hiss, so it stays pleasant when it repeats for many seconds."""
    rng = np.random.default_rng(seed)
    n = int(SR * dur)
    t = np.arange(n) / SR
    tone = (np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * freq * 2.4 * t) * np.exp(-60 * t)) * np.exp(-ring * t)
    noise = rng.standard_normal(n).astype(np.float32)
    y, lp = 0.0, np.zeros(n, dtype=np.float32)
    for i in range(n):   # one-pole low-pass: takes the hiss out of the noise
        y += 0.12 * (noise[i] - y)
        lp[i] = y
    out = tone + noise_amt * lp * 6 * np.exp(-250 * t)
    out *= np.minimum(1.0, t / 0.0008)   # a hair of attack so it does not click
    return (out / (float(np.max(np.abs(out))) or 1.0)).astype(np.float32)


def _room(x: np.ndarray, wet=0.35, tail=0.45, seed=11) -> np.ndarray:
    """A small amount of room echo, so a sound is not bone dry (a dry click sounds like a car indicator)."""
    rng = np.random.default_rng(seed)
    n = int(SR * tail)
    t = np.arange(n) / SR
    ir = rng.standard_normal(n) * np.exp(-9 * t)
    ir[:int(0.004 * SR)] *= 0.2
    ir /= np.sqrt(np.sum(ir ** 2)) or 1.0
    size = len(x) + n
    y = np.fft.irfft(np.fft.rfft(x, size * 2) * np.fft.rfft(ir, size * 2))[:size]
    y = x.sum() * 0 + (np.pad(x, (0, size - len(x))) + wet * y)
    return y.astype(np.float32)


def _mallet(freq, dur=0.34, ring=11.0) -> np.ndarray:
    """A soft wooden mallet note (marimba-like): a warm tone, a quiet upper partial, a gentle attack."""
    n = int(SR * dur)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * freq * t) * np.exp(-ring * t) + 0.22 * np.sin(2 * np.pi * freq * 4.0 * t) * np.exp(-38 * t) \
        + 0.1 * np.sin(2 * np.pi * freq * 9.2 * t) * np.exp(-70 * t)
    x *= np.minimum(1.0, t / 0.003)
    return (x / (float(np.max(np.abs(x))) or 1.0)).astype(np.float32)


def _blup(f0: float) -> np.ndarray:
    """One soft, bubbly note (the same family as the pop): a quick upward glide that dies away fast."""
    n = int(SR * 0.11)
    t = np.arange(n) / SR
    ph = 2 * np.pi * (f0 * t + (0.55 * f0 / (2 * 0.11)) * t ** 2)
    x = (np.sin(ph) + 0.18 * np.sin(2 * ph)) * np.exp(-26 * t) * np.minimum(1.0, t / 0.004)
    return (x / float(np.max(np.abs(x)))).astype(np.float32)


def _kick(f_hi=180.0, f_lo=85.0, dur=0.14) -> np.ndarray:
    """A soft low drum: a quick downward glide, with a short knock on top so small phone speakers still play it."""
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = f_lo + (f_hi - f_lo) * np.exp(-34 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-20 * t) + 0.25 * np.sin(2 * np.pi * 330 * t) * np.exp(-60 * t)
    x *= np.minimum(1.0, t / 0.002)
    return (x / float(np.max(np.abs(x)))).astype(np.float32)


def _hat(seed=0, dur=0.05) -> np.ndarray:
    """A tiny closed hi-hat: bright noise that stops almost at once."""
    rng = np.random.default_rng(100 + seed)
    n = int(SR * dur)
    t = np.arange(n) / SR
    x = np.diff(rng.standard_normal(n + 1)) * np.exp(-90 * t)
    x = np.diff(np.concatenate([[0.0], x]))              # a second difference: more air, less body
    return (x / float(np.max(np.abs(x)))).astype(np.float32)


def _snare(dur=0.16) -> np.ndarray:
    """A soft snare: a short noise burst with a low body, tucked back so it does not clatter."""
    rng = np.random.default_rng(31)
    n = int(SR * dur)
    t = np.arange(n) / SR
    noise = np.diff(rng.standard_normal(n + 1)) * np.exp(-26 * t)
    body = np.sin(2 * np.pi * 185 * t) * np.exp(-30 * t)
    x = 0.8 * noise / (float(np.max(np.abs(noise))) or 1.0) + 0.6 * body
    x *= np.minimum(1.0, t / 0.0015)
    return (x / float(np.max(np.abs(x)))).astype(np.float32)


def _beat(s: int) -> np.ndarray:
    """A steady groove, 120 beats a minute, so each second is half a bar and the seconds join into a two-second loop:
    kick on the first beat, snare on the second; the other half adds a kick on the off-beat. The hi-hat gets busier as
    the countdown runs down (off-beats, then eights, then sixteenths), so it drives towards the last three notes."""
    out = np.zeros(SR + SR // 4, dtype=np.float32)
    kick, snare = _kick(), _snare()

    def put(x, at, gain):
        st = int(at * SR)
        out[st:st + len(x)] += x * gain

    put(kick, 0.0, 1.0)
    put(snare, 0.5, 0.55)
    if s % 2 == 0:                                          # the second half of the bar
        put(kick, 0.25, 0.8)
    grid = [0.25, 0.75] if s >= 7 else [0.0, 0.25, 0.5, 0.75] if s >= 5 else [i * 0.125 for i in range(8)]
    for i, tt in enumerate(grid):
        on_beat = abs(tt * 2 - round(tt * 2)) < 1e-6
        put(_hat(i % 3), tt, 0.16 if on_beat else 0.26)
    out = _room(out, wet=0.1, tail=0.22)
    res = out[:SR].copy()
    res[:len(out) - SR] += out[SR:]
    return res.astype(np.float32)


def _ktick(seed: int, ring_hz: float) -> np.ndarray:
    """The hi-hat burst with a tiny ring of metal and plastic on it (option B)."""
    rng = np.random.default_rng(300 + seed)
    n = int(SR * 0.045)
    t = np.arange(n) / SR
    x = np.diff(rng.standard_normal(n + 1)) * np.exp(-110 * t)
    x = np.diff(np.concatenate([[0.0], x]))
    x = x / (float(np.max(np.abs(x))) or 1.0)
    ring = (np.sin(2 * np.pi * ring_hz * t) + 0.5 * np.sin(2 * np.pi * ring_hz * 1.51 * t)) * np.exp(-85 * t)
    y = 0.8 * x + 0.35 * ring
    y *= np.minimum(1.0, t / 0.0006)
    return (y / (float(np.max(np.abs(y))) or 1.0)).astype(np.float32)


def _kitchen(rate_override=None) -> np.ndarray:
    """The countdown tick, made of the hi-hat from the beat: soft, airy hits spaced evenly, no drum. Every hit is a different
    take of the noise (as in the beat), so it does not click the same way over and over like a lighter would.
    TICK_STYLE=ring gives the alternating hat-with-a-ring version instead."""
    rate = max(2, int(rate_override or env("TICK_RATE", "5")))   # ticks per second
    ring = env("TICK_STYLE", "hats") == "ring"
    hats = [_hat(i) for i in range(1, 9)]
    a, b = _ktick(1, 3300.0), _ktick(2, 2600.0)
    out = np.zeros(SR + SR // 4, dtype=np.float32)
    for k in range(rate):
        st = int(k * SR / rate)
        c = (a if k % 2 == 0 else b * 0.85) if ring else hats[k % len(hats)] * (0.9 if k % 2 else 1.0)
        out[st:st + len(c)] += c
    out = _room(out, wet=0.1, tail=0.2)
    res = out[:SR].copy()
    res[:len(out) - SR] += out[SR:]
    return res.astype(np.float32)


def tick_original() -> np.ndarray:
    """The countdown tick the app started with: one second of a wind-up kitchen timer, four mechanical clicks alternating a higher
    'tick' and a lower 'tock'."""
    rng = np.random.default_rng(5)
    hi = _click(rng, [(2350, 1.0), (3600, 0.5)], 150, body=0.35)
    lo = _click(rng, [(1650, 1.0), (2700, 0.45)], 130, body=0.5, body_f=150.0)
    out = np.zeros(SR, dtype=np.float32)
    for k in range(4):
        c = (hi if k % 2 == 0 else lo) * (0.95 if k % 2 == 0 else 0.8)
        st = int(k * 0.25 * SR)
        out[st:st + len(c)] += c
    return out * 0.6


def _thump() -> np.ndarray:
    """One soft, low heartbeat-like thump: felt more than heard, never a click."""
    n = int(SR * 0.28)
    t = np.arange(n) / SR
    f = 105 + 95 * np.exp(-28 * t)                       # glides down from ~200 Hz to ~105 Hz
    ph = 2 * np.pi * np.cumsum(f) / SR
    th = (np.sin(ph) + 0.28 * np.sin(2 * ph)) * np.exp(-17 * t) * np.minimum(1.0, t / 0.006)
    th = (th / float(np.max(np.abs(th)))).astype(np.float32)
    out = np.zeros(SR, dtype=np.float32)
    out[:n] += th
    out = _room(out, wet=0.18, tail=0.3)
    res = out[:SR].copy()
    res[:len(out) - SR] += out[SR:]
    return res.astype(np.float32)


def _bubbles(s: int) -> np.ndarray:
    """Soft bubbly notes: they climb a semitone every second and come quicker near the end (2, then 3, then 4 a second)."""
    f0 = 523.25 * 2 ** (-(s - 3) / 12)
    rate = 2 if s >= 7 else 3 if s >= 5 else 4
    note = _blup(f0)
    out = np.zeros(SR + SR // 4, dtype=np.float32)
    for k in range(rate):
        st = int(k * SR / rate)
        out[st:st + len(note)] += note
    out = _room(out, wet=0.12, tail=0.25)
    res = out[:SR].copy()
    res[:len(out) - SR] += out[SR:]
    return res.astype(np.float32)


# The timer sounds the person can pick: (id, name, description, tick level, level of the last-three-seconds notes).
# The last three notes are off by default (COUNTDOWN_BEEPS=1 in .env brings them back); the ticking runs to the end, then the ding.
TIMER_SOUNDS = [
    ("ticks", "Classic kitchen timer", "A real ticking timer, four ticks a second", 0.6, 0.9),
    ("classic", "Turn signal", "Dry mechanical clicking, four clicks a second", 0.6, 0.9),
    ("hihat", "Hi-hat ticks", "Soft, airy ticks, three a second", 0.6, 1.25),
    ("bubbles", "Bubble notes", "Soft bubbly notes that climb and speed up", 0.6, 0.9),
    ("beat", "Drum beat", "A soft drum and hi-hat groove that builds up", 0.6, 0.9),
    ("heartbeat", "Heartbeat", "One low thump a second", 0.6, 0.9),
    ("none", "No ticking", "A silent countdown", 0.0, 0.9),
]
TIMER_IDS = [t[0] for t in TIMER_SOUNDS]


_REAL: dict = {}


def _real_slice(s: int):
    """One second of the recorded ticking timer (assets/timer_ticks.mp3): exactly four ticks, stretched a hair so they land on the
    second. Each countdown second uses a different slice of the recording so it sounds like a real clock, not a loop."""
    if "slices" not in _REAL:
        slices = []
        p = next((ASSETS_DIR / f"timer_ticks.{e}" for e in ("mp3", "wav", "ogg") if (ASSETS_DIR / f"timer_ticks.{e}").exists()), None)
        if p:
            try:
                a = decode_audio(p)[: SR * 14]
                w = max(1, int(SR * 0.005))
                env = np.convolve(np.abs(a), np.ones(w) / w, "same")
                thr = float(env.max()) * 0.25
                on = []
                for i in np.flatnonzero((env[1:] > thr) & (env[:-1] <= thr)) + 1:
                    if not on or i - on[-1] > SR * 0.08:
                        on.append(int(i))
                pre, i = int(0.015 * SR), 0
                while i + 4 < len(on) and len(slices) < 8:
                    d = np.diff(on[i:i + 5]) / SR
                    if d.min() > 0.2 and d.max() < 0.3:
                        sl = a[max(0, on[i] - pre): on[i + 4] - pre]
                        sl = np.interp(np.linspace(0, len(sl) - 1, SR), np.arange(len(sl)), sl).astype(np.float32)
                        f = int(0.004 * SR)
                        sl[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
                        slices.append(sl)
                        i += 4
                    else:
                        i += 1
            except Exception:
                slices = []
        _REAL["slices"] = slices
    sl = _REAL["slices"]
    return sl[(s - 1) % len(sl)] if sl else None


def tick_at(s_left: int, style: str = "ticks") -> np.ndarray:
    """One second of the countdown, in the chosen sound, for `s_left` seconds still to go. A tick.wav dropped into the assets
    folder replaces every style."""
    custom = _override("tick")
    if custom is not None:
        return custom
    s = max(1, min(int(s_left), 12))
    if style == "ticks":
        real = _real_slice(s)
        return real if real is not None else tick_original()
    if style == "hihat":
        return _kitchen(3)
    if style == "bubbles":
        return _bubbles(s)
    if style == "beat":
        return _beat(s)
    if style == "heartbeat":
        return _thump()
    if style == "none":
        return np.zeros(SR, dtype=np.float32)
    return tick_original()


def tick() -> np.ndarray:
    return tick_original()


def beep(freq: float) -> np.ndarray:
    """The last-seconds beep: one clean, clear bell-like note per second, rising 3 - 2 - 1 (E, G, B). The ding follows it."""
    n = int(SR * 0.32)
    t = np.arange(n) / SR
    x = (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * 2 * freq * t) * np.exp(-14 * t)) * np.exp(-9 * t)
    x *= np.minimum(1.0, t / 0.004)
    out = np.zeros(SR + SR // 4, dtype=np.float32)
    out[:n] = x / float(np.max(np.abs(x)))
    out = _room(out, wet=0.15, tail=0.3)
    res = out[:SR].copy()
    res[:len(out) - SR] += out[SR:]
    return res.astype(np.float32)


BEEPS = {3: 659.25, 2: 783.99, 1: 987.77}


def count_sfx(sfx: dict, s_left: int) -> np.ndarray:
    """The sound for one second of a countdown: a climbing, speeding-up pulse, then the beeps 3 - 2 - 1."""
    if env("COUNTDOWN_BEEPS", "0") == "1" and s_left in BEEPS and "beep%d" % s_left in sfx:
        return sfx["beep%d" % s_left]
    return sfx.get("tick%d" % max(4, min(int(s_left), 12)), sfx["tick"])


def pop() -> np.ndarray:
    dur = 0.09
    t = np.arange(int(SR * dur)) / SR
    phase = 2 * np.pi * (400 * t + (500 / (2 * dur)) * t**2)  # sweep 400 -> 900 Hz
    return (np.sin(phase) * np.exp(-30 * t)).astype(np.float32) * 0.6


def pop_drop() -> np.ndarray:
    """A water drop: a quick upward bubble."""
    n = int(SR * 0.14)
    t = np.arange(n) / SR
    f = 300 * (1100 / 300) ** np.clip(t / 0.07, 0, 1)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = (np.sin(ph) + 0.15 * np.sin(2 * ph)) * np.exp(-38 * t) * np.minimum(1.0, t / 0.003)
    return (x / float(np.max(np.abs(x)))).astype(np.float32)


def pop_chime() -> np.ndarray:
    """A short, clean bell note."""
    n = int(SR * 0.4)
    t = np.arange(n) / SR
    f = 1046.5
    x = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2.01 * f * t) * np.exp(-8 * t)
         + 0.12 * np.sin(2 * np.pi * 3.02 * f * t) * np.exp(-14 * t)) * np.exp(-11 * t) * np.minimum(1.0, t / 0.002)
    return (x / float(np.max(np.abs(x)))).astype(np.float32)


def pop_blip() -> np.ndarray:
    """A quick retro video-game blip: two square-wave steps up."""
    n = int(SR * 0.11)
    t = np.arange(n) / SR
    f = np.where(t < 0.05, 880.0, 1320.0)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = (np.sin(ph) + np.sin(3 * ph) / 3 + np.sin(5 * ph) / 5) * np.exp(-9 * t) * np.minimum(1.0, t / 0.002)
    return (x / float(np.max(np.abs(x)))).astype(np.float32)


def pop_wood() -> np.ndarray:
    """A hollow wooden knock."""
    rng = np.random.default_rng(21)
    n = int(SR * 0.12)
    t = np.arange(n) / SR
    x = (np.sin(2 * np.pi * 1050 * t) * np.exp(-55 * t) + 0.45 * np.sin(2 * np.pi * 1900 * t) * np.exp(-85 * t)
         + 0.25 * np.diff(np.concatenate([[0.0], rng.standard_normal(n)])) * np.exp(-500 * t))
    x *= np.minimum(1.0, t / 0.0005)
    return (x / float(np.max(np.abs(x)))).astype(np.float32)


def pop_snap() -> np.ndarray:
    """A crisp finger snap."""
    rng = np.random.default_rng(22)
    n = int(SR * 0.09)
    t = np.arange(n) / SR
    nz = np.diff(np.concatenate([[0.0], rng.standard_normal(n)]))
    x = nz * np.exp(-150 * t) + 0.35 * np.sin(2 * np.pi * 1700 * t) * np.exp(-95 * t)
    x *= np.minimum(1.0, t / 0.0004)
    return (x / float(np.max(np.abs(x)))).astype(np.float32)


# The pop-in sounds the person can pick (the sound that plays as each answer choice appears): (id, name, description)
POP_SOUNDS = [
    ("pop", "Pop", "The classic pop", pop),
    ("drop", "Water drop", "A soft, bubbly bloop", pop_drop),
    ("chime", "Chime", "A short, clean bell note", pop_chime),
    ("blip", "Game blip", "A quick retro video-game beep", pop_blip),
    ("wood", "Woodblock", "A hollow wooden knock", pop_wood),
    ("snap", "Finger snap", "A crisp snap", pop_snap),
]
POP_IDS = [p[0] for p in POP_SOUNDS]


def whoosh() -> np.ndarray:
    """The scene-change whoosh: a soft, breathy rush of air, like a long exhale. Gentle noise with the harsh top end rolled off,
    its colour opening slowly from dark to light as it swells and fades. No hiss, no sharp edge. It is placed in the gap
    between two scenes, finishing just before the next one."""
    custom = _override("whoosh")   # assets/whoosh.mp3 (or .wav/.ogg) replaces the built-in sound
    if custom is not None:
        return custom
    dur = 0.4
    n = int(SR * dur)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n)
    x = np.arange(n) / n

    def one_pole_lp(sig, fc):
        a = 1 - np.exp(-2 * np.pi * np.asarray(fc) / SR)
        a = np.broadcast_to(a, sig.shape)
        out = np.zeros_like(sig)
        y = 0.0
        for i in range(len(sig)):
            y += a[i] * (sig[i] - y)
            out[i] = y
        return out

    soft = one_pole_lp(one_pole_lp(noise, 5500.0), 5500.0)      # roll the harsh highs off the noise
    air = soft - one_pole_lp(soft, 260.0)                        # and the low rumble
    fc = 650 * (4200 / 650) ** (x ** 0.9)                        # the colour opens slowly: 650 Hz -> 4.2 kHz
    out = one_pole_lp(one_pole_lp(air, fc), fc)
    env = np.sin(np.pi * np.clip(x ** 0.85, 0, 1)) ** 2          # a slow swell in and a soft fade out
    out = out * env
    return (out / (float(np.max(np.abs(out))) or 1.0) * 0.5).astype(np.float32)


def sparkle() -> np.ndarray:
    out = np.zeros(int(SR * 0.9), dtype=np.float32)
    for k, f in enumerate((2093, 2637, 3136, 4186)):
        a = _tones([(f, 1.0), (2 * f, 0.2)], 0.6, 7)
        s = int(k * 0.06 * SR)
        out[s:s + len(a)] += a[: len(out) - s] * 0.35
    return out


def siren(dur: float = 2.4) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = 850 + 260 * np.sin(2 * np.pi * 1.3 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) + 0.35 * np.sin(2 * ph)
    env = np.minimum(1.0, np.minimum(t / 0.05, (dur - t) / 0.25))
    return (s * env * 0.28).astype(np.float32)


def challenge_sting() -> np.ndarray:
    """Cinematic 'challenge round' hit: a riser, a deep boom with a brassy chord stab, a second smaller hit, then a heartbeat."""
    custom = _override("challenge")
    if custom is not None:
        return custom
    n = int(SR * 3.6)
    out = np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(11)

    def add(at, a, g=1.0):
        st = int(at * SR)
        e = min(n, st + len(a))
        if st < n:
            out[st:e] += a[: e - st] * g

    # riser into the first hit (0 - 0.45 s)
    d = 0.45
    m = int(SR * d)
    t = np.arange(m) / SR
    x = t / d
    ph = 2 * np.pi * np.cumsum(160 + 1100 * x ** 2) / SR
    tone = (np.sin(ph) + 0.5 * np.sin(2 * ph)) * x ** 1.6
    hiss = np.diff(rng.standard_normal(m + 1)).astype(np.float32) * (x ** 2.2)
    add(0.0, (tone * 0.22 + hiss * 0.16).astype(np.float32))

    def hit(f0, deep, chord):
        dd = 1.7
        k = int(SR * dd)
        tt = np.arange(k) / SR
        boom = np.sin(2 * np.pi * np.cumsum(30 + (f0 - 30) * np.exp(-9 * tt)) / SR) * np.exp(-2.4 * tt)
        crack = rng.standard_normal(k).astype(np.float32) * np.exp(-38 * tt)
        stab = np.zeros(k, dtype=np.float32)
        for f in chord:
            for det in (0.994, 1.0, 1.006):
                stab += sum(np.sin(2 * np.pi * h * f * det * tt) / h for h in range(1, 7)).astype(np.float32)
        stab *= np.exp(-3.2 * tt) * np.minimum(1.0, tt / 0.012) * 0.045
        return (boom * deep + crack * 0.35 + stab).astype(np.float32)

    add(0.45, hit(95, 0.85, (110.0, 164.8, 220.0, 277.2)))
    add(0.80, hit(120, 0.6, (123.5, 185.0, 246.9)), 0.7)

    # heartbeat under the narration
    for at in (1.45, 1.95, 2.45, 2.95):
        tt = np.arange(int(SR * 0.3)) / SR
        add(at, (np.sin(2 * np.pi * 58 * tt) * np.exp(-11 * tt)).astype(np.float32), 0.35)
        add(at + 0.17, (np.sin(2 * np.pi * 52 * tt) * np.exp(-13 * tt)).astype(np.float32), 0.22)

    peak = float(np.max(np.abs(out))) or 1.0
    return out / peak * 0.62


def _lowpass(a: np.ndarray, fc: float, passes: int = 4) -> np.ndarray:
    """A gentle low-pass (one-pole, run `passes` times for a softer slope) that takes the hiss and edge off a bright sound."""
    alpha = 1.0 - float(np.exp(-2 * np.pi * fc / SR))
    y = a.astype(np.float64)
    for _ in range(passes):
        out = np.empty_like(y)
        acc = 0.0
        for i in range(len(y)):
            acc += alpha * (y[i] - acc)
            out[i] = acc
        y = out
    return y.astype(np.float32)


def _polish(a: np.ndarray, cutoff: float = 0.0, attack: float = 0.0015, release: float = 0.006) -> np.ndarray:
    """The finishing touch every pop and timer sound gets, the same ones that made the ding and the pop sound clean: no DC offset,
    an optional low-pass for bright sounds, a tiny fade-in (no click at the start) and a short fade-out (no click when it is cut off)."""
    if not len(a) or float(np.max(np.abs(a))) == 0.0:
        return a
    a = a - float(np.mean(a))
    if cutoff:
        a = _lowpass(a, cutoff)
    n = len(a)
    ai, ri = min(int(attack * SR), n // 4), min(int(release * SR), n // 4)
    if ai:
        a[:ai] *= np.linspace(0.0, 1.0, ai, dtype=np.float32)
    if ri:
        a[-ri:] *= np.linspace(1.0, 0.0, ri, dtype=np.float32)
    return a.astype(np.float32)


# how much each bright sound is softened (cut-off in Hz; 0 = leave the top end alone)
POP_SOFTEN = {"pop": 0, "drop": 6000, "chime": 5000, "blip": 3800, "wood": 6500, "snap": 5500}
TIMER_SOFTEN = {"ticks": 0, "classic": 8000, "hihat": 6500, "bubbles": 0, "beat": 8000, "heartbeat": 0}


def _level(a: np.ndarray) -> np.ndarray:
    """One sound effect brought to the common level (see EFFECT_PEAK)."""
    peak = float(np.max(np.abs(a))) or 1.0
    a = a / peak * EFFECT_PEAK
    loud = a[np.abs(a) > 0.01]
    if len(a) >= SR and len(loud):   # a sound that lasts a second or more
        rms = float(np.sqrt(np.mean(loud ** 2)))
        if rms > EFFECT_MAX_RMS:
            a = a * (EFFECT_MAX_RMS / rms)
    return a.astype(np.float32)


def _match_rms(a: np.ndarray, rms: float) -> np.ndarray:
    loud = a[np.abs(a) > 0.01]
    cur = float(np.sqrt(np.mean(loud ** 2))) or 1.0
    a = a * (rms / cur)
    return np.clip(a, -0.95, 0.95).astype(np.float32)


MIX_RANGE_DB = 6.0   # each Mix slider moves its sound this far up or down (decibels)


# The recommended mix (decibels): what the Sound mix levers show out of the box. A video made without any Mix settings uses it too.
# The Overall lever reads 0 at the recommended mix; this much fixed gain sits behind it so the whole video keeps the loudness it was tuned to.
MASTER_TRIM_DB = 3.0
RECOMMENDED_DB = {"narrator": 3.5, "pop": 1.0, "ding": 0.0, "whoosh": 6.0, "timer": 3.5, "master": 0.0}


def mix_levels(mix=None) -> dict:
    """The person's Mix sliders (decibels, any junk ignored; anything missing uses the recommended level) -> linear gains for narrator,
    pop (the answer-choice sound), ding (the right-answer chime, sparkle, siren, sting), whoosh, timer and master."""
    out = {}
    for k, rec in RECOMMENDED_DB.items():
        try:
            db = float((mix or {}).get(k, rec))
        except (TypeError, ValueError):
            db = rec
        if not np.isfinite(db):
            db = rec
        out[k] = 10 ** ((max(-MIX_RANGE_DB, min(MIX_RANGE_DB, db)) + (MASTER_TRIM_DB if k == "master" else 0.0)) / 20.0)
    return out


def effects(timer: str = "ticks", pop_id: str = "pop", mix=None) -> dict:
    """Every sound effect already set to its level (see EFFECT_PEAK). All video types use this, so they all sound the same.
    `timer` and `pop_id` are the person's choice of countdown sound and of answer-choice sound."""
    timer = timer if timer in TIMER_IDS else "ticks"
    pop_fn = next((p[3] for p in POP_SOUNDS if p[0] == pop_id), pop)
    raw = {"bing": bing(), "whoosh": whoosh(), "sparkle": sparkle(), "siren": siren(), "sting": challenge_sting()}
    out = {k: _level(v) for k, v in raw.items()}
    tick_trim, beep_trim = next((t[3] * TIMER_BOOST, t[4] * END_NOTES) for t in TIMER_SOUNDS if t[0] == timer)
    for k, f in BEEPS.items():   # each of the last three seconds: just the rising bell note
        out["beep%d" % k] = (_level(beep(f)) * beep_trim).astype(np.float32)
    for k in range(4, 13):
        out["tick%d" % k] = np.clip(_level(_polish(tick_at(k, timer), TIMER_SOFTEN.get(timer, 0))) * tick_trim, -0.97, 0.97).astype(np.float32) if tick_trim else np.zeros(SR, dtype=np.float32)
    out["tick"] = out["tick8"]
    out["whoosh"] = np.clip(out["whoosh"] * WHOOSH_GAIN, -0.95, 0.95).astype(np.float32)
    if pop_fn is pop:   # the original classic pop, exactly as it was: untouched sound, a touch of saturation for body
        p = _level(pop_fn())
        p = np.tanh(p / float(np.max(np.abs(p)) or 1.0) * 1.25)
    else:
        p = _level(_polish(pop_fn(), POP_SOFTEN.get(pop_id, 0)))
    out["pop"] = (p / float(np.max(np.abs(p)) or 1.0) * (POP_PEAK if pop_fn is pop else POP_PEAK * OTHER_POP_TRIM)).astype(np.float32)
    out["bing"] = np.clip(out["bing"] * BING_GAIN, -0.95, 0.95).astype(np.float32)
    for k in list(out):   # which Mix lever each sound belongs to (the levels are applied when the video is mixed down)
        if k.startswith("tick") or k.startswith("beep"):
            out[k] = tag(out[k], "timer")
        elif k == "whoosh":
            out[k] = tag(out[k], "whoosh")
        elif k == "pop":
            out[k] = tag(out[k], "pop")
        else:   # bing, sparkle, siren, sting
            out[k] = tag(out[k], "ding")
    return out


PREVIEW_VERSION = 20
PREVIEW_GAIN = 0.92   # previews keep the real balance between the sounds (no per-sound normalising); this only sets how loud they play


def sound_preview(kind: str, sid: str):
    """A short wav to listen to before choosing: `kind` is "timer" (a countdown from five, the last three notes, then the ding)
    or "pop" (four answer choices appearing). Made once, then kept on disk."""
    if kind == "timer" and sid in TIMER_IDS:
        sfx = effects(timer=sid)
        parts = [(0.0, count_sfx(sfx, 5)), (1.0, count_sfx(sfx, 4)), (2.0, count_sfx(sfx, 3)), (3.0, count_sfx(sfx, 2)),
                 (4.0, count_sfx(sfx, 1)), (5.3, sfx["bing"])]
        total = 6.8
    elif kind == "pop" and sid in POP_IDS:
        sfx = effects(pop_id=sid)
        parts = [(0.15 + 0.45 * k, sfx["pop"]) for k in range(4)]
        total = 2.4
    else:
        raise ValueError("Unknown sound.")
    d = CACHE_DIR / "sound_previews"
    d.mkdir(parents=True, exist_ok=True)
    import hashlib   # the name carries every level setting, so changing a volume makes new previews instead of reusing old ones
    tag = hashlib.sha1(repr((PREVIEW_VERSION, PREVIEW_GAIN, MASTER_VOLUME, BING_GAIN, END_NOTES, TIMER_BOOST, WHOOSH_GAIN,
                             EFFECT_PEAK, POP_PEAK, TICK_TRIM, BEEP_TRIM)).encode()).hexdigest()[:8]
    path = d / f"{kind}_{sid}_{tag}.wav"
    if path.exists() and path.stat().st_size > 2000:
        return path
    mix = np.zeros(int(total * SR), dtype=np.float32)
    rec = mix_levels(None)   # the sounds play at the recommended mix, like in a video
    for t, clip in parts:
        st = int(t * SR)
        mix[st:st + len(clip)] += np.asarray(clip[:len(mix) - st]) * rec.get(getattr(clip, "group", None) or "other", 1.0)
    mix = _limit(mix * PREVIEW_GAIN * MASTER_VOLUME, 0.95)   # the real levels, through the same clean limiter as the videos
    tmp = path.with_suffix(".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes())
    tmp.replace(path)
    return path


def mix_preview(mix, timer_id: str, pop_id: str, voice_clip=None, master_only_cache: str = ""):
    """A short sample of a whole video's sound at the person's Mix settings: a scene change, the narrator reading, the answer choices
    popping up, a few seconds of countdown, then the ding. It goes through the same mixing and limiter as a real video, so what you
    hear is what the video will sound like. Returns a wav path (kept on disk by content hash)."""
    import hashlib
    g = mix_levels(mix)
    timer_id = timer_id if timer_id in TIMER_IDS else "ticks"
    pop_id = pop_id if pop_id in POP_IDS else "pop"
    sfx = effects(timer_id, pop_id, mix)
    voice = None
    if voice_clip is not None and len(voice_clip):
        voice = tag(trim_silence(voice_clip)[: int(4.5 * SR)] * VOICE_GAIN, "narrator")
    parts = [(0.0, sfx["whoosh"]), (0.06, sfx["pop"])]
    t = 0.5
    if voice is not None:
        parts.append((t, voice))
        t += len(voice) / SR + 0.25
    for k in range(3):
        parts.append((t + 0.45 * k, sfx["pop"]))
    t += 1.6
    for s_left in (5, 4, 3):
        parts.append((t, count_sfx(sfx, s_left)))
        t += 1.0
    parts.append((t + 0.1, sfx["bing"]))
    parts.append((t + 0.15, sfx["sparkle"]))
    total = t + 1.7
    d = CACHE_DIR / "mix_previews"
    d.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(repr((PREVIEW_VERSION, MASTER_VOLUME, timer_id, pop_id, round(g["narrator"], 4), round(g["pop"], 4), round(g["ding"], 4), round(g["whoosh"], 4),
                             round(g["timer"], 4), round(g["master"], 4), None if voice is None else int(len(voice)),
                             master_only_cache, POP_PEAK, BING_GAIN, VOICE_GAIN)).encode()).hexdigest()[:16]
    path = d / f"{key}.wav"
    if path.exists() and path.stat().st_size > 2000:
        return path
    for old in sorted(d.glob("*.wav"), key=lambda p: p.stat().st_mtime)[:-40]:   # keep the folder small
        try:
            old.unlink()
        except OSError:
            pass
    m = Mixer(total)
    for at, clip in parts:
        m.add(at, clip)
    y = m.mix_down(total, mix)
    tmp = path.with_suffix(".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
    tmp.replace(path)
    return path
