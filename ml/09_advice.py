# Databricks notebook source
# MAGIC %md
# MAGIC # 09 · Advice (Phase 4.1 Gemini daily plan + 4.2 "Why Red?" sentences)
# MAGIC For the **latest `run_ts` in `grid.gold.forecasts`**, writes one row to `grid.gold.daily_advice`: the plan the
# MAGIC dashboard's advice panel shows (`GET /api/advice`). Re-running for the same `run_ts` replaces that row.
# MAGIC
# MAGIC **How it is built**
# MAGIC 1. **Rules first (always).** From the 48 forecast hours: *avoid windows* = contiguous runs of red hours or
# MAGIC    hours with `spike_prob ≥ 0.30`; *best windows* = the lowest-scoring 3 h blocks (score = mean strain +
# MAGIC    100 × mean spike prob) that contain no red/avoid hour, plus the best overnight block (EV) and best daytime
# MAGIC    block (laundry). `best_hours` / `avoid_hours` are always these rule-based hours, so the highlighted hours are
# MAGIC    exactly what the models say. A templated plan (headline, tips) and a templated "Why Red?" sentence for every red
# MAGIC    hour (from that hour's top-3 drivers in `gold.forecast_drivers`) are also built.
# MAGIC 2. **Gemini (if available).** `gemini-2.5-flash` (REST `generateContent`, header `x-goog-api-key`, JSON output
# MAGIC    with a response schema) gets the 48 h forecast, the rule windows and the red hours' drivers as compact JSON and
# MAGIC    writes the headline, 3–5 tips and one sentence per red hour. The key comes from
# MAGIC    `dbutils.secrets.get('gridwise', 'gemini_api_key')` (create it with `python -m tools.setup_secrets`).
# MAGIC 3. **Validate + fall back.** Gemini's JSON is shape-checked (icons from a fixed set, lengths, red-hour keys). If
# MAGIC    the secret is missing, the call fails or the shape is wrong, the rule plan is used (`generated_by = 'rules'`).
# MAGIC    Red hours Gemini skipped get the templated sentence (`why_red_source = 'gemini+rules'`).
# MAGIC 4. **Checks.** Shape invariants (JSON shape, hours are forecast hours, best/avoid disjoint, no red hour in best,
# MAGIC    a sentence for every red hour, date = tomorrow) fail the task. Data-dependent ones (at least one best hour,
# MAGIC    2+ tips, Gemini actually used) are **warnings** in the exit JSON and never count in `all_pass`, so a
# MAGIC    rules-only or all-red day still publishes its row and keeps the Job green.
# MAGIC
# MAGIC | column | meaning |
# MAGIC |---|---|
# MAGIC | `run_ts`, `date_local` | forecast batch; the local (America/Chicago) date of **tomorrow** relative to `run_ts` |
# MAGIC | `generated_by` | `gemini` or `rules` (headline + tips) |
# MAGIC | `headline`, `tips_json` | headline; JSON list of `{icon, text, window}` (icon is one emoji from `ICONS`) |
# MAGIC | `best_hours_json`, `avoid_hours_json` | JSON lists of local ISO times (`2026-11-08T02:00:00-06:00`) |
# MAGIC | `best_windows_json`, `avoid_windows_json` | JSON `{start_local, end_local, avg_strain / max_spike_prob, label}` |
# MAGIC | `why_red_json`, `why_red_source` | JSON `{target_ts (UTC, '...Z'): sentence}` for every red hour; `gemini` / `gemini+rules` / `rules` |
# MAGIC | `model`, `gemini_status`, `created_at` | lineage (`gemini_status`: `ok`, `no_secret`, `error: ...`, `invalid: ...`) |

# COMMAND ----------

import json
import os
import re
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

dbutils.widgets.text("catalog", "grid")
catalog = dbutils.widgets.get("catalog")
spark.conf.set("spark.sql.session.timeZone", "UTC")

