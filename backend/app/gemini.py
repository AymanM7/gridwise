"""Gemini chat, grounded on the latest 48 h forecast + advice (REST, key sent as x-goog-api-key)."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .config import GEMINI_API_KEY, GEMINI_MODEL

log = logging.getLogger("gridwise.gemini")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM = """You are GridWise, a friendly assistant for Texans on the ERCOT power grid.
Answer ONLY questions about electricity use, the Texas grid, prices, the forecast, appliances, EVs,
thermostats and saving energy. For anything else, politely steer back to the grid in one sentence.
Ground every claim in the FORECAST and ADVICE JSON you are given; never invent numbers.
Always cite specific hours in Texas local time (for example "5 pm Sun"), and keep answers under 90 words,
plain English, no markdown tables. Strain levels: green < 60 (easy), yellow 60-85, red > 85 (tight).
Return JSON: {"answer": string, "highlight_ids": [the "id" numbers of the FORECAST hours your answer
refers to, at most 8]}. Pick ids by matching the "local" field, which is Texas time."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "answer": {"type": "STRING"},
        "highlight_ids": {"type": "ARRAY", "items": {"type": "INTEGER"}},
    },
    "required": ["answer", "highlight_ids"],
}


def context_blob(hours: list[dict], summary: dict, advice: dict) -> str:
    def local(h):  # "Sun 2026-11-08 5 pm": unambiguous and easy to quote
        d = datetime.fromisoformat(h["local_time"])
        return d.strftime("%a %Y-%m-%d ") + f"{d.hour % 12 or 12} {'am' if d.hour < 12 else 'pm'}"

    # Hours are referenced by a small integer id, not the UTC target_ts: flash otherwise copies UTC
    # timestamps whose clock hour matches the local hour it means (off by 6 h).
    compact = [{"id": i, "local": local(h), "net_load_mw": h["net_load_mw"],
                "strain": h["strain_index"], "level": h["level"], "spike_prob": h["spike_prob"]} for i, h in enumerate(hours, 1)]
    adv = {k: advice.get(k) for k in ("headline", "tips", "best_hours", "avoid_hours")}
    now = datetime.now(ZoneInfo("America/Chicago")).strftime("%a %Y-%m-%d %I:%M %p")
    blob = json.dumps({"NOW_TEXAS": now, "FORECAST": compact, "SUMMARY": summary, "ADVICE": adv},
                      separators=(",", ":"), ensure_ascii=False)
    # en dashes in window labels make flash emit raw newlines inside JSON strings
    return blob.replace(" – ", " to ").replace("–", "-")


_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()
_cooldown_until = 0.0
CACHE_TTL = 600        # same question on the same forecast -> reuse the answer for 10 min
COOLDOWN_S = 30        # after a 429, skip Gemini for a bit (free-tier RPM)


def ask(question: str, hours: list[dict], summary: dict, advice: dict, timeout: float = 30) -> dict | None:
    """Returns {answer, highlight_hours} or None when Gemini is unavailable (caller falls back to rules)."""
    global _cooldown_until
    if not GEMINI_API_KEY or time.time() < _cooldown_until:
        return None
    key = hashlib.sha1((" ".join(question.lower().split()) + "|" + (hours[0]["target_ts"] if hours else "")
                        ).encode()).hexdigest()
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [
            {"text": "DATA:\n" + context_blob(hours, summary, advice)},
            {"text": "QUESTION: " + question.strip()[:1000]},
        ]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1024, "responseMimeType": "application/json",
                             "responseSchema": SCHEMA, "thinkingConfig": {"thinkingBudget": 0}},
    }
    for attempt in range(2):  # one retry: flash occasionally returns a truncated JSON body
        try:
            resp = requests.post(URL.format(model=GEMINI_MODEL), json=body, timeout=timeout,
                                 headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"})
            if resp.status_code != 200:
                log.warning("gemini HTTP %s: %s", resp.status_code, " ".join(resp.text[:200].split()))
                if resp.status_code == 429:
                    _cooldown_until = time.time() + COOLDOWN_S
                    return None
                if resp.status_code < 500:
                    return None
                continue
            cand = resp.json()["candidates"][0]
            parts = cand["content"]["parts"]
            out = json.loads("".join(p.get("text", "") for p in parts), strict=False)
            hl = []
            for i in out.get("highlight_ids") or []:
                try:
                    i = int(i)
                except (TypeError, ValueError):
                    continue
                if 1 <= i <= len(hours) and hours[i - 1]["target_ts"] not in hl:
                    hl.append(hours[i - 1]["target_ts"])
            hl = hl[:8]
            answer = " ".join(str(out.get("answer") or "").split())
            res = {"answer": answer, "highlight_hours": hl}
            if answer:
                with _lock:
                    if len(_cache) > 500:
                        _cache.clear()
                    _cache[key] = (time.time(), res)
            return res
        except Exception as e:  # network, quota, malformed JSON
            log.warning("gemini failed (attempt %d): %s: %s", attempt + 1, type(e).__name__, e)
    return None
