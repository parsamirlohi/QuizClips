"""AI narration using Microsoft's free neural voices via edge-tts (no API key)."""
import asyncio
import re
import shutil
import tempfile
import time
import uuid
import wave
from pathlib import Path

import numpy as np

from audio import SR, VOICE_GAIN, decode_audio, trim_silence
from config import CACHE_DIR, WORK_DIR, is_mock

REGIONS = {"US": "United States", "GB": "United Kingdom", "AU": "Australia", "CA": "Canada",
           "IE": "Ireland", "IN": "India", "NZ": "New Zealand", "ZA": "South Africa"}
DEFAULT_VOICE = "en-US-AriaNeural"

# Used when Microsoft's voice list can't be fetched (offline). Online, every English voice is listed instead.
_FALLBACK = [
    ("US", "F", "Aria"), ("US", "F", "Jenny"), ("US", "F", "Michelle"), ("US", "F", "Emma"), ("US", "F", "Ava"),
    ("US", "M", "Guy"), ("US", "M", "Christopher"), ("US", "M", "Eric"), ("US", "M", "Roger"),
    ("US", "M", "Steffan"), ("US", "M", "Andrew"), ("US", "M", "Brian"),
    ("GB", "F", "Sonia"), ("GB", "F", "Libby"), ("GB", "M", "Ryan"), ("GB", "M", "Thomas"),
    ("AU", "F", "Natasha"), ("AU", "M", "William"), ("CA", "F", "Clara"), ("CA", "M", "Liam"),
    ("IE", "F", "Emily"), ("IE", "M", "Connor"), ("IN", "F", "Neerja"), ("IN", "M", "Prabhat"),
    ("NZ", "F", "Molly"), ("NZ", "M", "Mitchell"), ("ZA", "F", "Leah"), ("ZA", "M", "Luke"),
]


def _entry(short_name: str, region: str, gender: str) -> dict:
    name = short_name.split("-", 2)[2]
    if name.endswith("Neural"):
        name = name[:-6]
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    g = "female" if gender.upper().startswith("F") else "male"
    return {"id": short_name, "name": name, "gender": g, "region": REGIONS[region],
            "label": f"{name} ({region}, {g})"}


def voice_entries(raw: list) -> list:
    """English voices from edge-tts' list (ShortName, Gender, Locale), grouped by region, nicest first."""
    out = []
    for v in raw:
        loc = v.get("Locale", "")
        if loc.startswith("en-") and loc[3:] in REGIONS and v.get("ShortName", "").count("-") >= 2:
            out.append(_entry(v["ShortName"], loc[3:], v.get("Gender", "")))
    order = list(REGIONS.values())
    out.sort(key=lambda e: (order.index(e["region"]), e["id"] != DEFAULT_VOICE, e["name"]))
    return out


def _fallback_entries() -> list:
    return [_entry(f"en-{r}-{n}Neural", r, g) for r, g, n in _FALLBACK]


_voice_cache = {"at": 0.0, "list": None, "live": False}


def available_voices() -> list:
    """All English voices Microsoft offers (cached); a built-in list if it can't be reached right now."""
    now = time.time()
    c = _voice_cache
    if c["list"] and (c["live"] or now - c["at"] < 300):
        return c["list"]
    live = False
    try:
        if is_mock():
            raise RuntimeError("test mode")
        import edge_tts

        raw = asyncio.run(asyncio.wait_for(edge_tts.list_voices(), timeout=8))
        entries = voice_entries(raw)
        live = len(entries) > 0
    except Exception:
        entries = []
    if not entries:
        entries = _fallback_entries()
    c.update(at=now, list=entries, live=live)
    return entries


PREVIEW_DIR = CACHE_DIR / "voice_previews"
PREVIEW_TEXT = "Only a genius can get five out of five."


def preview_file(voice: str) -> tuple:
    """(path, media_type) of a short sample read by this voice. Made once, then reused from disk."""
    PREVIEW_DIR.mkdir(exist_ok=True)
    if is_mock():
        path = PREVIEW_DIR / f"mock_{voice}.wav"
        if not path.exists():
            audio = _mock_voice(PREVIEW_TEXT)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SR)
                w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
        return path, "audio/wav"
    path = PREVIEW_DIR / f"{voice}.mp3"
    if not path.exists() or path.stat().st_size < 1000:
        import edge_tts

        tmp = path.with_suffix(".part")
        asyncio.run(edge_tts.Communicate(PREVIEW_TEXT, voice, rate="+8%").save(str(tmp)))
        tmp.replace(path)
    return path, "audio/mpeg"


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
            return trim_silence(decode_audio(path)) * VOICE_GAIN

        return await asyncio.gather(*[one(t) for t in texts])

    try:
        return list(asyncio.run(run()))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