FCST = f"{catalog}.gold.forecasts"
DRIVERS = f"{catalog}.gold.forecast_drivers"
TABLE = f"{catalog}.gold.daily_advice"
TZ = "America/Chicago"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
AVOID_SPIKE = 0.30          # spike prob that makes an hour "avoid" even when not red
BLOCK_H = 3                 # length of a "best" block
ICONS = ["⚠️", "🚗", "👕", "🍽️", "🌡️", "❄️", "🔥", "💡", "☀️", "🌙", "🔌", "✅", "🏊"]

# COMMAND ----------

# MAGIC %md ## 1 · Latest forecast batch + drivers

# COMMAND ----------

run_ts = pd.Timestamp(spark.sql(f"SELECT max(run_ts) m FROM {FCST}").first()["m"])
run_ts_sql = run_ts.strftime("%Y-%m-%d %H:%M:%S")
fc = (spark.sql(f"SELECT target_ts, horizon_h, net_load_used, strain_index, level, spike_prob, low_confidence, "
                f"wind_fcst_mw, solar_fcst_mw FROM {FCST} WHERE run_ts = TIMESTAMP '{run_ts_sql}'").toPandas()
      .sort_values("target_ts").reset_index(drop=True))
fc["target_ts"] = pd.to_datetime(fc["target_ts"])
assert len(fc) == 48, f"forecast batch {run_ts} has {len(fc)} rows"
drv = spark.sql(f"SELECT target_ts, rank, feature, feature_label, feature_value, shap_mw, direction "
                f"FROM {DRIVERS} WHERE run_ts = TIMESTAMP '{run_ts_sql}'").toPandas()
drv["target_ts"] = pd.to_datetime(drv["target_ts"])
print(f"run_ts {run_ts} | {len(fc)} forecast hours | {len(drv)} driver rows | "
      f"levels {fc['level'].value_counts().to_dict()}")

# COMMAND ----------

# MAGIC %md ## 2 · Rule engine (windows, tips, templated "Why Red?")

# COMMAND ----------


def ts_key(t):
    """Canonical UTC key used in why_red_json and by the API: '2026-11-07T22:00:00Z'."""
    return pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ")


def hour_label(t):
    h = t.hour % 12 or 12
    return f"{h} {'AM' if t.hour < 12 else 'PM'}"


def window_label(start, end):
    """start = first hour, end = exclusive end (local tz-aware). 'Sat 3 PM–12 AM' or 'Sat 10 PM–Sun 2 AM'."""
    if (end - pd.Timedelta(hours=1)).date() == start.date():
        return f"{start:%a} {hour_label(start)}–{hour_label(end)}"
    return f"{start:%a} {hour_label(start)}–{end:%a} {hour_label(end)}"


def build_frame(fc):
    h = fc.copy()
    h["local"] = h["target_ts"].dt.tz_localize("UTC").dt.tz_convert(TZ)
    h["local_time"] = h["local"].map(lambda t: t.isoformat())
    h["avoid"] = (h["level"] == "red") | (h["spike_prob"] >= AVOID_SPIKE)
    return h


def runs(mask):
    """Contiguous True runs -> list of (i0, i1_inclusive)."""
    out, i0 = [], None
    for i, m in enumerate(list(mask) + [False]):
        if m and i0 is None:
            i0 = i
        elif not m and i0 is not None:
            out.append((i0, i - 1))
            i0 = None
    return out


def avoid_windows(h):
    out = []
    for i0, i1 in runs(h["avoid"].values):
        g = h.iloc[i0:i1 + 1]
        start, end = g["local"].iloc[0], g["local"].iloc[-1] + pd.Timedelta(hours=1)
        out.append({"start_local": start.isoformat(), "end_local": end.isoformat(),
                    "max_spike_prob": round(float(g["spike_prob"].max()), 3),
                    "max_strain": round(float(g["strain_index"].max()), 1),
                    "label": window_label(start, end), "_rows": list(range(i0, i1 + 1))})
    return out          # chronological


