"""Sync Gold (Databricks) -> Tiger Data (TimescaleDB) for the website.

    python -m db.sync                 # apply schema, sync everything, print row counts
    python -m db.sync --skip-actuals  # faster: forecasts / drivers / advice / scenarios / report card only
    python -m db.sync --schema-only
    python -m db.sync --if-newer      # no-op unless the Job finished / Gold has a newer batch since the last sync

Reads Databricks through the SQL warehouse (DATABRICKS_HOST / TOKEN / WAREHOUSE_ID) and writes
Tiger through TIGER_DATABASE_URL. Gold tables that do not exist yet (daily_advice, shift_scenarios,
shift_scenario_curves) are skipped with a note. Every write is idempotent (replace-by-key / upsert).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from ingestion.config import get_settings

SCHEMA = Path(__file__).with_name("schema.sql")
FORECAST_KEEP_DAYS = 7
ACTUALS_DAYS = 400


# ----------------------------------------------------------------------------- Databricks
def _catalog() -> str:
    return os.getenv("GRIDWISE_CATALOG") or "grid"


def dbx_query(sql: str) -> tuple[list[str], list[list]]:
    """Like tools.sql.query, but follows every result chunk (large tables)."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    s = get_settings()
    w = WorkspaceClient(host=s.databricks_host, token=s.databricks_token)
    wid = os.getenv("DATABRICKS_WAREHOUSE_ID") or next(iter(w.warehouses.list())).id
    r = w.statement_execution.execute_statement(statement=sql, warehouse_id=wid, wait_timeout="50s")
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{r.status.state}: {r.status.error.message if r.status.error else ''}")
    cols = [c.name for c in r.manifest.schema.columns]
    rows = list((r.result.data_array or []) if r.result else [])
    nxt = r.result.next_chunk_index if r.result else None
    while nxt is not None:
        chunk = w.statement_execution.get_statement_result_chunk_n(r.statement_id, nxt)
        rows.extend(chunk.data_array or [])
        nxt = chunk.next_chunk_index
    return cols, rows


def dbx_dicts(sql: str) -> list[dict]:
    cols, rows = dbx_query(sql)
    return [dict(zip(cols, row)) for row in rows]


def gold_tables() -> set[str]:
    _, rows = dbx_query(f"SHOW TABLES IN {_catalog()}.gold")
    return {r[1] for r in rows}


# ----------------------------------------------------------------------------- value helpers
def clean(v):
    """Statement API returns strings; turn NaN/Inf into NULL, keep the rest as text for Postgres."""
    if v is None:
        return None
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, str) and v.strip().lower() in ("nan", "inf", "-inf", "infinity", "-infinity", ""):
        return None
    return v


def utc_text(v):
    """Gold TIMESTAMP columns come back naive (session tz is UTC); tag them so Postgres never reads local time."""
    v = clean(v)
    if isinstance(v, str) and not re.search(r"(Z|[+-]\d\d:?\d\d)$", v):
        return v + "Z"
    return v


def num(v):
    v = clean(v)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pick(row: dict, *names, default=None):
    for n in names:
        if n in row and clean(row[n]) is not None:
            return row[n]
    return default


def as_json(v, default):
    v = clean(v)
    if v is None:
        return default
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default


def norm_window(v) -> str | None:
    """'16-20', '16–20', '4pm-8pm', [16, 20] -> '16-20' (local hours, end exclusive)."""
    v = clean(v)
    if v is None:
        return None
    if isinstance(v, (list, tuple)) and len(v) == 2:
        a, b = v
    else:
        s = str(v).strip().lower().replace("–", "-").replace(" ", "").replace("to", "-")
        m = re.match(r"^\[?\"?(\d{1,2})(am|pm)?[-,:\"]+(\d{1,2})(am|pm)?\]?$", s)
        if not m:
            return str(v)
        a, b = int(m.group(1)), int(m.group(3))
        if m.group(2) == "pm" and a < 12:
            a += 12
        if m.group(4) == "pm" and b < 12:
            b += 12
    return f"{int(a) % 24:02d}-{int(b) % 24:02d}"


# ----------------------------------------------------------------------------- Tiger helpers
def tiger() -> psycopg.Connection:
    url = os.getenv("TIGER_DATABASE_URL")
    if not url:
        sys.exit("TIGER_DATABASE_URL is not set")
    return psycopg.connect(url, autocommit=True, connect_timeout=15)


