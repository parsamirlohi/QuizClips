"""AI narration. The main voices are Google's Gemini voices (expressive, they follow a style direction like "upbeat quiz host");
Microsoft's free neural voices (edge-tts, no key) are the fallback whenever Gemini is not set up or not reachable."""
import asyncio
import base64
import hashlib
import re
import shutil
import tempfile
import time
import uuid
import wave
from pathlib import Path

import numpy as np
import requests

from audio import SR, VOICE_GAIN, decode_audio, trim_silence
import gemini
from config import CACHE_DIR, WORK_DIR, env, flog, is_mock

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


# ------------------------------------------------------------------ Gemini voices
# (name, gender, how Google describes the voice)
GEMINI_VOICES = [
    ("Puck", "M", "Upbeat"), ("Zephyr", "F", "Bright"), ("Fenrir", "M", "Excitable"), ("Sadachbia", "M", "Lively"),
    ("Laomedeia", "F", "Upbeat"), ("Leda", "F", "Youthful"), ("Achird", "M", "Friendly"), ("Aoede", "F", "Breezy"),
    ("Autonoe", "F", "Bright"), ("Callirrhoe", "F", "Easy-going"), ("Sulafat", "F", "Warm"), ("Zubenelgenubi", "M", "Casual"),
    ("Charon", "M", "Informative"), ("Rasalgethi", "M", "Informative"), ("Sadaltager", "M", "Knowledgeable"),
    ("Kore", "F", "Firm"), ("Orus", "M", "Firm"), ("Alnilam", "M", "Firm"), ("Iapetus", "M", "Clear"), ("Erinome", "F", "Clear"),
    ("Umbriel", "M", "Easy-going"), ("Algieba", "M", "Smooth"), ("Despina", "F", "Smooth"), ("Schedar", "M", "Even"),
    ("Enceladus", "M", "Breathy"), ("Algenib", "M", "Gravelly"), ("Gacrux", "F", "Mature"), ("Pulcherrima", "F", "Forward"),
    ("Achernar", "F", "Soft"), ("Vindemiatrix", "F", "Gentle"),
]
GEMINI_DEFAULT = "gemini:Puck"
GEMINI_MODELS = ["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"]   # GEMINI_TTS_MODEL in .env goes first
# How the narrator should sound. Gemini follows plain-language directions, which is what gives the voice emotion.
STYLE = ("Say this like an upbeat, expressive quiz-show host, with real emotion and energy and a brisk pace, "
         "emphasising the key words: ")
TTS_CACHE = CACHE_DIR / "tts_cache"


def gemini_enabled() -> bool:
    return env("TTS_ENGINE", "edge").lower() == "gemini" and (gemini.available() or is_mock())


def _gemini_entries() -> list:
    return [{"id": f"gemini:{n}", "name": f"{n} ({d})", "gender": "female" if g == "F" else "male",
             "region": "Expressive voices", "label": f"{n} ({d}, {'female' if g == 'F' else 'male'})"}
            for n, g, d in GEMINI_VOICES]


def default_voice() -> str:
    return GEMINI_DEFAULT if gemini_enabled() else DEFAULT_VOICE


def _is_gemini(voice: str) -> bool:
    return str(voice).startswith("gemini:")


def _edge_equivalent(voice: str) -> str:
    """The Microsoft voice used if Gemini cannot be reached: same gender as the chosen Gemini voice."""
    name = str(voice).split(":", 1)[-1]
    male = any(n == name and g == "M" for n, g, _ in GEMINI_VOICES)
    return "en-US-GuyNeural" if male else DEFAULT_VOICE


