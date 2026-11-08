"""Post-deploy smoke test for GridWise (stdlib only).

    python -m tools.smoke_test https://gridwise.tech
    python -m tools.smoke_test http://203.0.113.10
    python -m tools.smoke_test http://localhost:8000      # API only: "/" is skipped when it is not HTML

Hits the dashboard root and every public API endpoint, checks status + basic shape + latency,
prints a table and exits 1 if anything failed. Sends one POST /api/chat (uses at most one Gemini call).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SLOW_S = 5.0      # GET budget
CHAT_SLOW_S = 35  # chat may wait on Gemini (30 s timeout server-side)


def fetch(base: str, path: str, body: dict | None = None, timeout: float = 40):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", "User-Agent": "gridwise-smoke"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, ctype, raw = r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        status, ctype, raw = e.code, e.headers.get("Content-Type", ""), e.read()
    return status, ctype, raw, time.perf_counter() - t0


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].startswith(("http://", "https://")):
        print(__doc__)
        return 2
    base = sys.argv[1].rstrip("/")
    rows: list[tuple[str, str, str, str]] = []   # (mark, check, status/time, note)
    failed = False
    ctx: dict = {}

    def check(name, path, shape, body=None, slow=SLOW_S):
        nonlocal failed
        try:
            status, ctype, raw, dt = fetch(base, path, body)
        except Exception as e:  # DNS, TLS, refused, timeout
            rows.append(("✗", name, "-", f"{type(e).__name__}: {e}"[:70]))
            failed = True
            return None
        note, ok, data = "", status == 200, None
        if ok:
            try:
                data = json.loads(raw)
                note = shape(data) or ""
                ok = not note
            except Exception as e:
                ok, note = False, f"bad body: {type(e).__name__}: {e}"[:70]
        else:
            note = raw[:70].decode("utf-8", "replace").replace("\n", " ")
        if ok and dt > slow:
            ok, note = False, f"slow ({dt:.1f}s > {slow:.0f}s)"
        rows.append(("✓" if ok else "✗", name, f"{status} {dt * 1000:.0f}ms", note))
        failed |= not ok
        return data if ok else None

    # dashboard root: only meaningful when the base URL serves the Next.js app too
    try:
        status, ctype, raw, dt = fetch(base, "/")
        if "text/html" in ctype:
            ok = status == 200 and b"<html" in raw[:5000].lower() and dt <= SLOW_S
            rows.append(("✓" if ok else "✗", "GET /", f"{status} {dt * 1000:.0f}ms", "" if ok else "dashboard not OK"))
            failed |= not ok
        else:
            rows.append(("-", "GET /", f"{status} {dt * 1000:.0f}ms", "skipped: not HTML (API-only base URL?)"))
    except Exception as e:
        rows.append(("✗", "GET /", "-", f"{type(e).__name__}: {e}"[:70]))
        failed = True

    def need(cond, msg):
        return None if cond else msg

    check("GET /api/health", "/api/health",
          lambda d: need(d.get("status") == "ok", f"status={d.get('status')!r} source={d.get('data_source')!r}"))

    def fc(d):
        hs = d.get("hours") or []
        if hs:
            ctx["ts"] = hs[len(hs) // 2]["target_ts"]
        return need(len(hs) == 48 and isinstance(d.get("summary"), dict), f"{len(hs)} hours (want 48)")
    check("GET /api/forecast?hours=48", "/api/forecast?hours=48", fc)

    if "ts" in ctx:
        check("GET /api/forecast/drivers", "/api/forecast/drivers?ts=" + urllib.parse.quote(ctx["ts"]),
              lambda d: need(d.get("target_ts") == ctx["ts"] and isinstance(d.get("drivers"), list)
                             and d.get("why_red"), "missing target_ts/drivers/why_red"))
    else:
        rows.append(("✗", "GET /api/forecast/drivers", "-", "no hour from /api/forecast"))
        failed = True

    check("GET /api/advice", "/api/advice",
          lambda d: need(d.get("headline") and isinstance(d.get("tips"), list), "missing headline/tips"))
    check("GET /api/simulate", "/api/simulate?pct=15&kwh=5&from=17-21&to=10-14",
          lambda d: need(d.get("curve") and "before" in d and "after" in d, "empty curve / missing before-after"))
    check("GET /api/report-card?days=7", "/api/report-card?days=7",
          lambda d: need(isinstance(d.get("rows"), list) and d.get("rows"), "no rows"))
    check("GET /api/history?days=30", "/api/history?days=30",
          lambda d: need(isinstance(d.get("daily"), list) and d.get("daily"), "no daily rows"))
    check("POST /api/chat", "/api/chat",
          lambda d: need(isinstance(d.get("answer"), str) and d["answer"] and isinstance(d.get("highlight_hours"), list),
                         "missing answer/highlight_hours"),
          body={"question": "When is the best time to run my dishwasher?"}, slow=CHAT_SLOW_S)

    w = max(len(r[1]) for r in rows)
    print(f"\nGridWise smoke test: {base}\n")
    for mark, name, st, note in rows:
        print(f"  {mark}  {name:<{w}}  {st:<12}  {note}")
    n_fail = sum(r[0] == "✗" for r in rows)
    print(f"\n{'FAIL' if failed else 'PASS'}: {sum(r[0] == '✓' for r in rows)} ok, {n_fail} failed, "
          f"{sum(r[0] == '-' for r in rows)} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # ✓/✗ on Windows consoles
    sys.exit(main())
