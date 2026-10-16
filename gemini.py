"""Small Gemini REST helper shared by footage planning (footage_plan.py) and the picture check (vision.py)."""
import requests

from config import env

# Tried in order; GEMINI_MODEL in .env goes first. The "-latest" alias keeps working when Google renames models.
MODELS = ["gemini-3.1-flash-lite", "gemini-flash-lite-latest"]


class RateLimited(RuntimeError):
    pass


def available() -> bool:
    return bool(env("GEMINI_API_KEY"))


def generate(parts: list, timeout: int = 60) -> str:
    """Send text and/or {"inline_data": ...} parts, get JSON text back."""
    key = env("GEMINI_API_KEY")
    models = ([env("GEMINI_MODEL")] if env("GEMINI_MODEL") else []) + MODELS
    last = "no model tried"
    for model in models:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key, "content-type": "application/json"},
            json={"contents": [{"parts": parts}],
                  "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}},
            timeout=timeout,
        )
        if r.status_code == 404:  # model name not available to this key; try the next one
            last = f"model {model} not found"
            continue
        if r.status_code == 429:
            raise RateLimited("Gemini rate limit reached (free tier). Wait a minute and try again.")
        if r.status_code in (400, 401, 403):
            raise RuntimeError(f"Gemini rejected the request ({r.status_code}). Check GEMINI_API_KEY in .env")
        r.raise_for_status()
        out = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in out)
    raise RuntimeError(f"Gemini: {last}. Set GEMINI_MODEL in .env to a model your key can use.")