def _gemini_wav(text: str, name: str) -> Path:
    """One line of narration read by a Gemini voice, saved as a wav (cached, so a repeat or a retry costs nothing)."""
    style = env("TTS_STYLE") or STYLE
    TTS_CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{name}|{style}|{text}".encode("utf-8")).hexdigest()[:20]
    path = TTS_CACHE / f"{key}.wav"
    if path.exists() and path.stat().st_size > 2000:
        return path
    keyval = env("GEMINI_API_KEY")
    models = ([env("GEMINI_TTS_MODEL")] if env("GEMINI_TTS_MODEL") else []) + GEMINI_MODELS
    body = {"contents": [{"parts": [{"text": style + text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": name}}}}}
    last = "no model tried"
    for model in models:
        for attempt in range(6):
            t_req = time.time()
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  headers={"x-goog-api-key": keyval, "content-type": "application/json"}, json=body, timeout=90)
            except (requests.Timeout, requests.ConnectionError) as e:
                last = f"{model}: {type(e).__name__}"
                time.sleep(2 * (attempt + 1))
                continue
            flog(f"[tts] request {model} voice={name} {len(text)} chars -> HTTP {r.status_code} in {time.time() - t_req:.1f}s (try {attempt + 1})")
            if r.status_code == 404:
                last = f"model {model} not found"
                break   # try the next model
            if r.status_code in (400, 401, 403):
                raise RuntimeError(f"Gemini voice rejected the request ({r.status_code}): {r.text[:160]}")
            if r.status_code == 429 or r.status_code >= 500:
                last = f"{model}: HTTP {r.status_code}"
                if attempt == 0:
                    flog(f"[tts] Gemini says: {r.text[:300]}")
                if r.status_code == 429 and attempt >= 1:
                    break   # still rate-limited after ~20s: try the other model, then fall back to the Microsoft voice
                wait = min(40, 3 * 2 ** attempt)
                flog(f"[tts] Gemini {model} answered {r.status_code} (limit or busy); waiting {wait}s, try {attempt + 1}/6")
                time.sleep(wait)   # free-tier limit or a busy moment: wait, then try again
                continue
            try:
                part = r.json()["candidates"][0]["content"]["parts"][0]
                blob = part.get("inlineData") or part.get("inline_data")
                pcm = base64.b64decode(blob["data"])
                mime = blob.get("mimeType") or blob.get("mime_type") or ""
                m = re.search(r"rate=(\d+)", mime)
                rate = int(m.group(1)) if m else 24000
            except Exception:
                last = f"{model}: no audio came back"   # the model sometimes answers with text instead; asking again works
                time.sleep(1.0 * (attempt + 1))
                continue
            if len(pcm) < 4000:
                last = f"{model}: audio too short"
                continue
            tmp = path.with_suffix(".part")
            with wave.open(str(tmp), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm)
            tmp.replace(path)
            return path
    raise RuntimeError(f"Gemini voice: {last}")


def _gemini_clip(text: str, name: str) -> np.ndarray:
    a = trim_silence(decode_audio(_gemini_wav(text, name)))
    loud = a[np.abs(a) > 0.01]
    rms = float(np.sqrt(np.mean(loud ** 2))) if len(loud) else 0.0
    if rms > 0:
        a = np.clip(a * (0.13 / rms), -1.0, 1.0)   # the same average level as the Microsoft voices, so the mix balance holds
    return (a * VOICE_GAIN).astype(np.float32)


_gemini_block = {"until": 0.0}   # after Gemini fails, go straight to the Microsoft voice for a while instead of waiting again


def _gemini_all(texts: list, voice: str) -> list:
    from concurrent.futures import ThreadPoolExecutor
    name = voice.split(":", 1)[1]
    t0 = time.time()
    def one(t):
        t1 = time.time()
        a = _gemini_clip(t, name)
        flog(f"[tts] Gemini line ({len(t)} chars) took {time.time() - t1:.1f}s")
        return a
    with ThreadPoolExecutor(max_workers=int(env("TTS_WORKERS", "3"))) as ex:
        out = list(ex.map(one, texts))
    flog(f"[tts] Gemini narration: {len(texts)} lines in {time.time() - t0:.0f}s")
    return out


_voice_cache = {"at": 0.0, "list": None, "live": False}


def available_voices() -> list:
    """Expressive Gemini voices first (when set up), then every Microsoft voice."""
    if gemini_enabled():
        return _gemini_entries() + _edge_voices()
    return _edge_voices()


def _edge_voices() -> list:
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
    if _is_gemini(voice) and not is_mock():
        return _gemini_wav(PREVIEW_TEXT, voice.split(":", 1)[1]), "audio/wav"
    if is_mock():
        path = PREVIEW_DIR / f"mock_{re.sub(r'[^A-Za-z0-9_-]', '_', voice)}.wav"
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
    if _is_gemini(voice) and not gemini_enabled():
        voice = _edge_equivalent(voice)   # Gemini voices are switched off (TTS_ENGINE=gemini in .env turns them back on)
    if _is_gemini(voice) and time.time() < _gemini_block["until"]:
        flog("[tts] Gemini was refusing a moment ago; using the Microsoft voice for this video")
        voice = _edge_equivalent(voice)
    if _is_gemini(voice):
        try:
            return _gemini_all(texts, voice)
        except Exception as e:
            _gemini_block["until"] = time.time() + 600   # not set up, limit reached, or unreachable: the whole video uses the Microsoft voice instead
            flog(f"[tts] Gemini voice failed ({str(e)[:200]}); using the Microsoft voice for this video")
            voice = _edge_equivalent(voice)
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


def _preview_cached(voice: str) -> bool:
    try:
        if _is_gemini(voice):
            style = env("TTS_STYLE") or STYLE
            key = hashlib.sha1(f"{voice.split(':', 1)[1]}|{style}|{PREVIEW_TEXT}".encode("utf-8")).hexdigest()[:20]
            p = TTS_CACHE / f"{key}.wav"
            return p.exists() and p.stat().st_size > 2000
        p = PREVIEW_DIR / f"{voice}.mp3"
        return p.exists() and p.stat().st_size >= 1000
    except Exception:
        return False


def prewarm_previews(gap: float = 8.0) -> None:
    """Quietly make every voice's preview in the background so pressing play is instant. Runs once per
    missing voice, spaced out to stay inside free-tier limits, and stops early if a service is unreachable."""
    if is_mock() or env("PREWARM_VOICES", "0") != "1":
        return   # off by default: it shares Gemini's free-tier quota with real videos and caused rate-limit stalls
    fails = 0
    for v in available_voices():
        vid = v["id"]
        if _preview_cached(vid):
            continue
        try:
            preview_file(vid)
            fails = 0
        except Exception as e:
            fails += 1
            flog(f"[tts] preview prewarm skipped {vid}: {str(e)[:120]}")
            if fails >= 3:
                return
        time.sleep(gap if _is_gemini(vid) else 1.0)
