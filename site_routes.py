"""Public website: page routes, the looks list for the home page, and the early-access waitlist.

Pages live in static/ as plain HTML. The generator itself is at /app.
Waitlist sign-ups are appended to waitlist.jsonl (ignored by git). Run `python3 tools/export_waitlist.py` for a CSV.
"""
import json
import re
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

import looks
from config import BASE

router = APIRouter()
STATIC = BASE / "static"
WAITLIST = BASE / "waitlist.jsonl"
PAGES = {"/": "home.html", "/app": "index.html", "/pricing": "pricing.html", "/terms": "terms.html",
         "/privacy": "privacy.html", "/settings": "settings.html", "/profile": "profile.html"}
NO_STORE = {"Cache-Control": "no-store"}


def _page(name: str):
    def view():
        return FileResponse(STATIC / name, headers=NO_STORE)
    return view


for _path, _file in PAGES.items():
    router.add_api_route(_path, _page(_file), methods=["GET"], include_in_schema=False)


@router.get("/robots.txt", include_in_schema=False)
def robots():
    return HTMLResponse("User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /output/\n", media_type="text/plain")


@router.get("/api/looks")
def public_looks():
    """Light-weight list for the home page (no voice lookups, so it is fast)."""
    return {"looks": looks.listing(), "default": looks.DEFAULT}


# ----------------------------------------------------------------------------- waitlist
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
_lock = threading.Lock()
_hits: dict = {}  # ip -> recent request times


class WaitlistRequest(BaseModel):
    email: str = Field(max_length=254)
    plan: str = Field(default="", max_length=20)
    interest: str = Field(default="", max_length=60)
    website: str = Field(default="", max_length=200)  # hidden field: people leave it empty, bots fill it


def _known_emails() -> set:
    out = set()
    if WAITLIST.exists():
        for line in WAITLIST.read_text(encoding="utf-8").splitlines():
            try:
                out.add(json.loads(line)["email"])
            except Exception:
                pass
    return out


@router.post("/api/waitlist")
def join_waitlist(req: WaitlistRequest, request: Request):
    if req.website:  # honeypot: pretend it worked
        return {"ok": True}
    email = req.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "That email address doesn't look right. Check it and try again.")
    ip = request.client.host if request.client else "?"
    now = time.time()
    with _lock:
        recent = [t for t in _hits.get(ip, []) if now - t < 3600]
        if len(recent) >= 8:
            raise HTTPException(429, "Too many tries. Please wait a while and try again.")
        _hits[ip] = recent + [now]
        if email not in _known_emails():
            with WAITLIST.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"email": email, "plan": req.plan, "interest": req.interest,
                                    "at": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
    return {"ok": True}
