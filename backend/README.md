# backend/: API (FastAPI)

> **Status:** Phase 5.3 built. Reads Tiger Data (filled by `python -m db.sync`), serves `/api/*`.

## Run locally

```bash
cd "C:\Users\Ayman\OneDrive\Desktop\TamuHack 26"
.venv/Scripts/python -m pip install -r backend/requirements.txt
PYTHONIOENCODING=utf-8 .venv/Scripts/python -m db.sync          # fill Tiger first
.venv/Scripts/python -m uvicorn backend.app.main:app --port 8000 # http://localhost:8000/api/docs
```

Docker (from the repo root): `docker build -f backend/Dockerfile -t gridwise-api .` then
`docker run --env-file .env -p 8000:8000 gridwise-api`.

**Env** (read from the process env, falling back to the repo-root `.env`):

| Var | Use |
|---|---|
| `TIGER_DATABASE_URL` | required: Postgres/Timescale URL |
| `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-2.5-flash`) | `/api/chat` (REST, key sent as `x-goog-api-key`) |
| `CORS_ORIGINS` | comma-separated, default `http://localhost:3000` |
| `RIPPLE_RESIDENTIAL_METERS` (default 10,000,000), `RIPPLE_PEAKER_MW` (default 100) | Ripple fallback estimator |
| `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_WAREHOUSE_ID`, `DATABRICKS_JOB_ID` | background Tiger refresh (below); without host/token it stays off |
| `AUTO_SYNC_MINUTES` (default 5; `0` = off), `GOLD_CHECK_MINUTES` (default 30) | refresh cadence |

**Background Tiger refresh** (`app/refresh.py`): a daemon thread asks the Jobs API (no compute) every
`AUTO_SYNC_MINUTES` whether the `gridwise-hourly` Job finished after the last sync; if so it runs
`python -m db.sync` in a subprocess. Only while the forecast is stale does it also query the SQL warehouse for
`max(gold.forecasts.run_ts)` (at most every `GOLD_CHECK_MINUTES`), to catch notebooks run outside the Job. A
Postgres advisory lock keeps multiple workers/instances from syncing at once; failures back off 30 min.

## Endpoints (contract)

| Method | Path | Source | Notes |
|---|---|---|---|
| GET | `/api/health` | `forecasts` | `status` is `ok` while the DB answers (`error` if not, `empty` before the first sync); the UI shows its stale banner from `forecast_age_minutes` (> 120), measured from `created_at` (when the pipeline wrote the batch), not from `run_ts` (the data anchor, ~3 h behind the clock) |
| GET | `/api/forecast?hours=48` | `forecasts` (latest `run_ts`) | `summary` (peak, max spike, level counts, best/avoid windows, verdict) is computed here. `band_low_mw`/`band_high_mw` are in **net-load space**: the stored gold demand band re-centred on `net_load_mw` (`net − (demand_p50 − band_low)`, `net + (band_high − demand_p50)`), so the band brackets the net-load bars; width is unchanged |
| GET | `/api/forecast/drivers?ts=` | `forecast_drivers` | `ts` optional (defaults to the highest-strain hour); 404 if not in the latest batch. `why_red` = Gemini sentence from `daily_advice` if present, else a rule sentence for red hours, else `null` |
| GET | `/api/advice` | `daily_advice` + rules | Gold advice row for tomorrow (local) if synced, gaps filled by the rule-based plan; else `generated_by: "rules"` |
| GET | `/api/history?days=30` | `actuals_daily` (continuous aggregate) | last N local days with data |
| GET | `/api/simulate?pct=5&kwh=3&from=16-20&to=22-02` | `shift_scenarios` + `shift_scenario_curves` | nearest precomputed scenario (same windows first, then closest pct/kWh). With no scenarios: estimate from the forecast (same maths as `frontend/src/lib/simulate.ts`, strain re-scored with `strain_reference`), `nearest_params: null` |
| GET | `/api/report-card?days=7` | `report_card` | one row per date (live preferred over backtest) |
| POST | `/api/chat` `{question}` | Gemini, grounded on the 48 h forecast + summary + advice | JSON-mode answer; `highlight_hours` filtered to real `target_ts` values. Answers cached 10 min per question/batch; on 429 Gemini is skipped for 30 s and a rule-based summary is returned |

Conventions: `target_ts`/`run_ts` are UTC `…Z`; `local_time`, `start_local`, `end_local`, `best_hours`,
`avoid_hours` are `America/Chicago` with offset. Window labels look like `10 am – 2 pm` (end exclusive).
Tip icons are lucide names: `snowflake`, `shirt`, `car`, `plug` (Gemini rows may add others).
Window semantics and verdict text mirror `frontend/scripts/export_fixtures.py`, so fixtures and live data match.

## Layout

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI routes |
| `app/core.py` | forecast loading, summary windows, driver copy, rule-based advice, Ripple estimator |
| `app/gemini.py` | Gemini chat call (system prompt, JSON schema, cache, cooldown) |
| `app/db.py` | psycopg connection pool |
| `app/refresh.py` | background `db.sync` after each Databricks Job run |
| `app/config.py` | env settings |