def best_blocks(h, hour_filter=None, k=3):
    """Lowest-score non-overlapping BLOCK_H-hour blocks without avoid hours (optionally restricted to local hours)."""
    cands = []
    for i in range(len(h) - BLOCK_H + 1):
        g = h.iloc[i:i + BLOCK_H]
        if g["avoid"].any():
            continue
        if hour_filter is not None and not all(hour_filter(t.hour) for t in g["local"]):
            continue
        score = float(g["strain_index"].mean() + 100.0 * g["spike_prob"].mean())
        cands.append((score, i))
    chosen = []
    for score, i in sorted(cands):
        if all(abs(i - j) >= BLOCK_H for _, j in chosen):
            chosen.append((score, i))
        if len(chosen) == k:
            break
    out = []
    for score, i in sorted(chosen, key=lambda x: x[1]):
        g = h.iloc[i:i + BLOCK_H]
        start, end = g["local"].iloc[0], g["local"].iloc[-1] + pd.Timedelta(hours=1)
        out.append({"start_local": start.isoformat(), "end_local": end.isoformat(),
                    "avg_strain": round(float(g["strain_index"].mean()), 1),
                    "max_spike_prob": round(float(g["spike_prob"].max()), 3),
                    "label": window_label(start, end), "_rows": list(range(i, i + BLOCK_H)), "_score": score})
    return out


def phrase(d, local_hour):
    """One driver -> a plain-language clause."""
    f, v, mw, up = d["feature"], d["feature_value"], abs(float(d["shap_mw"])), d["direction"] == "raises"
    v = None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
    gw = f"{mw / 1000:.1f} GW"
    if f == "ercot_wind_forecast":
        return (f"wind is forecast at only {v / 1000:.1f} GW (well below a typical hour)" if up
                else f"strong wind ({v / 1000:.1f} GW) is helping")
    if f == "ercot_solar_forecast":
        if up and (v is None or v < 500):
            return "the sun is down, so solar adds almost nothing"
        return (f"solar is weaker than usual ({v / 1000:.1f} GW)" if up else f"solar ({v / 1000:.1f} GW) is helping")
    if f == "cdd":
        return "heat is driving air-conditioning use" if up else "mild weather keeps air-conditioning load low"
    if f == "hdd":
        return "cold weather is driving heating demand" if up else "mild weather keeps heating demand low"
    if f in ("temp_f", "heat_index_f", "temp_f_roll24_mean") and v is not None:
        return f"temperatures around {v:.0f}°F {'push demand up' if up else 'keep demand down'}"
    if f == "time_of_day":
        if up and 16 <= local_hour <= 22:
            return "it is the evening rush, when people get home and cook"
        return f"the usual daily pattern {'adds' if up else 'removes'} about {gw}"
    if f == "recent_demand_level":
        return ("demand over the last few hours has run above forecast" if up
                else "demand over the last few hours has run below forecast")
    label = str(d.get("feature_label") or f).strip()
    return f"{label[0].lower() + label[1:]} {'pushes load up' if up else 'holds load down'} by about {gw}"


def why_red_rule(row, drivers):
    t = row["local"]
    ds = drivers.sort_values("rank").to_dict("records")
    up = [phrase(d, t.hour) for d in ds if d["direction"] == "raises"]
    down = [phrase(d, t.hour) for d in ds if d["direction"] != "raises"]
    s = (f"{t:%a} {hour_label(t)} is red (strain {row['strain_index']:.0f}/100): net load is forecast at "
         f"{row['net_load_used'] / 1000:.1f} GW")
    s += (" because " + ", and ".join(up[:2]) + ".") if up else ", high for this time of year."
    if down:
        s += f" {down[0][0].upper() + down[0][1:]}, but not enough."
    if row["spike_prob"] > 0.5:
        s += f" Price-spike risk is {row['spike_prob']:.0%}, which adds to the strain score."
    elif row["spike_prob"] >= AVOID_SPIKE:
        s += f" Price-spike risk is {row['spike_prob']:.0%}."
    return s[0].upper() + s[1:]