def apply_schema(conn: psycopg.Connection) -> None:
    text = SCHEMA.read_text(encoding="utf-8")
    text = "\n".join(line for line in text.splitlines() if not line.strip().startswith("--"))
    for stmt in re.split(r";\s*\n", text):
        if stmt.strip():
            conn.execute(stmt)


def copy_rows(cur: psycopg.Cursor, table: str, cols: list[str], rows: list[tuple]) -> None:
    with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)


def upsert(conn: psycopg.Connection, table: str, cols: list[str], key: list[str], rows: list[tuple]) -> int:
    """COPY into a temp table, then INSERT .. ON CONFLICT (key) DO UPDATE."""
    if not rows:
        return 0
    upd = [c for c in cols if c not in key]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in upd) + ", synced_at = now()" if upd else ""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE _stage (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
        copy_rows(cur, "_stage", cols, rows)
        conflict = f"DO UPDATE SET {set_clause}" if upd else "DO NOTHING"
        cur.execute(f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _stage "
                    f"ON CONFLICT ({', '.join(key)}) {conflict}")
    return len(rows)


def replace_where(conn, table: str, where: str, params, cols: list[str], rows: list[tuple]) -> int:
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(f"DELETE FROM {table} WHERE {where}", params)
        if rows:
            copy_rows(cur, table, cols, rows)
    return len(rows)


# ----------------------------------------------------------------------------- sync steps
def sync_forecasts(conn) -> dict:
    c = _catalog()
    fc = dbx_dicts(f"""
        SELECT * FROM {c}.gold.forecasts
        WHERE run_ts >= (SELECT max(run_ts) FROM {c}.gold.forecasts) - INTERVAL {FORECAST_KEEP_DAYS} DAYS
        ORDER BY run_ts, target_ts""")
    cols = ["run_ts", "target_ts", "horizon_h", "net_load_mw", "demand_mw", "band_low_mw", "band_high_mw",
            "net_load_p10", "net_load_p50", "net_load_p90", "strain_index", "level", "spike_prob",
            "low_confidence", "strain_source", "band_source", "wind_fcst_mw", "solar_fcst_mw", "local_month",
            "created_at"]
    rows = [tuple(clean(x) for x in (
        r["run_ts"], r["target_ts"], r["horizon_h"], pick(r, "net_load_used", "net_load_p50"),
        r.get("demand_p50"), r.get("band_low"), r.get("band_high"), r.get("net_load_p10"),
        r.get("net_load_p50"), r.get("net_load_p90"), r.get("strain_index"), r.get("level"),
        r.get("spike_prob"), r.get("low_confidence"), r.get("strain_source"), r.get("band_source"),
        r.get("wind_fcst_mw"), r.get("solar_fcst_mw"), r.get("local_month"), utc_text(r.get("created_at"))))
        for r in fc]
    runs = sorted({r[0] for r in rows})
    n = replace_where(conn, "forecasts", "run_ts = ANY(%s::timestamptz[])", (runs,), cols, rows) if runs else 0

    dr = dbx_dicts(f"""
        SELECT run_ts, target_ts, rank, feature, feature_label, feature_value, shap_mw, direction, driver_source
        FROM {c}.gold.forecast_drivers
        WHERE run_ts >= (SELECT max(run_ts) FROM {c}.gold.forecasts) - INTERVAL {FORECAST_KEEP_DAYS} DAYS""")
    dcols = ["run_ts", "target_ts", "rank", "feature", "label", "value", "shap_mw", "direction", "driver_source"]
    drows = [tuple(clean(r[k]) for k in ("run_ts", "target_ts", "rank", "feature", "feature_label",
                                         "feature_value", "shap_mw", "direction", "driver_source")) for r in dr]
    druns = sorted({r[0] for r in drows})
    nd = replace_where(conn, "forecast_drivers", "run_ts = ANY(%s::timestamptz[])", (druns,), dcols, drows) \
        if druns else 0

    # retention: keep FORECAST_KEEP_DAYS of batches behind the newest
    for t in ("forecasts", "forecast_drivers"):
        conn.execute(f"DELETE FROM {t} WHERE run_ts < (SELECT max(run_ts) FROM forecasts) "
                     f"- INTERVAL '{FORECAST_KEEP_DAYS} days'")
    return {"forecasts": n, "forecast_batches": len(runs), "forecast_drivers": nd}


def sync_report_card(conn) -> dict:
    rc = dbx_dicts(f"SELECT * FROM {_catalog()}.gold.report_card")
    cols = ["date", "source", "mape", "demand_mape", "wmape", "spike_recall", "spike_precision",
            "spike_hours_actual", "spike_hours_caught", "band_coverage", "n_hours", "basis"]
    rows = [tuple(clean(r.get(k)) for k in cols) for r in rc]
    return {"report_card": upsert(conn, "report_card", cols, ["date", "source"], rows)}


def sync_strain_reference(conn) -> dict:
    ref = dbx_dicts(f"SELECT month, pct, net_load_mw FROM {_catalog()}.gold.strain_reference")
    rows = [(r["month"], int(float(r["pct"])), r["net_load_mw"]) for r in ref if clean(r["net_load_mw"]) is not None]
    return {"strain_reference": upsert(conn, "strain_reference", ["month", "pct", "net_load_mw"],
                                       ["month", "pct"], rows)}


def sync_actuals(conn) -> dict:
    c = _catalog()
    thr = float(os.getenv("SPIKE_PRICE_THRESHOLD") or 100)
    act = dbx_query(f"""
        SELECT s.ts_utc, s.demand_mw, s.wind_mw, s.solar_mw, s.net_load_mw, s.price_usd_mwh,
               st.strain_index, st.level,
               coalesce(CAST(se.is_spike AS BOOLEAN), s.price_usd_mwh > {thr}) AS is_spike
        FROM {c}.silver.grid_hourly s
        LEFT JOIN {c}.gold.strain_hourly st ON st.ts_utc = s.ts_utc AND NOT st.is_forecast_row
        LEFT JOIN {c}.gold.spike_events se ON se.ts_utc = s.ts_utc
        WHERE NOT s.is_forecast_row AND s.ts_utc >= current_timestamp() - INTERVAL {ACTUALS_DAYS} DAYS""")[1]
    cols = ["ts", "demand_mw", "wind_mw", "solar_mw", "net_load_mw", "price_usd_mwh", "strain_index",
            "level", "is_spike"]
    rows = [tuple(clean(x) for x in r) for r in act]
    n = upsert(conn, "actuals", cols, ["ts"], rows)
    if rows:
        lo = min(r[0] for r in rows)
        conn.execute("CALL refresh_continuous_aggregate('actuals_daily', %s::timestamptz - INTERVAL '1 day', "
                     "now() + INTERVAL '1 day')", (lo,))
    return {"actuals": n}


def sync_advice(conn, tables: set[str]) -> dict:
    if "daily_advice" not in tables:
        return {"daily_advice": "skipped (gold.daily_advice not found)"}
    rows_in = dbx_dicts(f"SELECT * FROM {_catalog()}.gold.daily_advice")
    latest: dict[str, dict] = {}
    for r in rows_in:
        d = str(pick(r, "date_local", "date", "advice_date", default=""))[:10]
        if not d:
            continue
        rts = str(pick(r, "run_ts", "generated_at", "created_at", default=""))
        if d not in latest or rts >= str(pick(latest[d], "run_ts", "generated_at", "created_at", default="")):
            latest[d] = r
    out = []
    for d, r in latest.items():
        headline = pick(r, "headline", "title")
        md = pick(r, "advice_md", "advice", "advice_text")
        if not headline and md:
            headline = str(md).strip().splitlines()[0].lstrip("#* ").strip()
        tips = as_json(pick(r, "tips", "tips_json"), [])
        tips = [t if isinstance(t, dict) else {"icon": "tip", "text": str(t), "window": None} for t in tips]
        tips = [{"icon": t.get("icon") or "tip", "text": t.get("text") or "", "window": t.get("window")} for t in tips]
        why = as_json(pick(r, "why_red", "why_red_json"), {})
        if isinstance(why, list):  # list of {target_ts, sentence} / [k, v]
            why = {str(x.get("target_ts") if isinstance(x, dict) else x[0]):
                   (x.get("sentence") or x.get("text") if isinstance(x, dict) else x[1]) for x in why}
        raw = {k: clean(v) for k, v in r.items()}
        out.append((d, clean(pick(r, "run_ts", "generated_at")), str(pick(r, "generated_by", "source", default="gemini")),
                    headline, Jsonb(tips), Jsonb(as_json(pick(r, "best_hours", "best_hours_json", "best_hours_local"), [])),
                    Jsonb(as_json(pick(r, "avoid_hours", "avoid_hours_json", "avoid_hours_local"), [])), Jsonb(why), Jsonb(raw)))
    cols = ["date_local", "run_ts", "generated_by", "headline", "tips", "best_hours", "avoid_hours", "why_red", "raw"]
    # Jsonb values need a binary/adapted path, so use executemany instead of COPY text here
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO daily_advice ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
            "ON CONFLICT (date_local) DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[1:]) +
            ", synced_at = now()", out)
    return {"daily_advice": len(out)}


