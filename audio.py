"""Audio helpers: decoding, mixing, and the synthesized sound effects (bing, tick, pop)."""
import subprocess
import wave

import numpy as np

from config import ASSETS_DIR, ffmpeg_exe

SR = 44100
CEILING = 0.95      # the loudest moment of a finished video sits here (just under clipping)
TARGET_RMS = 0.25   # the average level every finished video is brought to, whatever its type (was 0.2: a bit over 3 dB louder)
MAX_BOOST = 5.0     # never lift a mix by more than this
KNEE = 0.7          # above this a peak is eased down (see finish) instead of cutting off
VOICE_GAIN = 1.7    # the narrator, relative to the sound effects
# How loud the sound effects are, in ONE place so every video type has the same levels. Every effect peaks at the same level
# as the timer tick, so none of them is louder or quieter than another. A long, steady sound (the siren) is also held to a
# maximum average level, otherwise being as tall as a click would make it drown the narrator.
EFFECT_PEAK = 0.68
EFFECT_MAX_RMS = 0.16
TICK_TRIM = 0.9   # the timer tick a little lower than the other effects


def decode_audio(path) -> np.ndarray:
    """Any audio file -> mono float32 at 44.1 kHz."""
    cmd = [ffmpeg_exe(), "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("Could not decode audio: " + p.stderr.decode(errors="ignore")[-500:])
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def trim_silence(a: np.ndarray, thr: float = 0.012, pad: float = 0.04) -> np.ndarray:
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx) == 0:
        return a
    s = max(0, idx[0] - int(pad * SR))
    e = min(len(a), idx[-1] + int(pad * SR))
    return a[s:e]


class Mixer:
    def __init__(self, seconds: float):
        self.buf = np.zeros(int(seconds * SR) + SR, dtype=np.float32)

    def add(self, at: float, clip: np.ndarray, gain: float = 1.0) -> None:
        s = int(at * SR)
        if s < 0 or s >= len(self.buf):
            return
        e = min(len(self.buf), s + len(clip))
        self.buf[s:e] += clip[: e - s] * gain

    def save(self, path, seconds: float) -> None:
        a = self.buf[: int(seconds * SR)].copy()
        a = finish(a)
        pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16)
        stereo = np.repeat(pcm[:, None], 2, axis=1)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(stereo.tobytes())


def finish(a: np.ndarray) -> np.ndarray:
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
    x = np.abs(a * min(gain, MAX_BOOST))
    over = x > KNEE
    x[over] = KNEE + (CEILING - KNEE) * np.tanh((x[over] - KNEE) / (CEILING - KNEE))
    return (np.sign(a) * x).astype(np.float32)


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
    f = 1567.98  # G6, bell-like with a few overtones
    a = _tones([(f, 1.0), (2 * f, 0.3), (3 * f, 0.1)], 1.6, 3.2)
    return a / float(np.max(np.abs(a))) * 0.8


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


def tick() -> np.ndarray:
    """One second of a wind-up kitchen timer: four mechanical clicks, alternating a higher 'tick' and a lower 'tock'.
    The countdown plays this once per second, so it ticks the whole time the viewer is thinking."""
    custom = _override("tick")
    if custom is not None:
        return custom
    rng = np.random.default_rng(5)
    hi = _click(rng, [(2350, 1.0), (3600, 0.5)], 150, body=0.35)
    lo = _click(rng, [(1650, 1.0), (2700, 0.45)], 130, body=0.5, body_f=150.0)
    out = np.zeros(SR, dtype=np.float32)
    for k in range(4):
        c = (hi if k % 2 == 0 else lo) * (0.95 if k % 2 == 0 else 0.8)
        s = int(k * 0.25 * SR)
        out[s:s + len(c)] += c
    return out * 0.6


def pop() -> np.ndarray:
    """A short bubble pop. Longer and brighter than a plain sine so it reads as loud as the timer tick, not as a faint blip."""
    dur = 0.16
    t = np.arange(int(SR * dur)) / SR
    phase = 2 * np.pi * (450 * t + (700 / (2 * dur)) * t**2)   # sweep 450 -> 1150 Hz
    body = np.sin(phase) + 0.5 * np.sin(2 * phase) + 0.25 * np.sin(3 * phase)
    click = np.random.default_rng(3).standard_normal(len(t)) * np.exp(-400 * t) * 0.6
    out = (body * np.exp(-14 * t) + click) * np.minimum(1.0, t * 800)
    return np.tanh(out * 1.6).astype(np.float32)


def whoosh() -> np.ndarray:
    dur = 0.38
    n = int(SR * dur)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n).astype(np.float32)
    out = np.zeros(n, dtype=np.float32)
    y = 0.0
    for i in range(n):  # one-pole low-pass whose cutoff sweeps upward
        a = 0.02 + 0.5 * (i / n) ** 2
        y += a * (noise[i] - y)
        out[i] = y
    t = np.arange(n) / SR
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
    out = out * env
    return out / (float(np.max(np.abs(out))) or 1.0) * 0.45


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


def effects() -> dict:
    """Every sound effect already set to its level (see EFFECT_PEAK). All video types use this, so they all sound the same."""
    raw = {"bing": bing(), "tick": tick(), "pop": pop(), "whoosh": whoosh(), "sparkle": sparkle(), "siren": siren(),
           "sting": challenge_sting()}
    out = {k: _level(v) for k, v in raw.items()}
    out["tick"] = (out["tick"] * TICK_TRIM).astype(np.float32)   # the countdown plays the whole time, so it sits a little under the rest
    out["pop"] = _match_rms(out["pop"], 0.42)   # a short sound needs a higher peak to feel as loud as the others
    return out