def rule_plan(h, drv):
    av = avoid_windows(h)
    best = best_blocks(h, k=3)
    night = best_blocks(h, hour_filter=lambda x: x >= 21 or x < 7, k=1)
    day = best_blocks(h, hour_filter=lambda x: 8 <= x < 18, k=1)
    red = h[h["level"] == "red"]
    why = {ts_key(r["target_ts"]): why_red_rule(r, drv[drv["target_ts"] == r["target_ts"]]) for _, r in red.iterrows()}

    tips = []
    # the worst two avoid windows, shown in time order
    top_av = sorted(sorted(av, key=lambda w: (-w["max_strain"], -w["max_spike_prob"]))[:2],
                    key=lambda w: w["start_local"])
    if top_av:
        labels = " and ".join(w["label"] for w in top_av)
        tips.append({"icon": "⚠️", "window": top_av[0]["label"],
                     "text": f"Hold off on laundry, the dishwasher and EV charging {labels}: strain reaches "
                             f"{max(w['max_strain'] for w in top_av):.0f}/100 and price-spike risk peaks at "
                             f"{max(w['max_spike_prob'] for w in top_av):.0%}."})
        # pre-condition before the first tight window that starts at least 2 h from now
        first_local = h["local"].iloc[0]
        later = [w for w in top_av if pd.Timestamp(w["start_local"]) >= first_local + pd.Timedelta(hours=2)]
        if later:
            start = pd.Timestamp(later[0]["start_local"])
            tips.append({"icon": "🌡️", "window": f"before {start:%a} {hour_label(start)}",
                         "text": f"Pre-cool or pre-heat your home a degree or two before {start:%a} "
                                 f"{hour_label(start)}, then let the thermostat coast through the tight hours."})
    if night:
        n = night[0]
        tips.append({"icon": "🚗", "window": n["label"],
                     "text": f"Charge your EV {n['label']}: strain about {n['avg_strain']:.0f}/100 and spike risk "
                             f"at most {max(n['max_spike_prob'], 0.01):.0%}."})
    if day:
        d = day[0]
        tips.append({"icon": "👕", "window": d["label"],
                     "text": f"Run laundry, the dishwasher or the pool pump {d['label']}, one of the calmest daytime "
                             f"stretches (strain about {d['avg_strain']:.0f}/100)."})
    if not av:
        tips.insert(0, {"icon": "✅", "window": "next 48 h",
                        "text": "No red hours forecast in the next 48 hours: the grid has room, so use energy "
                                "as you normally would."})
    if len(tips) < 2 and best:
        tips.append({"icon": "🔌", "window": best[0]["label"],
                     "text": f"The calmest stretch is {best[0]['label']} (strain about {best[0]['avg_strain']:.0f}/100)."})

    if top_av:
        b = (night or day or best or [None])[0]
        w = top_av[0]["label"]
        headline = (f"Tight grid {w}: shift big loads to {b['label']}." if b
                    else f"Tight grid {w}: shift big loads out of it.")
    elif (h["level"] == "yellow").any():
        headline = f"Mostly manageable grid: best hours are {best[0]['label']}." if best else "Mostly manageable grid."
    else:
        headline = "Easy grid ahead: no strain expected in the next 48 hours."

    best_rows = sorted({r for w in best + night + day for r in w["_rows"]})
    avoid_rows = sorted({r for w in av for r in w["_rows"]})
    clean = lambda ws: [{k: v for k, v in w.items() if not k.startswith("_")} for w in ws]
    return {
        "headline": headline, "tips": tips[:5], "why_red": why,
        "best_hours": [h["local_time"].iloc[r] for r in best_rows],
        "avoid_hours": [h["local_time"].iloc[r] for r in avoid_rows],
        "best_windows": clean(sorted({w["start_local"]: w for w in best + night + day}.values(),
                                     key=lambda w: w["start_local"])),
        "avoid_windows": clean(av),
    }

# COMMAND ----------

# MAGIC %md ## 3 · Gemini (optional) + shape validation

# COMMAND ----------

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "tips": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "icon": {"type": "STRING"}, "text": {"type": "STRING"}, "window": {"type": "STRING"}},
            "required": ["icon", "text", "window"]}},
        "why_red": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "target_ts": {"type": "STRING"}, "sentence": {"type": "STRING"}}, "required": ["target_ts", "sentence"]}},
    },
    "required": ["headline", "tips", "why_red"],
}

