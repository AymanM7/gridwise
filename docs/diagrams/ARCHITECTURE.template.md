# GridWise Architecture

> Polished image version for Devpost and slides: [`docs/architecture.png`](docs/architecture.png) (source: [`docs/architecture.svg`](docs/architecture.svg)).
> Every diagram below is plain text, so it looks the same in VS Code, on GitHub and in a terminal.

---

## 1. System design

The whole system on one page. Data enters at the top, gets processed in Databricks, and ends up in front of users at the bottom.

> **Free Edition design.** Databricks Free Edition notebooks can only reach a short list of trusted domains (PyPI works; ERCOT, EIA, Open-Meteo, Gemini and Tiger Data most likely don't). So a small **worker** fetches the data outside Databricks and uploads it *into* a Unity Catalog Volume, which is always allowed. Databricks does all the processing, ML and Genie. The worker also handles the two outbound calls (Gemini and the Tiger sync) if `notebooks/00_connectivity_check` shows they're blocked.

{{D1}}

**Reading the diagram**

| Layer | What happens |
|---|---|
| Sources | ERCOT live data (gridstatus), EIA-930 hourly history, Open-Meteo weather |
| Worker | GitHub Actions job that fetches every hour, uploads parquet into the UC Volume and triggers the Databricks Job |
| Medallion pipeline | Raw → cleaned hourly UTC → business-ready Gold tables |
| Machine learning | Model A forecasts net load, Model B forecasts spike risk, SHAP explains Model A |
| AI & analytics | Gemini writes advice in SQL, Ripple runs what-ifs, report card scores yesterday, Genie answers questions |
| Serving | Tiger Data caches Gold for millisecond chart queries; FastAPI exposes it |
| Users | Dashboard at gridwise.tech; analysts and judges query Genie directly |

---

## 2. Databricks Job (hourly)

{{D2}}

| Task | Notebook | Output |
|---|---|---|
| *(worker)* `ingest` | `worker/cli.py ingest` | parquet → `/Volumes/grid/bronze/landing/<source>/` |
| `bronze` | `01_bronze.py` | `bronze.eia_hourly`, `ercot_load`, `ercot_prices`, `ercot_wind`, `ercot_solar`, `weather_hist`, `weather_forecast` |
| `build_silver` | `02_silver.py` | `silver.grid_hourly` |
| `build_gold` | `03_gold.py` | `gold.features`, `gold.strain_hourly`, `gold.spike_events` |
| `train` (manual / weekly) | `04_train.py` | MLflow runs → UC models `grid.ml.net_load`, `grid.ml.spike` |
| `predict` | `05_predict.py` | `gold.forecasts` |
| `explain` | `06_explain.py` | `gold.forecast_drivers` |
| `gemini_advice` | `07_advice.sql` | `gold.daily_advice` (only if AI Gateway external models work on Free Edition) |
| `ripple_scenarios` | `08_ripple.py` | `gold.shift_scenarios` |
| `report_card` | `09_report_card.py` | `gold.report_card` |
| *(worker)* `publish` | `worker/cli.py publish` | Gemini advice → `gold.daily_advice` (fallback); Gold → Tiger Data |

---

## 3. Data model

### 3.1 Medallion layers

{{D3}}

### 3.2 DST handling (the ERCOT gotcha)

{{D4}}

> ERCOT reports in Central Prevailing Time. The fall-back hour appears twice and the spring-forward hour is missing. Localize with the `DSTFlag`, convert to UTC, and *then* aggregate. This is worth mentioning to judges.

### 3.3 How the Gold tables relate

{{D5}}

### 3.4 Table reference

**Bronze (raw, append-only)**

| Table | Key columns |
|---|---|
| `bronze.eia_hourly` | `interval_start_utc`, `demand_mw`, `demand_forecast_mw`, `wind_mw`, `solar_mw` (EIA-930, hour-ending → start) |
| `bronze.ercot_load` | `interval_start_utc`, `interval_start_local` (with UTC offset), `load_mw` (5-min) |
| `bronze.ercot_prices` | `interval_start_utc`, `interval_start_local`, `location` (HB_HUBAVG), `price_usd_mwh` (15-min) |
| `bronze.ercot_wind` / `ercot_solar` | `interval_start_utc`, `publish_time_utc`, `gen_mw`, `forecast_mw`, `forecast_p80_mw`, `hsl_mw` |
| `bronze.weather_hist` / `weather_forecast` | `city`, `time_utc`, `temperature_2m` (°F), `relative_humidity_2m`, `apparent_temperature`, `wind_speed_10m`, `cloud_cover`, `shortwave_radiation` |

Every Bronze row also has `_source`, `_fetched_at_utc`, `_ingested_at` and `_source_file` for lineage.

**Silver**

`silver.grid_hourly`: one row per UTC hour:
`ts_utc, load_mw, wind_mw, solar_mw, rt_price, temp_{hou,dfw,aus,sat}, humidity_*, ...`

**Gold**

| Table | Columns |
|---|---|
| `gold.features` | `ts_utc`, `net_load_mw` (= load − wind − solar), lags (1h, 24h, 168h), rolling means, `hour`, `dow`, `month`, `is_holiday`, pop-weighted `temp_f`, `heat_index_f`, `cdd`, `hdd` |
| `gold.strain_hourly` | `ts_utc`, `net_load_mw`, `strain_index` (0–100), `level` (green / yellow / red) |
| `gold.spike_events` | `ts_utc`, `rt_price`, `is_spike` (price > $100/MWh) |
| `gold.forecasts` | `run_ts`, `target_ts`, `net_load_p10`, `net_load_p50`, `net_load_p90`, `spike_prob`, `strain_index`, `level` |
| `gold.forecast_drivers` | `run_ts`, `target_ts`, `rank`, `feature`, `value`, `shap_mw` |
| `gold.daily_advice` | `date`, `advice_md`, `best_hours[]`, `avoid_hours[]`, `why_red` (map target_ts → sentence) |
| `gold.shift_scenarios` | `run_ts`, `participation_pct`, `kwh_per_home`, `from_window`, `to_window`, `peak_reduction_mw`, `spike_prob_before`, `spike_prob_after`, `red_hours_before`, `red_hours_after` |
| `gold.report_card` | `date`, `mape`, `spike_recall`, `spike_precision`, `band_coverage` |

**Strain index:** percentile rank of net load against the trailing 2-year distribution for that month, scaled to 0–100, with a boost when spike probability > 0.5. Green < 60, Yellow 60–85, Red > 85.

---

## 4. Machine learning

### 4.1 Model design

| | Model A: Net load | Model B: Spike |
|---|---|---|
| Algorithm | LightGBM regressor (`objective=regression`, plus `quantile` α=0.1/0.9) | LightGBM classifier (`is_unbalance=True`) |
| Target | `net_load_mw` at t+1…t+48 (direct multi-horizon or horizon as a feature) | `rt_price > 100` |
| Features | lags, rolling stats, calendar, weather forecast, heat index | Model A forecast, reserve proxy, hour, temp, wind/solar forecast |
| Split | time-based: train ≤ 2025-06, validate 2025-07→09, test most recent 3 months | same |
| Metrics | MAPE, RMSE, P10–P90 coverage | recall, precision, PR-AUC |
| Registry | `grid.ml.net_load@champion` | `grid.ml.spike@champion` |

### 4.2 Model lifecycle

{{D6}}

---

## 5. Novel features

### 5.1 Ripple: "What if Texas shifted?" simulator

{{D7}}

### 5.2 "Why Red?" explainable alerts + report card

{{D8}}

---

## 6. Gemini integration

### 6.1 In the pipeline (AI Gateway + SQL)

```sql
CREATE OR REPLACE TABLE grid.gold.daily_advice AS
SELECT
  current_date() + 1 AS date,
  ai_query(
    'gemini-advice',   -- serving endpoint backed by Gemini external model
    concat(
      'You are GridWise. Given tomorrow''s hourly ERCOT forecast (JSON), write 3 short, ',
      'practical tips for Texas households (AC, dryer, dishwasher, EV). Name exact hours. ',
      'Forecast: ', to_json(collect_list(struct(target_ts, strain_index, level, spike_prob)))
    )
  ) AS advice_md
FROM grid.gold.forecasts
WHERE run_ts = (SELECT max(run_ts) FROM grid.gold.forecasts)
  AND date(target_ts) = current_date() + 1;
```

### 6.2 In the app (chat box)

FastAPI `/chat` sends the user's question plus the latest forecast JSON as context to the Gemini API.

{{D9}}

---

## 7. Serving layer (Tiger Data)

```sql
CREATE TABLE forecasts (run_ts timestamptz, target_ts timestamptz, net_load_p10 real,
  net_load_p50 real, net_load_p90 real, spike_prob real, strain_index real, level text);
SELECT create_hypertable('forecasts', 'target_ts');

CREATE TABLE actuals (ts timestamptz PRIMARY KEY, load_mw real, wind_mw real,
  solar_mw real, net_load_mw real, rt_price real, strain_index real);
SELECT create_hypertable('actuals', 'ts');

CREATE MATERIALIZED VIEW actuals_daily WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', ts) AS day, max(net_load_mw) AS peak_net_load,
       avg(rt_price) AS avg_price, max(strain_index) AS max_strain
FROM actuals GROUP BY day;
```

### 7.1 Dashboard request path

{{D10}}

---

## 8. API (FastAPI on Vultr)

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | status |
| GET | `/forecast?hours=48` | hourly forecast with P10/P50/P90, spike prob, level |
| GET | `/forecast/drivers?ts=` | top-3 SHAP drivers and the "Why Red?" sentence |
| GET | `/advice` | tomorrow's Gemini advice, best/avoid hours |
| GET | `/history?range=30d&agg=daily` | actuals from continuous aggregates |
| GET | `/simulate?pct=5&kwh=3&from=16-20&to=22-02` | Ripple before/after (precomputed lookup) |
| GET | `/report-card?days=7` | recent forecast accuracy |
| POST | `/chat` | Gemini answer grounded in the current forecast |

---

## 9. Deployment

{{D11}}

---

## 10. Project phases

### 10.1 Timeline

{{D12}}

### 10.2 Phase order

{{D13}}

The full step-by-step checklist (1.1 → 6.4) lives in **[PHASES.md](PHASES.md)**.

| Phase | Time | Checkpoint |
|---|---|---|
| 1. Setup & Ingestion → Bronze | 2 h | Bronze tables queryable in Databricks |
| 2. Silver & Gold | 2 h | One clean Gold feature table, 1 row per hour |
| 3. Machine Learning | 2.5 h | Tomorrow's forecast + MAPE to cite |
| 4. AI Layer & Automation | 1.5 h | Pipeline runs hourly with no manual steps |
| 5. Serving & Dashboard | 4 h (starts during Phase 3) | Live at gridwise.tech |
| 6. Ship | 1.5 h | Submitted on Devpost |

**Cut order if behind:** Solana → Model B → Ripple custom inputs → chat box → Vultr (use Vercel) → Tiger Data (query Databricks SQL directly).
**Never cut:** the pipeline, Model A, Gemini advice, the dashboard, Why Red? drivers.

---

## 11. Repository layout

```text
/
├── PROJECT_SCOPE.md
├── TECH_STACK.md
├── ARCHITECTURE.md
├── .env.example
├── PHASES.md
├── worker/           # fetches ERCOT / EIA / Open-Meteo, uploads to UC Volume, publishes
├── notebooks/        # Databricks notebooks 00–09 (see Job table)
├── .github/workflows # hourly trigger (GitHub Actions)
├── api/              # FastAPI app + Dockerfile
├── frontend/         # Next.js dashboard + Dockerfile
├── infra/            # docker-compose.yml, Caddyfile, Tiger Data schema.sql
└── docs/             # architecture.svg / .png, demo assets
```

---

## 12. Secrets handling

- Local and Vultr: `.env` (never committed; copy from `.env.example`).
- GitHub Actions: repo secrets `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_JOB_ID`, `EIA_API_KEY`, `GRIDWISE_CATALOG`.
- Databricks: store keys in a secret scope, never in notebooks:
  ```bash
  databricks secrets create-scope gridwise
  databricks secrets put-secret gridwise gemini_api_key
  databricks secrets put-secret gridwise tiger_db_url
  ```
  Read them with `dbutils.secrets.get("gridwise", "gemini_api_key")`. The AI Gateway external model references `{{secrets/gridwise/gemini_api_key}}`.