SCEN_KEYS = ["run_ts", "participation_pct", "kwh_per_home", "from_window", "to_window"]


def _scen_key(r: dict) -> tuple:
    return (clean(r.get("run_ts")),
            num(pick(r, "participation_pct", "pct", "participation")),
            num(pick(r, "kwh_per_home", "kwh", "kwh_shifted")),
            norm_window(pick(r, "from_window", "from_win", "shift_from", "window_from", "from_hours")),
            norm_window(pick(r, "to_window", "to_win", "shift_to", "window_to", "to_hours")))


def sync_scenarios(conn, tables: set[str]) -> dict:
    if "shift_scenarios" not in tables:
        return {"shift_scenarios": "skipped (gold.shift_scenarios not found)"}
    c = _catalog()
    sc = dbx_dicts(f"SELECT * FROM {c}.gold.shift_scenarios "
                   f"WHERE run_ts = (SELECT max(run_ts) FROM {c}.gold.shift_scenarios)")
    cols = SCEN_KEYS + ["red_hours_before", "red_hours_after", "peak_mw_before", "peak_mw_after",
                        "peak_reduction_mw", "spike_prob_before", "spike_prob_after", "peakers_avoided"]
    rows, embedded_curves = [], []
    for r in sc:
        k = _scen_key(r)
        if None in k:
            continue
        rows.append(k + tuple(clean(x) for x in (
            pick(r, "red_hours_before"), pick(r, "red_hours_after"),
            pick(r, "peak_mw_before", "peak_before_mw", "peak_net_load_before"),
            pick(r, "peak_mw_after", "peak_after_mw", "peak_net_load_after"),
            pick(r, "peak_reduction_mw"),
            pick(r, "spike_prob_before", "max_spike_before", "max_spike_prob_before", "spike_before"),
            pick(r, "spike_prob_after", "max_spike_after", "max_spike_prob_after", "spike_after"),
            pick(r, "peakers_avoided"))))
        for p in as_json(pick(r, "curve", "curve_json"), []) or []:
            if isinstance(p, dict):
                embedded_curves.append(k + tuple(clean(p.get(x)) for x in (
                    "target_ts", "before_mw", "after_mw", "level_before", "level_after", "spike_before", "spike_after")))
    # the table holds only the latest scenario grid
    n = replace_where(conn, "shift_scenarios", "TRUE", None, cols, rows)

    ccols = SCEN_KEYS + ["target_ts", "before_mw", "after_mw", "level_before", "level_after",
                         "spike_before", "spike_after"]
    curves = embedded_curves
    note = "embedded" if curves else None
    if not curves and "shift_scenario_curves" in tables:
        cv = dbx_dicts(f"SELECT * FROM {c}.gold.shift_scenario_curves "
                       f"WHERE run_ts = (SELECT max(run_ts) FROM {c}.gold.shift_scenario_curves)")
        for r in cv:
            k = _scen_key(r)
            if None in k:
                continue
            curves.append(k + tuple(clean(x) for x in (
                r.get("target_ts"), pick(r, "before_mw", "net_load_before_mw", "net_load_before"),
                pick(r, "after_mw", "net_load_after_mw", "net_load_after"), r.get("level_before"),
                r.get("level_after"), pick(r, "spike_before", "spike_prob_before"),
                pick(r, "spike_after", "spike_prob_after"))))
        note = "table"
    # dedupe on PK (last wins)
    curves = list({cv[:6]: cv for cv in curves}.values())
    nc = replace_where(conn, "shift_scenario_curves", "TRUE", None, ccols, curves)
    out = {"shift_scenarios": n, "shift_scenario_curves": nc}
    if not curves:
        out["shift_scenario_curves"] = "0 (gold.shift_scenario_curves not found / empty)"
    elif note:
        out["shift_scenario_curves_source"] = note
    return out


