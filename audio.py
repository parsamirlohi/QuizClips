"""Audio helpers: decoding, mixing, and the synthesized sound effects (bing, tick, pop)."""
import subprocess
import wave

import numpy as np

from config import ASSETS_DIR, ffmpeg_exe

SR = 44100


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
        a = self.buf[: int(seconds * SR)]
        peak = float(np.max(np.abs(a))) if len(a) else 0.0
        if peak > 0.98:
            a = a * (0.98 / peak)
        pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16)
        stereo = np.repeat(pcm[:, None], 2, axis=1)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(stereo.tobytes())


def _tones(parts, dur, decay, attack=0.002) -> np.ndarray:
    t = np.arange(int(SR * dur)) / SR
    s = sum(amp * np.sin(2 * np.pi * f * t) for f, amp in parts)
    env = np.exp(-decay * t) * np.minimum(1.0, t / attack)
    return (s * env).astype(np.float32)


def _override(name: str):
    """Drop assets/bing.wav (or .mp3/.ogg) next to the app to use your own sound."""
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
    a = _tones([(f, 1.0), (2 * f, 0.35), (3.01 * f, 0.15), (4.2 * f, 0.06)], 1.6, 3.2)
    return a / float(np.max(np.abs(a))) * 0.8


def tick() -> np.ndarray:
    return _tones([(1200, 1.0)], 0.06, 60) * 0.5


def pop() -> np.ndarray:
    dur = 0.09
    t = np.arange(int(SR * dur)) / SR
    phase = 2 * np.pi * (400 * t + (500 / (2 * dur)) * t**2)  # sweep 400 -> 900 Hz
    return (np.sin(phase) * np.exp(-30 * t)).astype(np.float32) * 0.6
