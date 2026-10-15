"""Structured text and image requests to a local Ollama model."""
import json

import requests

from config import env


def chat_json(messages: list, schema: dict, temperature: float = 0.3) -> dict:
    model = env("OLLAMA_MODEL", "gemma4:latest").strip()
    base = env("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
    if not model or not base:
        raise RuntimeError("Set OLLAMA_MODEL and OLLAMA_BASE_URL in .env.")
    try:
        timeout = int(env("OLLAMA_TIMEOUT", "180"))
        if timeout <= 0:
            raise ValueError
    except ValueError as exc:
        raise RuntimeError("OLLAMA_TIMEOUT must be a positive number of seconds.") from exc
    try:
        response = requests.post(
            f"{base}/api/chat",
            json={"model": model, "messages": messages, "format": schema,
                  "stream": False, "think": False,
                  "options": {"temperature": temperature, "num_predict": 4096}},
            timeout=(5, timeout),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("expected an Ollama response object")
        if payload.get("error"):
            raise ValueError(payload["error"])
        result = json.loads(payload["message"]["content"])
        if not isinstance(result, dict):
            raise ValueError("expected a JSON object")
        return result
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"Ollama request failed. Check that {model} is installed and Ollama is running: {exc}") from exc