# ----------------------------------------------------------------------------- freshness checks
def last_job_end() -> tuple[datetime | None, str]:
    """End time of the newest finished run of DATABRICKS_JOB_ID (Jobs API: no compute). (None, why) if unknown."""
    s = get_settings()
    if not (s.job_id and s.has_databricks):
        return None, "DATABRICKS_JOB_ID not set"
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(host=s.databricks_host, token=s.databricks_token)
    for run in w.jobs.list_runs(job_id=int(s.job_id), completed_only=True, limit=1):
        if run.end_time:
            state = run.state.result_state.value if run.state and run.state.result_state else "?"
            return datetime.fromtimestamp(run.end_time / 1000, tz=timezone.utc), f"run {run.run_id} {state}"
    return None, "job has no finished runs"


def gold_latest_run_ts(conn) -> datetime | None:
    """max(run_ts) of gold.forecasts (one small SQL-warehouse query), parsed by Postgres."""
    _, rows = dbx_query(f"SELECT max(run_ts) FROM {_catalog()}.gold.forecasts")
    v = rows[0][0] if rows else None
    return conn.execute("SELECT %s::timestamptz", (v,)).fetchone()[0] if v else None


def sync_needed(conn, check_gold: bool = True) -> tuple[bool, str]:
    """True when the Job finished after the last sync, or Gold holds a newer forecast batch than Tiger."""
    last_sync = conn.execute("SELECT max(synced_at) FROM sync_log").fetchone()[0]
    tiger_run = conn.execute("SELECT max(run_ts) FROM forecasts").fetchone()[0]
    if last_sync is None or tiger_run is None:
        return True, "Tiger has never been synced"
    try:
        end, what = last_job_end()
        if end is not None and end > last_sync:
            return True, f"job {what} finished {end:%Y-%m-%d %H:%M}Z, after the last sync {last_sync:%H:%M}Z"
    except Exception as e:  # Jobs API trouble: fall through to the Gold check
        what = f"jobs API error {type(e).__name__}"
    if check_gold:
        gold_run = gold_latest_run_ts(conn)
        if gold_run is not None and gold_run > tiger_run:
            return True, f"gold run_ts {gold_run:%Y-%m-%d %H:%M}Z is newer than Tiger {tiger_run:%H:%M}Z"
    return False, f"up to date (Tiger run_ts {tiger_run:%Y-%m-%d %H:%M}Z, last sync {last_sync:%H:%M}Z; {what})"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema-only", action="store_true")
    ap.add_argument("--skip-actuals", action="store_true")
    ap.add_argument("--if-newer", action="store_true",
                    help="skip the sync unless the Job finished, or Gold has a newer forecast, since the last sync")
    a = ap.parse_args(argv)

    t0 = time.time()
    counts: dict = {}
    with tiger() as conn:
        apply_schema(conn)
        print("schema applied")
        if a.schema_only:
            return
        if a.if_newer:
            needed, why = sync_needed(conn)
            print(("syncing: " if needed else "skip: ") + why)
            if not needed:
                return
        tables = gold_tables()
        steps = [("forecasts", sync_forecasts), ("report_card", sync_report_card),
                 ("strain_reference", sync_strain_reference)]
        if not a.skip_actuals:
            steps.append(("actuals", sync_actuals))
        steps += [("daily_advice", lambda c: sync_advice(c, tables)),
                  ("shift_scenarios", lambda c: sync_scenarios(c, tables))]
        errors = []
        for name, fn in steps:
            try:
                res = fn(conn)
                counts.update(res)
                print(f"  {name:<18} {res}")
            except Exception as e:  # keep going: one failing table shouldn't block the rest
                errors.append(f"{name}: {type(e).__name__}: {e}")
                print(f"  {name:<18} FAILED: {type(e).__name__}: {e}")
        # Tiger-side totals
        for t in ("forecasts", "forecast_drivers", "daily_advice", "shift_scenarios", "shift_scenario_curves",
                  "report_card", "strain_reference", "actuals", "actuals_daily"):
            counts[f"tiger.{t}"] = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        latest = conn.execute("SELECT max(run_ts) FROM forecasts").fetchone()[0]
        conn.execute("INSERT INTO sync_log (counts, notes) VALUES (%s, %s)",
                     (Jsonb({k: (v if isinstance(v, (int, float)) else str(v)) for k, v in counts.items()}),
                      "; ".join(errors) or None))
    print("\nTiger row counts:")
    for k, v in counts.items():
        if k.startswith("tiger."):
            print(f"  {k[6:]:<24} {v}")
    print(f"latest forecast run_ts: {latest}")
    print(f"done in {time.time() - t0:.1f}s at {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
