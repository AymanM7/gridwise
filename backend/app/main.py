"""GridWise API (FastAPI). Reads Tiger Data; see backend/README.md and the API contract.

    uvicorn backend.app.main:app --port 8000
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import core, db, gemini, refresh
from .config import (CHAT_GEMINI_PER_MIN, CHAT_MAX_CHARS, CHAT_PER_IP_PER_MIN, CORS_ORIGINS,
                     STALE_MINUTES)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("gridwise.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.open_pool()
    refresh.start()          # re-syncs Tiger after each Databricks Job run (AUTO_SYNC_MINUTES=0 disables)
    yield
    refresh.stop()
    db.close_pool()


app = FastAPI(title="GridWise API", version="1.0", lifespan=lifespan, docs_url="/api/docs",
              openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["*"])


def _latest() -> datetime:
    run_ts = core.latest_run_ts()
    if run_ts is None:
        raise HTTPException(503, "no forecast has been synced yet")
    return run_ts


# ----------------------------------------------------------------------------- health
@app.get("/api/health")
def health():
    try:
        batch = core.latest_batch()
    except Exception as e:
        log.warning("health: db error %s", e)
        return {"status": "error", "forecast_run_ts": None, "forecast_age_minutes": None,
                "data_source": "unavailable"}
    if batch is None:
        return {"status": "empty", "forecast_run_ts": None, "forecast_age_minutes": None, "data_source": "tiger"}
    run_ts = batch["run_ts"]
    # age = time since the pipeline produced the batch. run_ts is the data anchor hour and trails the clock by
    # ERCOT/EIA latency (~3 h), so measuring from it would show the "pipeline may be delayed" banner even when fresh.
    age = max(0, int((datetime.now(timezone.utc) - batch["produced_at"]).total_seconds() // 60))
    # status stays "ok" while the DB answers; the UI shows its "last updated" banner from forecast_age_minutes
    if age > STALE_MINUTES:
        log.info("forecast is %d min old", age)
    return {"status": "ok", "forecast_run_ts": core.iso_utc(run_ts),
            "forecast_age_minutes": age, "data_source": "tiger"}


# ----------------------------------------------------------------------------- forecast
@app.get("/api/forecast")
def forecast(hours: int = Query(48, ge=1, le=48)):
    run_ts = _latest()
    hs = core.load_hours(run_ts, hours)
    return {"run_ts": core.iso_utc(run_ts), "hours": core.public(hs), "summary": core.summarize(hs)}


@app.get("/api/forecast/drivers")
def forecast_drivers(ts: str | None = Query(None, description="target_ts (ISO-8601); default: peak-strain hour")):
    run_ts = _latest()
    hs = core.load_hours(run_ts)
    if not hs:
        raise HTTPException(404, "empty forecast")
    if ts:
        try:
            want = core.parse_ts(ts)
        except ValueError:
            raise HTTPException(422, f"bad ts: {ts!r}")
        h = next((x for x in hs if x["_dt"] == want), None)
        if h is None:
            raise HTTPException(404, f"{core.iso_utc(want)} is not in the latest forecast ({core.iso_utc(run_ts)})")
    else:
        h = max(hs, key=lambda x: (x["strain_index"] or 0, x["spike_prob"] or 0))
    drivers = core.load_drivers(run_ts, h["_dt"]).get(h["target_ts"], [])
    why = core.why_sentence(h, drivers)
    adv = core.stored_advice(run_ts)
    if adv and adv.get("why_red") and adv.get("run_ts") in (None, run_ts):  # older runs quote stale numbers
        for k, v in adv["why_red"].items():
            try:
                if v and core.parse_ts(k) == h["_dt"]:
                    why = v
            except ValueError:
                pass
    return {"target_ts": h["target_ts"], "local_time": h["local_time"], "level": h["level"],
            "strain_index": h["strain_index"], "drivers": drivers, "why_red": why}


# ----------------------------------------------------------------------------- advice
def _advice_bundle():
    run_ts = _latest()
    hs = core.load_hours(run_ts)
    drivers = core.load_drivers(run_ts)
    return run_ts, hs, core.build_advice(run_ts, hs, drivers)


@app.get("/api/advice")
def advice():
    return _advice_bundle()[2]


# ----------------------------------------------------------------------------- history
@app.get("/api/history")
def history(days: int = Query(30, ge=1, le=400)):
    rows = db.fetch("""
        SELECT day, peak_net_load_mw, max_strain, avg_price, max_price, spike_hours FROM actuals_daily
        WHERE day > (SELECT max(day) FROM actuals_daily) - make_interval(days => %s) ORDER BY day""", (days,))
    return {"daily": [{
        "day": x["day"].astimezone(core.TZ).date().isoformat(),
        "peak_net_load_mw": core.r(x["peak_net_load_mw"]), "max_strain": core.r(x["max_strain"]),
        "avg_price": core.r(x["avg_price"], 2), "max_price": core.r(x["max_price"], 2),
        "spike_hours": int(x["spike_hours"] or 0)} for x in rows]}


# ----------------------------------------------------------------------------- simulate
WIN = re.compile(r"^\d{1,2}-\d{1,2}$")


@app.get("/api/simulate")
def simulate(pct: float = Query(5, ge=0, le=100), kwh: float = Query(3, ge=0, le=100),
             from_: str = Query("16-20", alias="from"), to: str = Query("22-02")):
    if not WIN.match(from_) or not WIN.match(to):
        raise HTTPException(422, "windows look like 16-20 (local hours, end exclusive)")
    frm, to = core.norm_window(from_), core.norm_window(to)
    params = {"pct": pct, "kwh": kwh, "from": frm, "to": to}

    scen = db.fetch("""SELECT * FROM shift_scenarios
                       WHERE run_ts = (SELECT max(run_ts) FROM shift_scenarios)""")
    if scen:
        pr = (max(s["participation_pct"] for s in scen) - min(s["participation_pct"] for s in scen)) or 1
        kr = (max(s["kwh_per_home"] for s in scen) - min(s["kwh_per_home"] for s in scen)) or 1
        best = min(scen, key=lambda s: ((s["from_window"] != frm) + (s["to_window"] != to),
                                        abs(s["participation_pct"] - pct) / pr + abs(s["kwh_per_home"] - kwh) / kr))
        nearest = {"pct": best["participation_pct"], "kwh": best["kwh_per_home"],
                   "from": best["from_window"], "to": best["to_window"]}
        rows = db.fetch("""SELECT * FROM shift_scenario_curves WHERE run_ts = %s AND participation_pct = %s
                           AND kwh_per_home = %s AND from_window = %s AND to_window = %s ORDER BY target_ts""",
                        (best["run_ts"], best["participation_pct"], best["kwh_per_home"],
                         best["from_window"], best["to_window"]))
        if rows:
            curve = [{"target_ts": core.iso_utc(c["target_ts"]), "local_time": core.iso_local(c["target_ts"]),
                      "before_mw": core.r(c["before_mw"]), "after_mw": core.r(c["after_mw"]),
                      "level_before": c["level_before"], "level_after": c["level_after"],
                      "spike_before": core.r(c["spike_before"], 4), "spike_after": core.r(c["spike_after"], 4)}
                     for c in rows]
        else:  # scenario stats exist but no curve: draw the estimate for the nearest params
            curve = core.estimate_simulation(core.load_hours(_latest()), nearest["pct"], nearest["kwh"],
                                             nearest["from"], nearest["to"])
        b, a = core.curve_stats(curve, "before"), core.curve_stats(curve, "after")
        # prefer the scenario task's own numbers where present
        fmt = {"red_hours": int, "peak_mw": lambda v: core.r(v, 1), "max_spike_prob": lambda v: core.r(v, 4)}
        for k, col in (("red_hours", "red_hours_{}"), ("peak_mw", "peak_mw_{}"), ("max_spike_prob", "spike_prob_{}")):
            for stats, side in ((b, "before"), (a, "after")):
                if best.get(col.format(side)) is not None:
                    stats[k] = fmt[k](best[col.format(side)])
        red = best.get("peak_reduction_mw")
        red = int(round(red)) if red is not None else round(max(0.0, b["peak_mw"] - a["peak_mw"]))
        # Always use the API's peaker size (RIPPLE_PEAKER_MW, the "~100 MW each" the UI prints); the gold
        # column assumes a different unit size, so mixing them would contradict the label.
        return {"params": params, "nearest_params": nearest, "before": b, "after": a, "peak_reduction_mw": red,
                "peakers_avoided": core.peakers(red), "curve": curve}

    curve = core.estimate_simulation(core.load_hours(_latest()), pct, kwh, frm, to)
    b, a = core.curve_stats(curve, "before"), core.curve_stats(curve, "after")
    red = round(max(0.0, b["peak_mw"] - a["peak_mw"]))
    return {"params": params, "nearest_params": None, "before": b, "after": a, "peak_reduction_mw": red,
            "peakers_avoided": core.peakers(red), "curve": curve}


# ----------------------------------------------------------------------------- report card
@app.get("/api/report-card")
def report_card(days: int = Query(7, ge=1, le=120)):
    rows = db.fetch("""
        SELECT DISTINCT ON (date) date, source, mape, demand_mape, spike_recall, band_coverage,
               spike_hours_caught, spike_hours_actual
        FROM report_card ORDER BY date DESC, (source = 'live') DESC LIMIT %s""", (days,))
    out = [{"date": x["date"].isoformat(), "source": x["source"], "mape": core.r(x["mape"], 2),
            "demand_mape": core.r(x["demand_mape"], 2), "spike_recall": core.r(x["spike_recall"], 3),
            "band_coverage": core.r(x["band_coverage"], 1), "spike_hours_caught": int(x["spike_hours_caught"] or 0),
            "spike_hours_actual": int(x["spike_hours_actual"] or 0)} for x in rows]
    if not out:
        note = "No graded days yet."
    elif all(x["source"] == "backtest" for x in out):
        note = "Backtest rows grade Model A's P50 on held-out days; live rows start once forecast batches have actuals."
    elif any(x["source"] == "backtest" for x in out):
        note = "Live rows grade the published forecast against actuals; older days are backtests of Model A's P50."
    else:
        note = "Each day grades the published forecast against ERCOT actuals."
    return {"latest": out[0] if out else None, "rows": out, "note": note}


# ----------------------------------------------------------------------------- chat
class ChatIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=CHAT_MAX_CHARS)


_hits: dict[str, deque] = defaultdict(deque)   # client ip -> recent /api/chat timestamps
_gemini_hits: deque = deque()
_rl_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    # Behind Caddy: it overwrites X-Forwarded-For with the real client (incoming XFF is untrusted by default),
    # and the api container is not published, so the header cannot be forged from outside.
    xff = request.headers.get("x-forwarded-for", "")
    return xff.split(",")[0].strip() or (request.client.host if request.client else "?")


def _allow(q: deque, limit: int, now: float) -> bool:
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def _rate_limit(request: Request) -> bool:
    """429 if this IP is over CHAT_PER_IP_PER_MIN; returns False when the global Gemini budget is spent."""
    now = time.monotonic()
    ip = _client_ip(request)
    with _rl_lock:
        if not _allow(_hits[ip], CHAT_PER_IP_PER_MIN, now):
            raise HTTPException(429, "too many questions; try again in a minute", headers={"Retry-After": "60"})
        if len(_hits) > 10_000:                  # bound memory: drop idle IPs
            for k in [k for k, q in _hits.items() if not q or now - q[-1] > 60]:
                del _hits[k]
        return _allow(_gemini_hits, CHAT_GEMINI_PER_MIN, now)


def _rules_answer(hs: list[dict], summ: dict) -> dict:
    best = summ["best_windows"][0] if summ["best_windows"] else None
    avoid = summ["avoid_windows"][0] if summ["avoid_windows"] else None
    parts = [summ["verdict"] + "."]
    if best:
        parts.append(f"The easiest window is {best['label']} (avg strain {best['avg_strain']:.0f}).")
    if avoid:
        parts.append(f"Avoid heavy appliances {avoid['label']}.")
    hl = [h["target_ts"] for h in hs if best and best["start_local"] <= h["local_time"] < best["end_local"]]
    return {"answer": " ".join(parts) + " (AI assistant is offline; this is the rule-based summary.)",
            "highlight_hours": hl[:8]}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    use_gemini = _rate_limit(request)
    run_ts, hs, adv = _advice_bundle()
    summ = core.summarize(hs)
    out = gemini.ask(body.question, core.public(hs), summ, adv) if use_gemini else None
    return out if out and out["answer"] else _rules_answer(hs, summ)