PROMPT = """You are GridWise, a friendly energy coach for Texas households on the ERCOT grid.
Below is GridWise's 48-hour forecast as JSON. Times are America/Chicago. strain is 0-100 (green < 60, yellow 60-85,
red > 85); spike_pct is the model's chance that the real-time price tops $100/MWh. best_windows and avoid_windows were
computed from the models: recommend ONLY those windows and copy their labels exactly into "window".
red_hour_facts lists, for each red hour, plain-language facts about its top model drivers. Net load = demand minus
wind and solar, i.e. what gas and other plants must cover; low wind or no sun means more of it.

Write JSON with:
- headline: one short sentence, max 90 characters, naming the single most important window to avoid and the
  best window to use (e.g. "Tight evening Sat 3 PM–Sun 1 AM: charge and wash Mon 1 AM–4 AM instead.").
- tips: 3 to 5 practical actions (EV charging, laundry/dishwasher, thermostat pre-cooling or pre-heating, pool pump,
  avoiding the red window). Each: icon = exactly one of {icons}; text max 160 characters, concrete and friendly;
  window = a label from best_windows/avoid_windows (or "before <time>" for pre-cooling, where <time> is the start
  of an avoid window at least 2 hours after now_local; skip the pre-cooling tip if there is none).
- why_red: one entry per red hour in red_hour_facts (target_ts copied exactly): one sentence, max 30 words, plain
  English, explaining why that hour is strained from its facts (e.g. "Wind drops to 4.5 GW just as the sun sets,
  so gas plants must cover a 47 GW evening peak."). No jargon: never say SHAP, driver, model, feature or forecast
  "raises demand".
Do not invent numbers that are not in the data. Round GW to one decimal.

DATA:
{data}"""


def gemini_input(h, drv, plan, date_local):
    red_ts = set(plan["why_red"])
    hours = [{"ts": ts_key(r["target_ts"]), "t": f"{r['local']:%a} {hour_label(r['local'])}",
              "net_load_gw": round(r["net_load_used"] / 1000, 1), "strain": round(float(r["strain_index"])),
              "level": r["level"], "spike_pct": round(100 * float(r["spike_prob"]))} for _, r in h.iterrows()]
    rd = {}
    for _, r in h[h["level"] == "red"].iterrows():
        g = drv[drv["target_ts"] == r["target_ts"]].sort_values("rank")
        rd[ts_key(r["target_ts"])] = {
            "t": f"{r['local']:%a} {hour_label(r['local'])}", "net_load_gw": round(r["net_load_used"] / 1000, 1),
            "spike_pct": round(100 * float(r["spike_prob"])),
            "facts": [phrase(x, r["local"].hour) + f" (effect {x['shap_mw'] / 1000:+.1f} GW)"
                      for x in g.to_dict("records")]}
    return {"date_local": date_local, "now_local": f"{h['local'].iloc[0]:%a} {hour_label(h['local'].iloc[0])}",
            "hours": hours,
            "best_windows": [{k: w[k] for k in ("label", "avg_strain", "max_spike_prob")} for w in plan["best_windows"]],
            "avoid_windows": [{k: w[k] for k in ("label", "max_strain", "max_spike_prob")}
                              for w in plan["avoid_windows"]],
            "red_hour_facts": rd}


