"""Forecast loading, summary windows/verdict, plain-language drivers, rule-based advice and the
Ripple fallback estimator. Semantics mirror frontend/scripts/export_fixtures.py and
frontend/src/lib/simulate.ts so fixtures mode and live mode read the same."""
from __future__ import annotations

from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from . import db
from .config import PEAKER_MW, TEXAS_HOMES

TZ = ZoneInfo("America/Chicago")
SPIKE_BOOST_PROB, SPIKE_BOOST = 0.5, 15.0
GREEN_MAX, YELLOW_MAX = 60.0, 85.0


# ----------------------------------------------------------------------------- formatting
def r(x, nd=1):
    return None if x is None else round(float(x), nd)


def iso_utc(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_local(d: datetime) -> str:
    return d.astimezone(TZ).isoformat()


def parse_ts(s: str) -> datetime:
    d = datetime.fromisoformat(s.strip().replace(" ", "+").replace("Z", "+00:00"))
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def hour_label(d: datetime) -> str:
    h = d.astimezone(TZ).hour
    return f"{h % 12 or 12} {'am' if h < 12 else 'pm'}"


def day_hour(d: datetime) -> str:
    return d.astimezone(TZ).strftime("%a ") + hour_label(d)


def level_of(strain: float) -> str:
    return "green" if strain < GREEN_MAX else ("yellow" if strain <= YELLOW_MAX else "red")


# ----------------------------------------------------------------------------- forecast
def latest_run_ts() -> datetime | None:
    row = db.fetch_one("SELECT max(run_ts) AS run_ts FROM forecasts")
    return row["run_ts"] if row else None


def latest_batch() -> dict | None:
    """run_ts of the newest batch and when the pipeline produced it (created_at; falls back to run_ts)."""
    return db.fetch_one("""
        SELECT run_ts, coalesce(max(created_at), run_ts) AS produced_at FROM forecasts
        WHERE run_ts = (SELECT max(run_ts) FROM forecasts) GROUP BY run_ts""")


def net_load_band(net_load, demand_p50, demand_lo, demand_hi):
    """Re-center the stored DEMAND band (gold band_low/band_high) on net load.

    Tiger keeps the raw gold demand band; the API serves it in net-load space so it
    brackets the net-load bars: low = net - (demand_p50 - band_low), high = net + (band_high - demand_p50).
    """
    if net_load is None or demand_lo is None or demand_hi is None:
        return None, None
    if demand_lo > demand_hi:
        demand_lo, demand_hi = demand_hi, demand_lo
    if demand_p50 is None or not (demand_lo <= demand_p50 <= demand_hi):
        # Quantile crossing (the demand p50 comes from a different model than the band and can
        # fall outside it): keep the band width but centre it on net load.
        half = (demand_hi - demand_lo) / 2
        return net_load - half, net_load + half
    return net_load - (demand_p50 - demand_lo), net_load + (demand_hi - demand_p50)


def load_hours(run_ts: datetime, limit: int = 48) -> list[dict]:
    rows = db.fetch("""
        SELECT target_ts, horizon_h, net_load_mw, demand_mw, band_low_mw, band_high_mw, strain_index, level,
               spike_prob, low_confidence, strain_source, wind_fcst_mw, solar_fcst_mw, local_month
        FROM forecasts WHERE run_ts = %s ORDER BY target_ts LIMIT %s""", (run_ts, limit))
    out = []
    for x in rows:
        t = x["target_ts"]
        lo, hi = net_load_band(x["net_load_mw"], x["demand_mw"], x["band_low_mw"], x["band_high_mw"])
        out.append({
            "target_ts": iso_utc(t), "local_time": iso_local(t), "horizon_h": int(x["horizon_h"]),
            "net_load_mw": r(x["net_load_mw"]), "demand_mw": r(x["demand_mw"]),
            "band_low_mw": r(lo), "band_high_mw": r(hi),
            "strain_index": r(x["strain_index"]), "level": x["level"], "spike_prob": r(x["spike_prob"], 4),
            "low_confidence": bool(x["low_confidence"]), "strain_source": x["strain_source"],
            "wind_fcst_mw": r(x["wind_fcst_mw"]), "solar_fcst_mw": r(x["solar_fcst_mw"]),
            "_dt": t, "_month": x["local_month"] or t.astimezone(TZ).month,
        })
    return out


def public(hours: list[dict]) -> list[dict]:
    return [{k: v for k, v in h.items() if not k.startswith("_")} for h in hours]


def _span(run: list[dict]) -> tuple[datetime, datetime]:
    return run[0]["_dt"], run[-1]["_dt"] + timedelta(hours=1)


def _win(run: list[dict]) -> str:
    s, e = _span(run)
    return f"{hour_label(s)} – {hour_label(e)}"


def best_windows(hours: list[dict]) -> list[dict]:
    """Runs of >=2 non-red hours with spike risk < 20 %, trimmed to their best 4 h; top 3 by avg strain."""
    cand, cur = [], []
    for h in hours + [None]:
        if h is not None and h["level"] != "red" and (h["spike_prob"] or 0) < 0.2:
            cur.append(h)
            continue
        if len(cur) >= 2:
            if len(cur) > 4:
                cur = min((cur[i:i + 4] for i in range(len(cur) - 3)),
                          key=lambda w: sum(x["strain_index"] or 0 for x in w))
            cand.append(cur)
        cur = []
    cand.sort(key=lambda w: sum(x["strain_index"] or 0 for x in w) / len(w))
    out = []
    for w in cand[:3]:
        s, e = _span(w)
        out.append({"start_local": iso_local(s), "end_local": iso_local(e),
                    "avg_strain": round(sum(x["strain_index"] or 0 for x in w) / len(w), 1), "label": _win(w),
                    "_hours": w})
    return sorted(out, key=lambda b: b["start_local"])


def avoid_windows(hours: list[dict]) -> list[dict]:
    """Contiguous runs of red hours or spike risk >= 50 %."""
    out, cur = [], []
    for h in hours + [None]:
        if h is not None and (h["level"] == "red" or (h["spike_prob"] or 0) >= 0.5):
            cur.append(h)
            continue
        if cur:
            s, e = _span(cur)
            out.append({"start_local": iso_local(s), "end_local": iso_local(e),
                        "max_spike_prob": round(max(x["spike_prob"] or 0 for x in cur), 4), "label": _win(cur),
                        "_hours": cur})
        cur = []
    return out


def strip(ws: list[dict]) -> list[dict]:
    return [{k: v for k, v in w.items() if not k.startswith("_")} for w in ws]


def summarize(hours: list[dict]) -> dict:
    if not hours:
        return {"peak": None, "max_spike": None, "level_counts": {"green": 0, "yellow": 0, "red": 0},
                "best_windows": [], "avoid_windows": [], "verdict": "No forecast available yet."}
    peak = max(hours, key=lambda h: h["net_load_mw"] or 0)
    mx = max(hours, key=lambda h: h["spike_prob"] or 0)
    counts = {k: sum(1 for h in hours if h["level"] == k) for k in ("green", "yellow", "red")}
    if counts["red"]:
        verdict = (f"Tight grid ahead: {counts['red']} red hours. Strain peaks {day_hour(peak['_dt'])}"
                   f" · {round((mx['spike_prob'] or 0) * 100)}% spike risk {day_hour(mx['_dt'])}")
    elif counts["yellow"]:
        verdict = (f"Mostly normal, with {counts['yellow']} elevated hours. "
                   f"Shift big loads away from {hour_label(peak['_dt'])}.")
    else:
        verdict = "All green: use power freely."
    return {
        "peak": {"local_time": peak["local_time"], "net_load_mw": peak["net_load_mw"],
                 "strain_index": peak["strain_index"], "level": peak["level"]},
        "max_spike": {"local_time": mx["local_time"], "spike_prob": mx["spike_prob"]},
        "level_counts": counts,
        "best_windows": strip(best_windows(hours)),
        "avoid_windows": strip(avoid_windows(hours)),
        "verdict": verdict,
    }


# ----------------------------------------------------------------------------- drivers
def load_drivers(run_ts: datetime, target: datetime | None = None) -> dict[str, list[dict]]:
    sql = ("SELECT target_ts, rank, feature, label, value, shap_mw, direction FROM forecast_drivers "
           "WHERE run_ts = %s" + (" AND target_ts = %s" if target else "") + " ORDER BY target_ts, rank")
    rows = db.fetch(sql, (run_ts, target) if target else (run_ts,))
    out: dict[str, list[dict]] = {}
    for d in rows:
        out.setdefault(iso_utc(d["target_ts"]), []).append(
            {"rank": int(d["rank"]), "feature": d["feature"], "label": d["label"], "value": r(d["value"]),
             "mw": r(d["shap_mw"], 0), "direction": d["direction"]})
    return out


def plain(d: dict) -> str:
    """Plain-language copy for a SHAP driver (mirrors frontend/src/lib/drivers.ts)."""
    feat, up, v = d["feature"], d["direction"] == "raises", d["value"]
    gw = None if v is None else float(v) / 1000
    if feat == "ercot_wind_forecast" and gw is not None:
        return f"low wind ({gw:.1f} GW)" if up else f"strong wind ({gw:.1f} GW)"
    if feat == "ercot_solar_forecast":
        return ("solar fading" if gw and gw > 0.05 else "no solar after dark") if up else \
            f"plenty of solar ({(gw or 0):.1f} GW)"
    if feat == "recent_demand_level":
        return "demand running hotter than expected today" if up else "demand running cooler than expected"
    label = (d.get("label") or feat).split(" (")[0].lower()
    return label if up else f"lower {label}"


def why_sentence(h: dict, drivers: list[dict]) -> str | None:
    if h["level"] != "red":
        return None
    ups = [plain(d) for d in drivers if d["direction"] == "raises"][:2]
    sp = h["spike_prob"] or 0
    return (f"{hour_label(h['_dt'])} is red because "
            + (" and ".join(ups) if ups else "net load is high for the month")
            + " leave a big gap for gas plants to fill, putting net load near the top of its range for this month"
            + (f", with a {round(sp * 100)}% chance of a price spike." if sp >= 0.01 else "."))


# ----------------------------------------------------------------------------- advice
def advice_day(run_ts: datetime) -> date:
    return (run_ts.astimezone(TZ) + timedelta(days=1)).date()


def rules_advice(run_ts: datetime, hours: list[dict], drivers: dict[str, list[dict]]) -> dict:
    best, avoid = best_windows(hours), avoid_windows(hours)
    summ = summarize(hours)
    def day(w):  # "Sat 5 pm – 1 am": rule labels need the day, the 48 h span covers 2-3 dates
        return datetime.fromisoformat(w["start_local"]).strftime("%a ") + w["label"]

    tips = []
    if avoid:
        # pre-cooling needs lead time: skip a window that is already starting when the forecast begins
        soon = hours[0]["_dt"] + timedelta(hours=2) if hours else None
        a = next((w for w in avoid if soon is None or parse_ts(w["start_local"]) >= soon), avoid[0])
        start, end = day(a).split(" – ")
        tips.append({"icon": "snowflake", "text": f"Pre-cool your home before {start}, then let the thermostat "
                     f"drift up a few degrees until {end}.", "window": day(a)})
    if best:
        b = best[0]
        tips.append({"icon": "shirt", "text": f"Run laundry and the dishwasher {day(b)} "
                     f"(average strain {b['avg_strain']:.0f}/100).", "window": day(b)})
        night = next((x for x in best if x["_hours"][0]["_dt"].astimezone(TZ).hour < 6), best[-1])
        tips.append({"icon": "car", "text": f"Charge the EV {day(night)}, when strain is lowest.",
                     "window": day(night)})
    if avoid:
        worst = max(avoid, key=lambda w: w["max_spike_prob"])
        tips.append({"icon": "plug", "text": f"Delay non-essential loads {day(worst)}: price-spike risk reaches "
                     f"{worst['max_spike_prob'] * 100:.0f}%.", "window": day(worst)})
    why = {}
    for h in hours:
        s = why_sentence(h, drivers.get(h["target_ts"], []))
        if s:
            why[h["target_ts"]] = s
    return {
        "date_local": advice_day(run_ts).isoformat(),
        "generated_by": "rules",
        "headline": summ["verdict"],
        "tips": tips,
        "best_hours": [h["local_time"] for h in sorted(hours, key=lambda h: h["strain_index"] or 0)[:6]],
        "avoid_hours": [h["local_time"] for h in hours if h["level"] == "red"],
        "why_red": why,
    }


def stored_advice(run_ts: datetime) -> dict | None:
    """The gold-synced advice row for the advice day (else the most recent one)."""
    return db.fetch_one("""
        SELECT date_local, run_ts, generated_by, headline, tips, best_hours, avoid_hours, why_red FROM daily_advice
        ORDER BY (date_local = %s) DESC, date_local DESC LIMIT 1""", (advice_day(run_ts),))


# Gold advice may use emoji icons; the UI uses lucide names (same set as the rules plan)
ICON_MAP = {"⚠️": "plug", "⚠": "plug", "🔌": "plug", "🌡️": "snowflake", "🌡": "snowflake", "❄️": "snowflake",
            "❄": "snowflake", "🚗": "car", "🔋": "car", "👕": "shirt", "🧺": "shirt", "🍽️": "shirt"}


def _in_forecast(local_times, hours: list[dict]) -> list[str]:
    """Keep only the stored hours that are still inside the current 48 h forecast."""
    valid = {parse_ts(h["local_time"]) for h in hours if h.get("local_time")}
    out = []
    for t in local_times or []:
        try:
            if parse_ts(t) in valid:
                out.append(t)
        except Exception:
            continue
    return out


def build_advice(run_ts: datetime, hours: list[dict], drivers: dict[str, list[dict]]) -> dict:
    rules = rules_advice(run_ts, hours, drivers)
    row = stored_advice(run_ts)
    if not row:
        return rules
    stale = row.get("run_ts") is not None and row["run_ts"] != run_ts
    if stale and (row["generated_by"] or "") == "rules":
        # An older rules plan is the same algorithm on older data: the fresh one is strictly better.
        return rules
    why = dict(rules["why_red"])
    if not stale:  # an older run's sentences quote that run's numbers; keep the fresh rule sentences
        why.update({iso_utc(parse_ts(k)): v for k, v in (row["why_red"] or {}).items() if v})
    tips = [{"icon": ICON_MAP.get(t.get("icon") or "", t.get("icon") or "plug"), "text": t.get("text") or "", "window": t.get("window")}
            for t in (row["tips"] or []) if isinstance(t, dict) and t.get("text")]
    return {
        "date_local": row["date_local"].isoformat(),
        "generated_by": "gemini" if (row["generated_by"] or "gemini") != "rules" else "rules",
        "headline": row["headline"] or rules["headline"],
        "tips": tips or rules["tips"],
        "best_hours": _in_forecast(row["best_hours"], hours) or rules["best_hours"],
        "avoid_hours": _in_forecast(row["avoid_hours"], hours) or rules["avoid_hours"],
        "why_red": why,
    }


# ----------------------------------------------------------------------------- Ripple
def window_hours(spec: str) -> list[int]:
    a, b = (int(x) % 24 for x in spec.split("-"))
    out, h = [], a
    while h != b and len(out) < 24:
        out.append(h)
        h = (h + 1) % 24
    return out


def norm_window(spec: str) -> str:
    a, b = (int(x) % 24 for x in spec.split("-"))
    return f"{a:02d}-{b:02d}"


@lru_cache(maxsize=1)
def _reference() -> dict[int, tuple[list[float], list[float]]]:
    rows = db.fetch("SELECT month, pct, net_load_mw FROM strain_reference ORDER BY month, pct")
    ref: dict[int, tuple[list[float], list[float]]] = {}
    for x in rows:
        xs, ps = ref.setdefault(int(x["month"]), ([], []))
        xs.append(max(float(x["net_load_mw"]), xs[-1] if xs else float("-inf")))  # monotone guard
        ps.append(float(x["pct"]))
    return ref


def strain_for(net_load: float, month: int, spike: float) -> float:
    ref = _reference().get(int(month))
    if not ref:
        return 50.0
    xs, ps = ref
    if net_load <= xs[0]:
        base = 0.0
    elif net_load >= xs[-1]:
        base = 100.0
    else:
        i = bisect_left(xs, net_load)
        x0, x1, p0, p1 = xs[i - 1], xs[i], ps[i - 1], ps[i]
        base = p0 if x1 == x0 else p0 + (net_load - x0) / (x1 - x0) * (p1 - p0)
    return min(100.0, base + SPIKE_BOOST) if spike > SPIKE_BOOST_PROB else base


def estimate_simulation(hours: list[dict], pct: float, kwh: float, frm: str, to: str) -> dict:
    """Fallback when no precomputed scenario exists (same maths as the frontend's offline estimator)."""
    fh, th = window_hours(frm), window_hours(to)
    energy = (pct / 100) * TEXAS_HOMES * kwh / 1000          # MWh shifted per day
    cut = energy / len(fh) if fh else 0.0
    add = energy / len(th) if th else 0.0
    curve = []
    for h in hours:
        hr = h["_dt"].astimezone(TZ).hour
        before = h["net_load_mw"] or 0.0
        delta = -cut if hr in fh else (add if hr in th else 0.0)
        after = before + delta
        sb = h["spike_prob"] or 0.0
        sa = min(1.0, max(0.0, sb + (delta / 1000) * 0.08 * (1 if sb > 0.05 else 0.2)))
        strain_after = h["strain_index"] if delta == 0 else strain_for(after, h["_month"], sa)
        curve.append({"target_ts": h["target_ts"], "local_time": h["local_time"], "before_mw": r(before),
                      "after_mw": r(after), "level_before": h["level"], "level_after": level_of(strain_after or 0),
                      "spike_before": r(sb, 4), "spike_after": r(sa, 4)})
    return curve


def curve_stats(curve: list[dict], k: str) -> dict:
    lv, mw, sp = f"level_{k}", f"{k}_mw", f"spike_{k}"
    return {"red_hours": sum(1 for c in curve if c[lv] == "red"),
            "peak_mw": max((c[mw] or 0 for c in curve), default=0),
            "max_spike_prob": max((c[sp] or 0 for c in curve), default=0)}


def peakers(reduction_mw: float) -> int:
    return int(round(max(0.0, reduction_mw) / PEAKER_MW))
