"""AI narration using Microsoft's free neural voices via edge-tts (no API key)."""
import asyncio
import io
import shutil
import tempfile
import uuid
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

from audio import SR, decode_audio, trim_silence
from config import WORK_DIR, is_mock

VOICES = [
    ("en-US-AriaNeural", "Aria (female)"),
    ("en-US-GuyNeural", "Guy (male)"),
    ("en-US-JennyNeural", "Jenny (female)"),
    ("en-US-ChristopherNeural", "Christopher (male)"),
]

PREVIEW_TEXT = "Ready for a quick quiz? Which planet is known as the Red Planet? Pick your answer!"


def voice_preview(voice: str) -> bytes:
    """A short sample at the same speaking rate as the quiz narration."""
    if voice not in {v for v, _ in VOICES}:
        raise ValueError("Unsupported voice")
    return _cached_preview(voice, is_mock())


@lru_cache(maxsize=8)
def _cached_preview(voice: str, mock: bool) -> bytes:
    clip = _mock_voice(PREVIEW_TEXT) if mock else synthesize_all([PREVIEW_TEXT], voice)[0]
    pcm = (np.clip(clip, -1, 1) * 32767).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SR)
        wav.writeframes(pcm.tobytes())
    return output.getvalue()


def _mock_voice(text: str) -> np.ndarray:
    dur = max(0.8, 0.06 * len(text))
    t = np.arange(int(dur * SR)) / SR
    wobble = 0.5 + 0.5 * np.sin(2 * np.pi * 3.3 * t)
    fade = np.minimum(1.0, np.minimum(t, dur - t) / 0.03)
    return (0.25 * np.sin(2 * np.pi * 170 * t) * wobble * fade).astype(np.float32)


def synthesize_all(texts: list, voice: str, rate: str = "+8%") -> list:
    """Return one mono float32 array per text, in order."""
    if is_mock():
        return [_mock_voice(t) for t in texts]
    import edge_tts

    tmp = Path(tempfile.mkdtemp(dir=WORK_DIR, prefix="tts_"))

    async def run():
        sem = asyncio.Semaphore(4)

        async def one(text):
            path = tmp / f"{uuid.uuid4().hex}.mp3"
            async with sem:
                for attempt in range(3):
                    try:
                        await edge_tts.Communicate(text, voice, rate=rate).save(str(path))
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(1.5)
            return trim_silence(decode_audio(path))

        return await asyncio.gather(*[one(t) for t in texts])

    try:
        return list(asyncio.run(run()))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
