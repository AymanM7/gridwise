"""Export REAL Gold-table data into frontend/fixtures/*.json, shaped like the API contract.

Run from the repo root:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python frontend/scripts/export_fixtures.py

Reads (SQL warehouse only, no notebook compute):
  grid.gold.forecasts, grid.gold.forecast_drivers, grid.gold.report_card,
  grid.gold.strain_reference, grid.gold.strain_hourly, grid.silver.grid_hourly, grid.gold.spike_events
Advice is the rule-based fallback (generated_by="rules"), computed here from the forecast.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.sql import query  # noqa: E402

OUT = ROOT / "frontend" / "fixtures"
TZ = ZoneInfo("America/Chicago")


def rows(sql: str) -> list[dict]:
    cols, data = query(sql)
    return [dict(zip(cols, r)) for r in data]


def f(x, nd=1):
    return None if x is None else round(float(x), nd)


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_utc(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_local(d: datetime) -> str:
    return d.astimezone(TZ).isoformat()


def hour_label(d: datetime) -> str:
    h = d.astimezone(TZ).hour
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12} {suffix}"


def day_hour(d: datetime) -> str:
    return d.astimezone(TZ).strftime("%a ") + hour_label(d)


def plain(d: dict) -> str:
    """Plain-language copy for a SHAP driver (mirrors frontend/src/lib/drivers.ts)."""
    feat, up, v = d["feature"], d["direction"] == "raises", d["feature_value"]
    gw = None if v is None else float(v) / 1000
    if feat == "ercot_wind_forecast":
        return f"low wind ({gw:.1f} GW)" if up else f"strong wind ({gw:.1f} GW)"
    if feat == "ercot_solar_forecast":
        return ("solar fading" if gw and gw > 0.05 else "no solar after dark") if up else f"plenty of solar ({gw:.1f} GW)"
    if feat == "recent_demand_level":
        return "demand running hotter than expected today" if up else "demand running cooler than expected"
    label = d["feature_label"].split(" (")[0].lower()
    return label if up else f"lower {label}"


def write(name: str, obj) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=2), encoding="utf-8")
    print("wrote", OUT / name)


def main() -> None:
    run_ts = rows("SELECT max(run_ts) AS r FROM grid.gold.forecasts")[0]["r"]
    fc = rows(f"""
        SELECT target_ts, horizon_h, net_load_used, demand_p50, band_low, band_high, strain_index, level,
               spike_prob, low_confidence, strain_source, wind_fcst_mw, solar_fcst_mw, local_month
        FROM grid.gold.forecasts WHERE run_ts = '{run_ts}' ORDER BY target_ts""")
    hours = []
    for r in fc:
        t = parse_ts(r["target_ts"])
        hours.append({
            "target_ts": iso_utc(t),
            "local_time": iso_local(t),
            "horizon_h": int(r["horizon_h"]),
            "net_load_mw": f(r["net_load_used"]),
            "demand_mw": f(r["demand_p50"]),
            "band_low_mw": f(r["band_low"]),
            "band_high_mw": f(r["band_high"]),
            "strain_index": f(r["strain_index"]),
            "level": r["level"],
            "spike_prob": f(r["spike_prob"], 4),
            "low_confidence": str(r["low_confidence"]).lower() == "true",
            "strain_source": r["strain_source"],
            "wind_fcst_mw": f(r["wind_fcst_mw"]),
            "solar_fcst_mw": f(r["solar_fcst_mw"]),
        })
    run_dt = parse_ts(run_ts)

    # ---- summary
    peak = max(hours, key=lambda h: h["net_load_mw"] or 0)
    mx = max(hours, key=lambda h: h["spike_prob"] or 0)
    counts = {k: sum(1 for h in hours if h["level"] == k) for k in ("green", "yellow", "red")}

    def span(run):
        s = parse_ts(run[0]["target_ts"])
        e = parse_ts(run[-1]["target_ts"]) + timedelta(hours=1)
        return s, e

    best = []
    # Rank candidate best windows by average strain (lowest first).
    cand = []
    cur = []
    for h in hours + [None]:
        ok = h is not None and h["level"] != "red" and (h["spike_prob"] or 0) < 0.2
        if ok:
            cur.append(h)
        else:
            if len(cur) >= 2:
                # trim long runs to the best 4-hour sub-window
                if len(cur) > 4:
                    sub = min((cur[i:i + 4] for i in range(len(cur) - 3)),
                              key=lambda w: sum(x["strain_index"] for x in w))
                    cur = sub
                cand.append(cur)
            cur = []
    cand.sort(key=lambda w: sum(x["strain_index"] for x in w) / len(w))
    for w in cand[:3]:
        s, e = span(w)
        avg = sum(x["strain_index"] for x in w) / len(w)
        best.append({"start_local": iso_local(s), "end_local": iso_local(e), "avg_strain": round(avg, 1),
                     "label": f"{hour_label(s)} – {hour_label(e)}"})
    best.sort(key=lambda b: b["start_local"])

    avoid = []
    cur = []
    for h in hours + [None]:
        ok = h is not None and (h["level"] == "red" or (h["spike_prob"] or 0) >= 0.5)
        if ok:
            cur.append(h)
        else:
            if cur:
                s, e = span(cur)
                avoid.append({"start_local": iso_local(s), "end_local": iso_local(e),
                              "max_spike_prob": round(max(x["spike_prob"] or 0 for x in cur), 4),
                              "label": f"{hour_label(s)} – {hour_label(e)}"})
            cur = []
    reds = counts["red"]
    if reds:
        verdict = (f"Tight grid ahead: {reds} red hours. Strain peaks {day_hour(parse_ts(peak['target_ts']))}"
                   f" · {round(mx['spike_prob'] * 100)}% spike risk {day_hour(parse_ts(mx['target_ts']))}")
    elif counts["yellow"]:
        verdict = f"Mostly normal, with {counts['yellow']} elevated hours. Shift big loads away from {hour_label(parse_ts(peak['target_ts']))}."
    else:
        verdict = "All green: use power freely."
    forecast = {
        "run_ts": iso_utc(run_dt),
        "hours": hours,
        "summary": {
            "peak": {"local_time": peak["local_time"], "net_load_mw": peak["net_load_mw"],
                     "strain_index": peak["strain_index"], "level": peak["level"]},
            "max_spike": {"local_time": mx["local_time"], "spike_prob": mx["spike_prob"]},
            "level_counts": counts,
            "best_windows": best,
            "avoid_windows": avoid,
            "verdict": verdict,
        },
    }
    write("forecast.json", forecast)
    write("health.json", {"status": "ok", "forecast_run_ts": iso_utc(run_dt),
                          "forecast_age_minutes": 0, "data_source": "fixtures"})

    # ---- drivers for 3 hours: the peak-strain hour, the max-spike hour, and the calmest hour
    calm = min(hours, key=lambda h: h["strain_index"])
    reds_sorted = sorted([h for h in hours if h["level"] == "red"], key=lambda h: -h["strain_index"])
    picks = []
    for h in [reds_sorted[0] if reds_sorted else peak, mx, calm]:
        if h["target_ts"] not in [p["target_ts"] for p in picks]:
            picks.append(h)
    if len(picks) < 3:
        for h in hours:
            if h["target_ts"] not in [p["target_ts"] for p in picks]:
                picks.append(h)
            if len(picks) == 3:
                break
    ts_list = ",".join(f"'{p['target_ts']}'" for p in picks)
    drv = rows(f"""SELECT target_ts, rank, feature, feature_label, feature_value, shap_mw, direction
                   FROM grid.gold.forecast_drivers WHERE run_ts = '{run_ts}' AND target_ts IN ({ts_list})
                   ORDER BY target_ts, rank""")
    drivers = {}
    for p in picks:
        ds = [{"rank": int(d["rank"]), "feature": d["feature"], "label": d["feature_label"],
               "value": f(d["feature_value"]), "mw": f(d["shap_mw"], 0), "direction": d["direction"]}
              for d in drv if iso_utc(parse_ts(d["target_ts"])) == p["target_ts"]]
        why = None
        if p["level"] == "red":
            raw = [d for d in drv if iso_utc(parse_ts(d["target_ts"])) == p["target_ts"] and d["direction"] == "raises"]
            ups = [plain(d) for d in raw][:2]
            why = (f"{hour_label(parse_ts(p['target_ts']))} is red because "
                   + (" and ".join(ups) if ups else "net load is high for the month")
                   + " leave a big gap for gas plants to fill, putting net load near the top of its range for this month"
                   + (f", with a {round(p['spike_prob'] * 100)}% chance of a price spike." if p["spike_prob"] else "."))
        drivers[p["target_ts"]] = {"target_ts": p["target_ts"], "local_time": p["local_time"], "level": p["level"],
                                   "strain_index": p["strain_index"], "drivers": ds, "why_red": why}
    write("drivers.json", drivers)

    # ---- rules advice (the API's fallback shape)
    tips = []
    if avoid:
        a = avoid[0]
        tips.append({"icon": "snowflake", "text": f"Pre-cool your home before {a['label'].split(' – ')[0]}, then let the thermostat drift up a few degrees until {a['label'].split(' – ')[1]}.", "window": a["label"]})
    if best:
        b = best[0]
        tips.append({"icon": "shirt", "text": f"Run laundry and the dishwasher during {b['label']}.", "window": b["label"]})
        night = next((x for x in best if parse_ts(x["start_local"]).astimezone(TZ).hour < 6), best[-1])
        tips.append({"icon": "car", "text": f"Charge the EV during {night['label']}, when strain is lowest.", "window": night["label"]})
    tips.append({"icon": "plug", "text": "Unplug or delay non-essential loads during red hours.", "window": avoid[0]["label"] if avoid else None})
    tomorrow = (run_dt.astimezone(TZ) + timedelta(days=1)).date().isoformat()
    advice = {
        "date_local": tomorrow,
        "generated_by": "rules",
        "headline": verdict,
        "tips": tips,
        "best_hours": [h["local_time"] for h in sorted(hours, key=lambda h: h["strain_index"])[:6]],
        "avoid_hours": [h["local_time"] for h in hours if h["level"] == "red"],
        "why_red": {k: v["why_red"] for k, v in drivers.items() if v["why_red"]},
    }
    write("advice.json", advice)

    # ---- strain reference (for the fixture-mode Ripple approximation)
    months = sorted({int(r["local_month"]) for r in fc})
    ref = rows(f"SELECT month, pct, net_load_mw FROM grid.gold.strain_reference WHERE month IN ({','.join(map(str, months))}) ORDER BY month, pct")
    write("strain_reference.json", [{"month": int(r["month"]), "pct": f(r["pct"], 2), "net_load_mw": f(r["net_load_mw"])} for r in ref])

    # ---- report card
    rc = rows("""SELECT date, source, mape, demand_mape, spike_recall, band_coverage, spike_hours_caught, spike_hours_actual
                 FROM grid.gold.report_card ORDER BY date DESC LIMIT 7""")
    rc_rows = [{"date": r["date"], "source": r["source"], "mape": f(r["mape"], 2), "demand_mape": f(r["demand_mape"], 2),
                "spike_recall": f(r["spike_recall"], 3), "band_coverage": f(r["band_coverage"], 1),
                "spike_hours_caught": int(r["spike_hours_caught"] or 0), "spike_hours_actual": int(r["spike_hours_actual"] or 0)}
               for r in rc]
    note = ("Backtest rows grade Model A's P50 on held-out days; live rows start once forecast batches have actuals."
            if all(r["source"] == "backtest" for r in rc_rows) else None)
    write("report_card.json", {"latest": rc_rows[0] if rc_rows else None, "rows": rc_rows, "note": note})

    # ---- 30-day history (local-day rollups of actuals)
    hist = rows("""
        WITH h AS (
          SELECT to_date(from_utc_timestamp(g.ts_utc, 'America/Chicago')) AS day, g.net_load_mw, g.price_usd_mwh,
                 s.strain_index, e.is_spike
          FROM grid.silver.grid_hourly g
          LEFT JOIN grid.gold.strain_hourly s ON s.ts_utc = g.ts_utc
          LEFT JOIN grid.gold.spike_events e ON e.ts_utc = g.ts_utc
          WHERE g.is_forecast_row = false
            AND g.ts_utc >= (SELECT max(ts_utc) FROM grid.silver.grid_hourly WHERE is_forecast_row = false) - INTERVAL 31 DAYS)
        SELECT day, max(net_load_mw) AS peak, max(strain_index) AS max_strain, avg(price_usd_mwh) AS avg_price,
               max(price_usd_mwh) AS max_price, sum(coalesce(is_spike, 0)) AS spike_hours
        FROM h GROUP BY day ORDER BY day""")
    daily = [{"day": r["day"], "peak_net_load_mw": f(r["peak"]), "max_strain": f(r["max_strain"]),
              "avg_price": f(r["avg_price"], 2), "max_price": f(r["max_price"], 2), "spike_hours": int(r["spike_hours"] or 0)}
             for r in hist][-30:]
    write("history.json", {"daily": daily})


if __name__ == "__main__":
    main()