def call_gemini(api_key, payload, date_local):
    body = {
        "contents": [{"role": "user", "parts": [{"text": PROMPT.format(
            date_local=date_local, icons=" ".join(ICONS), data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": RESPONSE_SCHEMA,
                             "temperature": 0.4, "maxOutputTokens": 8192, "thinkingConfig": {"thinkingBudget": 0}},
    }
    last = None
    for attempt in range(3):
        try:
            r = requests.post(GEMINI_URL, headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                              json=body, timeout=90)
        except requests.RequestException as e:
            last = f"error: {type(e).__name__}"
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            cand = r.json().get("candidates") or [{}]
            parts = (cand[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts)
            return json.loads(text), "ok"
        last = f"error: HTTP {r.status_code}"
        if r.status_code not in (429, 500, 502, 503, 504):
            break
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(last or "error: unknown")


_CTL = re.compile(r"[\x00-\x1f\x7f]")
EN_DASH = "\u2013"


def scrub(o):
    """Gemini sometimes returns the en dash in our window labels as a control char (seen: backspace, i.e. a
    mangled \\u2013). Map backspace back to an en dash and other control chars to a space, recursively."""
    if isinstance(o, str):
        return re.sub(r" {2,}", " ", _CTL.sub(lambda m: EN_DASH if m.group() == "\b" else " ", o))
    if isinstance(o, list):
        return [scrub(x) for x in o]
    if isinstance(o, dict):
        return {k: scrub(v) for k, v in o.items()}
    return o


def validate_gemini(out, red_keys):
    """Returns (headline, tips, why_red dict) or raises ValueError with a reason."""
    out = scrub(out)
    if not isinstance(out, dict):
        raise ValueError("not an object")
    headline = out.get("headline")
    if not isinstance(headline, str) or not 5 <= len(headline.strip()) <= 200:
        raise ValueError("bad headline")
    if len(headline.strip()) > 120:          # too long for the panel: caller keeps the rule headline
        headline = None
    tips = out.get("tips")
    if not isinstance(tips, list) or not 2 <= len(tips) <= 6:
        raise ValueError("bad tips length")
    clean = []
    for t in tips:
        if not isinstance(t, dict) or not isinstance(t.get("text"), str) or not 5 <= len(t["text"].strip()) <= 300:
            raise ValueError("bad tip")
        icon = t.get("icon") if t.get("icon") in ICONS else "💡"
        clean.append({"icon": icon, "text": t["text"].strip(), "window": str(t.get("window") or "").strip()[:60]})
    why = {}
    for w in out.get("why_red") or []:
        try:
            t = pd.Timestamp(w["target_ts"])
            k = ts_key(t.tz_convert("UTC").tz_localize(None) if t.tzinfo is not None else t)
        except Exception:
            continue
        s = w.get("sentence")
        if k in red_keys and isinstance(s, str) and 10 <= len(s.strip()) <= 400:
            why[k] = s.strip()
    return (headline.strip() if headline else None), clean[:5], why

# COMMAND ----------

# MAGIC %md ## 4 · Build the plan

# COMMAND ----------

h = build_frame(fc)
date_local = (run_ts.tz_localize("UTC").tz_convert(TZ) + pd.Timedelta(days=1)).date()
plan = rule_plan(h, drv)
red_keys = set(plan["why_red"])

api_key = None
try:
    api_key = dbutils.secrets.get("gridwise", "gemini_api_key")
except Exception:
    api_key = None
api_key = api_key or os.environ.get("GEMINI_API_KEY") or None   # env fallback is for local dev runs only

generated_by, why_red_source, gemini_status = "rules", "rules", "no_secret"
headline, tips, why_red = plan["headline"], plan["tips"], dict(plan["why_red"])
if api_key:
    try:
        raw, gemini_status = call_gemini(api_key, gemini_input(h, drv, plan, str(date_local)), str(date_local))
        g_head, g_tips, g_why = validate_gemini(raw, red_keys)
        headline, tips, generated_by = g_head or headline, g_tips, "gemini"
        why_red.update(g_why)
        why_red_source = "gemini" if len(g_why) == len(red_keys) else ("gemini+rules" if g_why else "rules")
    except ValueError as e:
        gemini_status = f"invalid: {str(e)[:120]}"
    except Exception as e:
        gemini_status = re.sub(r"[A-Za-z0-9_\-\.]{30,}", "<redacted>", str(e))[:160]
print(f"generated_by={generated_by} why_red_source={why_red_source} gemini_status={gemini_status}")
print("headline:", headline)
for t in tips:
    print(" ", t["icon"], t["window"], "|", t["text"])
for k in sorted(why_red)[:4]:
    print("  why", k, why_red[k])

# COMMAND ----------

# MAGIC %md ## 5 · Write (replace this `run_ts`)

# COMMAND ----------

SCHEMA = """run_ts TIMESTAMP, date_local DATE, generated_by STRING, model STRING, headline STRING, tips_json STRING,
  best_hours_json STRING, avoid_hours_json STRING, best_windows_json STRING, avoid_windows_json STRING,
  why_red_json STRING, why_red_source STRING, gemini_status STRING, created_at TIMESTAMP"""
spark.sql(f"CREATE TABLE IF NOT EXISTS {TABLE} ({SCHEMA}) USING DELTA "
          f"COMMENT 'GridWise daily plan + Why Red? sentences, one row per run_ts; written by ml/09_advice'")
dump = lambda o: json.dumps(o, ensure_ascii=False)
row = (run_ts.to_pydatetime(), date_local, generated_by, GEMINI_MODEL if generated_by == "gemini" else "rules_v1",
       headline, dump(tips), dump(plan["best_hours"]), dump(plan["avoid_hours"]), dump(plan["best_windows"]),
       dump(plan["avoid_windows"]), dump(why_red), why_red_source, gemini_status,
       datetime.now(timezone.utc).replace(tzinfo=None))
sdf = spark.createDataFrame([row], SCHEMA.replace("\n", " "))
spark.sql(f"DELETE FROM {TABLE} WHERE run_ts = TIMESTAMP '{run_ts_sql}'")
sdf.select(*spark.table(TABLE).columns).write.mode("append").saveAsTable(TABLE)

# COMMAND ----------

# MAGIC %md ## 6 · Validation (read back)

# COMMAND ----------

back = spark.sql(f"SELECT * FROM {TABLE} WHERE run_ts = TIMESTAMP '{run_ts_sql}'").toPandas()
b = back.iloc[0]
tips_b, best_b, avoid_b = json.loads(b["tips_json"]), json.loads(b["best_hours_json"]), json.loads(b["avoid_hours_json"])
why_b = json.loads(b["why_red_json"])
local_set = set(h["local_time"])
red_local = set(h.loc[h["level"] == "red", "local_time"])


def chk(value, ok):
    return {"value": value if not isinstance(value, float) else round(value, 4), "pass": bool(ok)}


checks = {
    "one_row_per_run_ts": chk(len(back), len(back) == 1),
    "generated_by_valid": chk(b["generated_by"], b["generated_by"] in ("gemini", "rules")),
    "headline_ok": chk(len(b["headline"] or ""), 5 <= len(b["headline"] or "") <= 200),
    "tips_shape": chk(len(tips_b), 1 <= len(tips_b) <= 6 and all(
        isinstance(t, dict) and set(t) == {"icon", "text", "window"} and t["icon"] in ICONS and t["text"]
        for t in tips_b)),
    "best_hours_in_forecast": chk(len(best_b), set(best_b) <= local_set),
    "avoid_hours_in_forecast": chk(len(avoid_b), set(avoid_b) <= local_set),
    "best_avoid_disjoint": chk(len(set(best_b) & set(avoid_b)), not set(best_b) & set(avoid_b)),
    "no_red_in_best": chk(len(set(best_b) & red_local), not set(best_b) & red_local),
    "why_red_covers_red_hours": chk({"red": len(red_keys), "sentences": len(why_b)},
                                    set(why_b) == red_keys and all(isinstance(s, str) and s for s in why_b.values())),
    "date_local_is_tomorrow": chk(str(b["date_local"]), str(b["date_local"]) == str(date_local)),
}
# Data / time-of-day dependent: reported, never fail the task.
warnings = {
    "best_hours_nonempty": chk(len(best_b), len(best_b) > 0),
    "tips_at_least_2": chk(len(tips_b), len(tips_b) >= 2),
    "gemini_used": chk(gemini_status, b["generated_by"] == "gemini"),
}
failed = [k for k, v in checks.items() if not v["pass"]]
warned = [k for k, v in warnings.items() if not v["pass"]]
summary = {
    **checks,
    "all_pass": not failed,
    "failed": failed,
    "warnings": warnings,
    "warned": warned,
    "run_ts": str(run_ts),
    "table": TABLE,
    "generated_by": generated_by,
    "why_red_source": why_red_source,
    "gemini_status": gemini_status,
    "headline": headline,
    "tips": tips,
    "best_windows": [w["label"] for w in plan["best_windows"]],
    "avoid_windows": [w["label"] for w in plan["avoid_windows"]],
    "why_red_example": next(iter(sorted(why_red.items())), None),
}
print(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
assert not failed, f"failed hard checks: {failed}"   # warnings never fail the task

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary, ensure_ascii=False, default=str))
