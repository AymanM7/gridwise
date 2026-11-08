"""Vercel serverless entry point for the GridWise API (FastAPI / ASGI).

Vercel rewrites /api/<rest> to this function as /api/index?__p=<rest> (see vercel.json) and the
function only ever sees "/api/index", so this shim restores the original path before FastAPI routes it.
Deployed as its own Vercel project from the repo root.
"""
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.main import app as _fastapi  # noqa: E402


async def app(scope, receive, send):
    if scope["type"] == "http":
        pairs = parse_qsl((scope.get("query_string") or b"").decode(), keep_blank_values=True)
        rest = next((v for k, v in pairs if k == "__p"), None)
        if rest is not None:
            path = "/api/" + rest.lstrip("/") if rest else "/api/health"
            qs = urlencode([(k, v) for k, v in pairs if k != "__p"]).encode()
            scope = {**scope, "path": path, "raw_path": path.encode(), "query_string": qs}
    await _fastapi(scope, receive, send)
