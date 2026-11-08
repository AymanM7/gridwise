"""Runtime settings, read from the environment (and the repo-root .env when present)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


DATABASE_URL = os.getenv("TIGER_DATABASE_URL", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
CORS_ORIGINS = [o.strip() for o in (os.getenv("CORS_ORIGINS") or "http://localhost:3000").split(",") if o.strip()]
TEXAS_HOMES = _f("RIPPLE_RESIDENTIAL_METERS", 10_000_000)   # same default as frontend/src/lib/simulate.ts
PEAKER_MW = _f("RIPPLE_PEAKER_MW", 100)                      # typical gas peaker unit
STALE_MINUTES = 120                                          # forecast older than this -> health "stale"

# /api/chat abuse limits (the public URL spends the owner's Gemini quota). Per uvicorn worker, in memory.
CHAT_MAX_CHARS = int(_f("CHAT_MAX_CHARS", 500))              # longer question -> 422
CHAT_PER_IP_PER_MIN = int(_f("CHAT_PER_IP_PER_MIN", 10))     # over -> 429
CHAT_GEMINI_PER_MIN = int(_f("CHAT_GEMINI_PER_MIN", 60))     # all clients; over -> rule-based answer, no Gemini call

# Background Tiger refresh (app/refresh.py): Jobs API poll interval; 0 disables. Gold (SQL warehouse) check cadence.
AUTO_SYNC_MINUTES = _f("AUTO_SYNC_MINUTES", 5)
GOLD_CHECK_MINUTES = _f("GOLD_CHECK_MINUTES", 30)


def databricks_configured() -> bool:
    return bool(os.getenv("DATABRICKS_HOST") and os.getenv("DATABRICKS_TOKEN"))
