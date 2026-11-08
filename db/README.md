# db/: Serving Database (Tiger Data)

> **Status:** Phase 5.1–5.2 built. `schema.sql` + `sync.py` run against the live Tiger service.

The website never queries Databricks directly. After each pipeline run the latest Gold results are copied into
**Tiger Data** (TimescaleDB 2.31 on Postgres 18), which serves the API in milliseconds.

| File | Purpose |
|---|---|
| `schema.sql` | Idempotent DDL: hypertables, the `actuals_daily` continuous aggregate + refresh policy |
| `sync.py` | `python -m db.sync`: applies the schema, then upserts Gold → Tiger and prints row counts |

## Run

```bash
cd "C:\Users\Ayman\OneDrive\Desktop\TamuHack 26"
PYTHONIOENCODING=utf-8 .venv/Scripts/python -m db.sync                 # everything (~15 s)
PYTHONIOENCODING=utf-8 .venv/Scripts/python -m db.sync --skip-actuals  # hourly fast path
PYTHONIOENCODING=utf-8 .venv/Scripts/python -m db.sync --schema-only
PYTHONIOENCODING=utf-8 .venv/Scripts/python -m db.sync --if-newer      # no-op unless there is something new
```

`--if-newer` syncs only when the newest finished run of `DATABRICKS_JOB_ID` ended after the last `sync_log` row
(Jobs API, no compute) or `max(gold.forecasts.run_ts)` is newer than Tiger's. The API runs the same check in the
background (`backend/app/refresh.py`, every `AUTO_SYNC_MINUTES`, default 5), so Tiger refreshes itself after each
Job run while the API is up. `forecasts.created_at` (= `gold.forecasts.created_at`, when 05_predict wrote the
batch) is what `/api/health` measures forecast age from.

Needs in `.env`: `TIGER_DATABASE_URL`, `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_WAREHOUSE_ID`
(optional `GRIDWISE_CATALOG`, default `grid`; `SPIKE_PRICE_THRESHOLD`, default 100). Reads go through the SQL
warehouse only (no notebook compute). Exit code 1 if any table failed; the others still sync.

## Tables

| Tiger table | Source (Gold) | Key | Sync rule |
|---|---|---|---|
| `forecasts` (hypertable on `target_ts`, 7-day chunks) | `gold.forecasts` | `(target_ts, run_ts)` | every batch within 7 days of the newest `run_ts`, replaced per `run_ts`; older batches deleted |
| `forecast_drivers` | `gold.forecast_drivers` | `(run_ts, target_ts, rank)` | same batches as forecasts |
| `daily_advice` (jsonb `tips`, `best_hours`, `avoid_hours`, `why_red`, `raw`) | `gold.daily_advice` *if it exists* | `date_local` | latest row per date, upsert |
| `shift_scenarios` | `gold.shift_scenarios` *if it exists* | `(run_ts, participation_pct, kwh_per_home, from_window, to_window)` | latest `run_ts` only (table replaced) |
| `shift_scenario_curves` | `gold.shift_scenario_curves` *if it exists*, or a `curve` JSON column on `shift_scenarios` | scenario key + `target_ts` | latest `run_ts` only |
| `report_card` | `gold.report_card` | `(date, source)` | upsert all |
| `strain_reference` | `gold.strain_reference` | `(month, pct)` | upsert all (API uses it to re-score what-if curves) |
| `actuals` (hypertable on `ts`, 30-day chunks) | `silver.grid_hourly` ⨝ `gold.strain_hourly` ⨝ `gold.spike_events` | `ts` | last 400 days, upsert |
| `actuals_daily` (continuous aggregate) | `actuals`, buckets of 1 day in `America/Chicago` | `day` | refreshed by sync over the synced range; policy refreshes the last 10 days hourly |
| `sync_log` | — | — | one row per sync with counts / errors |

### Column names sync accepts from the Phase 4 Gold tables

These tables are built in parallel (4.1 / 4.3), so `sync.py` maps several spellings:

- **`gold.daily_advice`**: `date_local` | `date`; `run_ts`; `generated_by` (`gemini`/`rules`); `headline` (else the
  first line of `advice_md`); `tips` (JSON array of `{icon, text, window}` or strings); `best_hours`, `avoid_hours`
  (`best_hours_json` etc.: JSON array of local ISO times); `why_red` (JSON object or MAP `target_ts → sentence`).
- **`gold.shift_scenarios`**: `run_ts`, `participation_pct` | `pct`, `kwh_per_home` | `kwh`, `from_window`,
  `to_window` (`'16-20'`, `'22-02'`, local hours, end exclusive; normalised to 2 digits), `red_hours_before/after`,
  `peak_mw_before/after`, `peak_reduction_mw`, `spike_prob_before/after` | `max_spike_before/after` (max over the 48 h), `peakers_avoided`.
- **`gold.shift_scenario_curves`**: scenario key + `target_ts`, `before_mw`, `after_mw`, `level_before`,
  `level_after`, `spike_before`, `spike_after`.

## Notes
- DDL runs one statement at a time in autocommit (continuous aggregates can't be created in a transaction).
- Bulk loads use `COPY` into a temp table + `INSERT … ON CONFLICT`, so reruns never duplicate.
- Re-running `schema.sql` is safe (`IF NOT EXISTS` / `if_not_exists => TRUE` everywhere).
