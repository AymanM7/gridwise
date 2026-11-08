# GridWise Architecture

> Polished image version for Devpost and slides: [`docs/architecture.png`](docs/architecture.png) (source: [`docs/architecture.svg`](docs/architecture.svg)).
> Every diagram below is plain text, so it looks the same in VS Code, on GitHub and in a terminal.

---

## 1. System design

The whole system on one page. Data enters at the top, gets processed in Databricks, and ends up in front of users at the bottom.

> **Free Edition design.** Databricks Free Edition notebooks can only reach a short list of trusted domains (PyPI works; ERCOT, EIA, Open-Meteo, Gemini and Tiger Data most likely don't). So a small **worker** fetches the data outside Databricks and uploads it *into* a Unity Catalog Volume, which is always allowed. Databricks does all the processing, ML and Genie. The worker also handles the two outbound calls (Gemini and the Tiger sync) if `pipeline/00_connectivity_check` shows they're blocked.

```text
┌────────────────────────────┐   ┌────────────────────────────┐   ┌────────────────────────────┐
│     ERCOT (gridstatus)     │   │        EIA-930 API         │   │         OPEN-METEO         │
│    live load · RT price    │   │    hourly history 2023+    │   │   HOU · DFW · AUS · SAT    │
│   wind/solar + forecasts   │   │   demand · wind · solar    │   │     archive + forecast     │
└──────────────┬─────────────┘   └──────────────┬─────────────┘   └──────────────┬─────────────┘
               └────────────────────────────────┼────────────────────────────────┘
                                                ▼
                 ┌─────────────────────────────────────────────────────────────┐
                 │       GRIDWISE WORKER   ·   GitHub Actions, every hour      │
                 │    fetch -> parquet -> upload INTO a Unity Catalog Volume   │
                 │     (Free Edition blocks outbound calls from notebooks)     │
                 └──────────────────────────────┬──────────────────────────────┘
                                                │ files.upload -> /Volumes/grid/bronze/landing
                                                ▼
╔═══════════════════════════════════════════════════════════════════════════════════════════════════╗
║            DATABRICKS LAKEHOUSE   ·   Unity Catalog: grid   ·   Delta Lake   ·   MLflow           ║
║                                                                                                   ║
║   [1] MEDALLION PIPELINE  (Delta Lake)                                                            ║
║   ┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐   ║
║   │    AUTO LOADER    │   │       BRONZE      │   │       SILVER      │   │        GOLD       │   ║
║   │  Volume -> Delta  │──►│  raw Delta tables │──►│  hourly UTC grid  │──►│  net load = D-W-S │   ║
║   │    incremental    │   │    stored as-is   │   │ DST duplicate fix │   │  strain idx 0-100 │   ║
║   │    availableNow   │   │   + _ingested_at  │   │ grid+weather join │   │ features · spikes │   ║
║   └───────────────────┘   └───────────────────┘   └───────────────────┘   └─────────┬─────────┘   ║
║                                                                                     │             ║
║   [2] MACHINE LEARNING  (MLflow)    ┌───────────────────────────────────────────────┤             ║
║                                     │                                               │             ║
║                                     ▼                                               ▼             ║
║   ┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐   ║
║   │    MLflow + UC    │   │      MODEL A      │   │    SHAP  [NEW]    │   │      MODEL B      │   ║
║   │   Model Registry  │◄──│ LightGBM net load │──►│   top-3 drivers   │   │  spike classifier │   ║
║   │    experiments    │   │   24-48 h ahead   │   │ per forecast hour │   │  P(price > $100)  │   ║
║   │  @champion alias  │   │  P10 · P50 · P90  │   │   -> 'Why Red?'   │   │      per hour     │   ║
║   └───────────────────┘   └───────┬───────┬───┘   └─────────┬─────────┘   └───────┬───────────┘   ║
║                                   │       │                 │                     │       ▲       ║
║                                   │       └─────────────────┼─────────────────────┼───────┘       ║
║                                   │                         │ forecast -> Model B │               ║
║                                   │    ┌────────────────────┘                     │               ║
║   [3] AI & ANALYTICS              │    │                                          │               ║
║                                   ▼    ▼                                          ▼               ║
║   ┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐   ║
║   │    GENIE SPACE    │   │       GEMINI      │   │ REPORT CARD [NEW] │   │   RIPPLE  [NEW]   │   ║
║   │  natural-language │   │   ai_query() or   │   │  forecast vs real │   │  what-if shifting │   ║
║   │   Q&A over Gold   │   │   worker publish  │   │   MAPE · recall   │   │ re-scores Model B │   ║
║   │    (demo live)    │   │ advice + Why Red? │   │   band coverage   │   │   scenario grid   │   ║
║   └───────────────────┘   └─────────┬─────────┘   └─────────┬─────────┘   └─────────┬─────────┘   ║
║             ▲                       │                       │                       │             ║
║             │                       ▼                       ▼                       ▼             ║
║   ┌─────────┴─────────────────────────────────────────────────────────────────────────────────┐   ║
║   │                                    GOLD SERVING TABLES                                    │   ║
║   │        forecasts · forecast_drivers · daily_advice · shift_scenarios · report_card        │   ║
║   └───────────────────────────────────────────────────────────────────────────────────────────┘   ║
║                                                                                                   ║
║   ┌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┐   ║
║   ╎                            DATABRICKS WORKFLOWS  ·  HOURLY JOB                            ╎   ║
║   ╎          bronze -> silver -> gold -> predict -> explain -> ripple -> report card          ╎   ║
║   ╎     triggered hourly by the worker  ·  Unity Catalog governance  ·  train runs weekly     ╎   ║
║   └╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┘   ║
║                                                                                                   ║
╚═══════════╧═════════════════════════════════════╤═════════════════════════════════════════════════╝
            ▲                                     │
            │                                     │ hourly sync (worker publish)
            │                                     ▼
            │                 ┌───────────────────────────────────────┐
            │ Genie Q&A       │       TIGER DATA  (TimescaleDB)       │
            │                 │  hypertables + continuous aggregates  │
            │                 │         hourly + daily rollups        │
            │                 └───────────────────┬───────────────────┘
            │                                     │
            │                                     ▼
┌───────────┴──────────┐      ┌───────────────────────────────────────┐        ┌────────────────────┐
│  ANALYSTS / JUDGES   │      │            FASTAPI on VULTR           │        │     GEMINI API     │
│     ask Genie in     │      │         Docker + Caddy (HTTPS)        │◄──────►│    chat answers    │
│    plain English     │      │      /forecast  /advice  /history     │        │    grounded in     │
│                      │      │     /simulate  /chat  /report-card    │        │   forecast JSON    │
└──────────────────────┘      └───────────────────┬───────────────────┘        └────────────────────┘
                                                  │ JSON / HTTPS
                                                  ▼
                      ┌───────────────────────────────────────────────────────┐    ┌────────────────┐
                      │         NEXT.JS DASHBOARD   ·   gridwise.tech         │    │    GODADDY     │
                      │     strain timeline + P10-P90 band  ·  spike risk     │◄───│ DNS: A record  │
                      │       best hours  ·  Gemini advice  ·  chat box       │    │  -> Vultr IP   │
                      │     Ripple simulator  ·  Why Red?  ·  report card     │    └────────────────┘
                      └───────────────────────────────────────────────────────┘
                                                  ▲
                                                  │
                              ┌───────────────────┴───────────────────┐
                              │     TEXANS · EV OWNERS · TOU PLANS    │
                              │    shift usage off-peak, save money   │
                              └───────────────────────────────────────┘
```

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

```text
                          ┌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┐
                          ╎  worker: ingest + upload  ╎
                          ╎  GitHub Actions (hourly)  ╎
                          └╌╌╌╌╌╌╌╌╌╌╌╌╌┬╌╌╌╌╌╌╌╌╌╌╌╌╌┘
                                        ▼
                             ┌─────────────────────┐
                             │        bronze       │
                             │     Auto Loader     │
                             └──────────┬──────────┘
                                        ▼
                             ┌─────────────────────┐
                             │     build_silver    │
                             └──────────┬──────────┘
                                        ▼
                             ┌─────────────────────┐
                             │      build_gold     │
                             └──────────┬──────────┘
                                        ▼            registers @champion
                             ┌─────────────────────┐        ┌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┐
                             │       predict       │◄╌╌╌╌╌╌╌╎        train         ╎
                             │  Model A + Model B  │        ╎   manual / weekly    ╎
                             └──────────┬──────────┘        └╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┘
               ┌────────────────────────┼────────────────────────┐
               ▼                        ▼                        ▼
   ┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
   │       explain        │ │   ripple_scenarios   │ │     report_card      │
   │     SHAP drivers     │ │    Ripple  [NEW]     │ │ daily ~6am CT  [NEW] │
   └───────────┬──────────┘ └───────────┬──────────┘ └───────────┬──────────┘
               ▼                        │                        │
   ┌──────────────────────┐             │                        │
   │    gemini_advice     │             │                        │
   │ ai_query if allowed  │             │                        │
   └───────────┬──────────┘             │                        │
               │                        │                        │
               └────────────────────────┼────────────────────────┘
                                        ▼
                        ┌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┐
                        ╎        worker: publish        ╎
                        ╎   Gemini advice + Tiger sync  ╎
                        └╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┘
```

| Task | Notebook | Output |
|---|---|---|
| *(worker)* `ingest` | `ingestion/cli.py ingest` | parquet → `/Volumes/grid/bronze/landing/<source>/` |
| `bronze` | `pipeline/01_bronze.py` | `bronze.eia_hourly`, `ercot_load`, `ercot_prices`, `ercot_wind`, `ercot_solar`, `weather_hist`, `weather_forecast` |
| `build_silver` | `pipeline/02_silver.py` | `silver.grid_hourly` |
| `build_gold` | `pipeline/03_gold.py` | `gold.features`, `gold.strain_hourly`, `gold.spike_events` |
| `train` (manual / weekly) | `ml/04_train.py` | MLflow runs → UC models `grid.ml.net_load`, `grid.ml.spike` |
| `predict` | `ml/05_predict.py` | `gold.forecasts` |
| `explain` | `ml/06_explain.py` | `gold.forecast_drivers` |
| `gemini_advice` | *(Phase 4)* | `gold.daily_advice` (only if AI Gateway external models work on Free Edition) |
| `ripple_scenarios` | *(Phase 4)* | `gold.shift_scenarios` |
| `report_card` | `ml/07_report_card.py` | `gold.report_card` |
| *(worker)* `publish` | *(Phase 4/5)* | Gemini advice → `gold.daily_advice` (fallback); Gold → Tiger Data |

---

## 3. Data model

### 3.1 Medallion layers

```text
┌──────────────────────┐            ┌──────────────────────┐            ┌──────────────────────┐
│        BRONZE        │            │        SILVER        │            │         GOLD         │
│  raw, stored as-is   │            │   cleaned + joined   │            │    business-ready    │
├──────────────────────┤            ├──────────────────────┤            ├──────────────────────┤
│ eia_hourly           │ CPT -> UTC │ grid_hourly          │ net load   │ features             │
│ ercot_load           │ DST fix    │ 1 row per UTC hour   │ lags/rolls │ strain_hourly        │
│ ercot_prices         │ dedupe     │ load · wind · solar  │ heat index │ spike_events         │
│ ercot_wind           │ join       │ RT price             │ strain     │ forecasts            │
│ ercot_solar          │            │ 4-city weather       │            │ forecast_drivers     │
│ weather_hist         │──────────► │                      │──────────► │ daily_advice         │
│ weather_forecast     │            │                      │            │ shift_scenarios      │
│                      │            │                      │            │ report_card          │
└──────────────────────┘            └──────────────────────┘            └──────────────────────┘
```

### 3.2 DST handling (the ERCOT gotcha)

```text
┌────────────────────────────────┐
│ ERCOT row: local CPT hour      │
│ + DSTFlag column               │
└────────────────┬───────────────┘
                 ▼
┌────────────────────────────────┐            ┌────────────────────────────────┐
│ Fall-back day?                 │── yes ────►│ DSTFlag True  -> 1st 01:00 CDT │──┐
│ (01:00 appears twice)          │            │ DSTFlag False -> 2nd 01:00 CST │  │
└────────────────┬───────────────┘            └────────────────────────────────┘  │
                 │ no                                                             │
                 ▼                                                                │
┌────────────────────────────────┐            ┌────────────────────────────────┐  │
│ Spring-forward day?            │── yes ────►│ 23-hour day:                   │──┤
│ (02:00 is missing)             │            │ don't impute 02:00             │  │
└────────────────┬───────────────┘            └────────────────────────────────┘  │
                 │ no                                                             │
                 ▼                                                                │
┌────────────────────────────────┐                                                │
│ tz_localize('America/Chicago') │                                                │
│ -> tz_convert('UTC')           │◄───────────────────────────────────────────────┘
└────────────────┬───────────────┘
                 ▼
┌────────────────────────────────┐
│ dedupe on ts_utc               │
│ -> silver.grid_hourly          │
└────────────────────────────────┘
```

> ERCOT reports in Central Prevailing Time. The fall-back hour appears twice and the spring-forward hour is missing. Localize with the `DSTFlag`, convert to UTC, and *then* aggregate. This is worth mentioning to judges.

### 3.3 How the Gold tables relate

```text
                                 ┌────────────────────┐
                                 │   gold.features    │
                                 └──────────┬─────────┘
                                            │ Models A + B
                                            ▼
                                 ┌────────────────────┐                ┌────────────────────┐
                                 │   gold.forecasts   │                │ gold.strain_hourly │
                                 └──────────┬─────────┘                └──────────┬─────────┘
          ┌───────────────────────┬─────────┴─────────────┬───────────────────────┤
          ▼                       ▼                       ▼                       ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ forecast_drivers │    │   daily_advice   │    │ shift_scenarios  │    │   report_card    │
│      (SHAP)      │    │     (Gemini)     │    │     (Ripple)     │    │ (eval vs actual) │
└──────────────────┘    └──────────────────┘    └──────────────────┘    └──────────────────┘
```

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

```text
                      ┌────────────────────────────────┐
                      │         gold.features          │
                      └────────────────┬───────────────┘
                                       ▼
                      ┌────────────────────────────────┐
                      │        time-based split        │
                      │       train / val / test       │
                      └────────────────┬───────────────┘
                   ┌───────────────────┴───────────────────┐
                   ▼                                       ▼
    ┌────────────────────────────┐          ┌────────────────────────────┐
    │       Train Model A        │          │       Train Model B        │
    │ P50 + P10 + P90 quantiles  │          │      spike classifier      │
    └──────────────┬─────────────┘          └──────────────┬─────────────┘
                   └───────────────────┬───────────────────┘
                                       ▼
                      ┌────────────────────────────────┐
                      │          MLflow runs           │
                      │  params · metrics · artifacts  │
                      └────────────────┬───────────────┘
                                       ▼
                      ┌────────────────────────────────┐
                      │     beats current champion     │
                      │       on validation set?       │
                      └────────────────┬───────────────┘
                   ┌───────────────────┴───────────────────┐
                   ▼ yes                                   ▼ no
    ┌────────────────────────────┐          ┌────────────────────────────┐
    │ register in Unity Catalog  │          │       keep existing        │
    │      alias @champion       │          │          champion          │
    └──────────────┬─────────────┘          └──────────────┬─────────────┘
                   └───────────────────┬───────────────────┘
                                       ▼
                      ┌────────────────────────────────┐
                      │     hourly batch inference     │
                      │       -> gold.forecasts        │
                      └────────────────────────────────┘
```

---

## 5. Novel features

### 5.1 Ripple: "What if Texas shifted?" simulator

```text
┌──────────────────────────────┐              ┌──────────────────────────────┐
│         USER SLIDERS         │              │      FORECAST P50 CURVE      │
│       participation %        │              │        gold.forecasts        │
│         kWh per home         │              │        (net load, MW)        │
│      from / to windows       │              │                              │
└───────────────┬──────────────┘              └───────────────┬──────────────┘
                ▼                                             │
┌──────────────────────────────┐                              │
│         shifted MW =         │                              │
│   pct x meters x kWh / hrs   │                              │
└───────────────┬──────────────┘                              │
                └──────────────────────┬──────────────────────┘
                                       ▼
                      ┌────────────────────────────────┐
                      │   subtract from peak window    │
                      │  add back to off-peak window   │
                      └────────────────┬───────────────┘
                ┌──────────────────────┴──────────────────────┐
                ▼                                             ▼
┌──────────────────────────────┐              ┌──────────────────────────────┐
│    re-score with Model B     │              │    recompute strain index    │
└───────────────┬──────────────┘              └───────────────┬──────────────┘
                └──────────────────────┬──────────────────────┘
                                       ▼
          ┌────────────────────────────────────────────────────────┐
          │               RESULT  (before vs. after)               │
          │          Δ peak MW   ·   Δ spike probability           │
          │     Δ red hours   ·   ≈ gas peaker plants avoided      │
          └────────────────────────────────────────────────────────┘
                                       ▲ instant lookup
                                       ╎
                      ┌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┴╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┐
                      ╎      gold.shift_scenarios      ╎
                      ╎   precomputed scenario grid    ╎
                      └╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┘
```

### 5.2 "Why Red?" explainable alerts + report card

```text
┌──────────────────────────┐      ┌──────────────────────────┐      ┌──────────────────────────┐
│    Model A (champion)    │      │     quantile models      │      │   yesterday's forecast   │
│                          │      │        P10 / P90         │      │  + yesterday's actuals   │
└─────────────┬────────────┘      └─────────────┬────────────┘      └─────────────┬────────────┘
              │                                 │                                 │
              ▼                                 │                                 │
┌──────────────────────────┐                    │                                 │
│    SHAP TreeExplainer    │                    │                                 │
│    per forecast hour     │                    │                                 │
└─────────────┬────────────┘                    │                                 │
              ▼                                 ▼                                 ▼
┌──────────────────────────┐      ┌──────────────────────────┐      ┌──────────────────────────┐
│      top-3 drivers       │      │     confidence band      │      │       REPORT CARD        │
│  feature · value · ±MW   │      │  + low-confidence flag   │      │ MAPE · spike hits · band │
└─────────────┬────────────┘      └─────────────┬────────────┘      └─────────────┬────────────┘
              ▼                                 │                                 │
┌──────────────────────────┐                    │                                 │
│   Gemini via ai_query    │                    │                                 │
│  1-sentence 'Why Red?'   │                    │                                 │
└─────────────┬────────────┘                    │                                 │
              └─────────────────────────────────┼─────────────────────────────────┘
                                                ▼
                    ┌──────────────────────────────────────────────────────┐
                    │                      DASHBOARD                       │
                    │       hover tooltip on red hours + report card       │
                    └──────────────────────────────────────────────────────┘
```

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

```text
 ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐
 │    User    │    │  Next.js   │    │  FastAPI   │    │ Tiger Data │    │ Gemini API │
 └──────┬─────┘    └──────┬─────┘    └──────┬─────┘    └──────┬─────┘    └──────┬─────┘
        │                 │                 │                 │                 │
        │ "EV question"   │                 │                 │                 │
        │────────────────►│                 │                 │                 │
        │                 │                 │                 │                 │
        │                 │ POST /chat      │                 │                 │
        │                 │────────────────►│                 │                 │
        │                 │                 │                 │                 │
        │                 │                 │ next 48h fcst   │                 │
        │                 │                 │────────────────►│                 │
        │                 │                 │                 │                 │
        │                 │                 │ rows            │                 │
        │                 │                 │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                 │
        │                 │                 │                 │                 │
        │                 │                 │ prompt + JSON   │                 │
        │                 │                 │──────────────────────────────────►│
        │                 │                 │                 │                 │
        │                 │                 │ "plug in 1-5am" │                 │
        │                 │                 │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│
        │                 │                 │                 │                 │
        │                 │ answer + hours  │                 │                 │
        │                 │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                 │                 │
        │                 │                 │                 │                 │
        │ highlight       │                 │                 │                 │
        │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                 │                 │                 │
        │                 │                 │                 │                 │
        │                 │                 │                 │                 │
```

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

```text
┌────────────────┐    ┌────────────────┐    ┌────────────────┐    ┌────────────────┐
│ Databricks Job │    │   Tiger Data   │    │    FastAPI     │    │    Browser     │
└────────┬───────┘    └────────┬───────┘    └────────┬───────┘    └────────┬───────┘
         │                     │                     │                     │
         │ hourly upsert       │                     │                     │
         │────────────────────►│                     │                     │
         │                     │                     │                     │
         │                     ├──┐                  │                     │
         │                     │  │ refresh caggs    │                     │
         │                     │◄─┘                  │                     │
         │                     │                     │                     │
         │                     │                     │ GET /forecast       │
         │                     │                     │◄────────────────────│
         │                     │                     │                     │
         │                     │ SQL query           │                     │
         │                     │◄────────────────────│                     │
         │                     │                     │                     │
         │                     │ rows (ms)           │                     │
         │                     │╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌►│                     │
         │                     │                     │                     │
         │                     │                     │ JSON -> charts      │
         │                     │                     │╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌►│
         │                     │                     │                     │
         │                     │                     │                     │
```

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

```text
                              ┌────────────────────────┐
                              │      User browser      │
                              └────────────┬───────────┘
                                           │ https://gridwise.tech
                                           ▼
                              ┌────────────────────────┐
                              │      GoDaddy DNS       │
                              │  A record -> Vultr IP  │
                              └────────────┬───────────┘
                                           ▼
    ╔════════════════════ Vultr VM  (Ubuntu + Docker Compose) ═══════════════════╗
    ║                                                                            ║
    ║                         ┌────────────────────────┐                         ║
    ║                         │    caddy :80 / :443    │                         ║
    ║                         │    auto-HTTPS proxy    │                         ║
    ║                         └────────────┬───────────┘                         ║
    ║                 ┌────────────────────┴────────────────────┐                ║
    ║                 │ /                                       │ /api           ║
    ║                 ▼                                         ▼                ║
    ║    ┌────────────────────────┐                ┌────────────────────────┐    ║
    ║    │       web :3000        │                │       api :8000        │    ║
    ║    │        Next.js         │                │        FastAPI         │    ║
    ║    └────────────────────────┘                └────────────┬───────────┘    ║
    ║                                                           │                ║
    ║                                                           │                ║
    ║                                                           │                ║
    ╚═══════════════════════════════════════════════════════════╤════════════════╝
                                                                │
                                                ┌───────────────┴───────────────┐
                                                ▼ SQL                           ▼ chat
┌────────────────────────┐          ┌──────────────────────┐          ┌──────────────────┐
│     Databricks Job     │          │      Tiger Data      │          │    Gemini API    │
│      hourly sync       │─────────►│ hypertables + caggs  │          │   chat answers   │
└────────────────────────┘          └──────────────────────┘          └──────────────────┘
```

---

## 10. Project phases

### 10.1 Timeline

```text
                            0    1    2    3    4    5    6    7    8    9    10   11   12   (hours from kickoff)
                            ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
1  Setup & Ingestion        ██████████  2 h
2  Silver & Gold                      ██████████  2 h
3  Machine Learning                             ████████████  2.5 h
4  AI Layer & Automation                                    ████████  1.5 h
5  Serving & Dashboard                                    ████████████████████  4 h
6  Ship                                                                       ████████  1.5 h
```

### 10.2 Phase order

```text
┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐
│  PHASE 1   │    │  PHASE 2   │    │  PHASE 3   │    │  PHASE 4   │    │  PHASE 6   │
│  Setup +   │───►│  Silver +  │───►│  Machine   │───►│ AI layer + │───►│    Ship    │
│ Ingestion  │    │    Gold    │    │  Learning  │    │ Automation │    │  Devpost   │
│    2 h     │    │    2 h     │    │   2.5 h    │    │   1.5 h    │    │   1.5 h    │
└────────────┘    └────────────┘    └──────┬─────┘    └────────────┘    └────────────┘
                                           │                                   ▲
                                           │  ┌──────────────────────────┐     │
                                           └─►│         PHASE 5          │─────┘
                                              │   Serving + Dashboard    │
                                              │  4 h, starts during P3   │
                                              └──────────────────────────┘
```

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
gridwise/
├── ingestion/        📥 DATA INGESTION: fetch ERCOT · EIA · Open-Meteo, upload into Databricks
│   └── sources/        ercot.py · eia.py · weather.py
├── pipeline/         🏗️ DATABRICKS PIPELINE: 00_setup → 01_bronze → 02_silver → 03_gold
├── ml/               🤖 MACHINE LEARNING: 04_train · 05_predict · 06_explain · 07_report_card
├── db/               🗄️ SERVING DATABASE: Tiger Data schema + continuous aggregates  (Phase 5)
├── backend/          🔌 API: FastAPI on Vultr                                       (Phase 5)
├── frontend/         🖥️ DASHBOARD: Next.js at gridwise.tech                          (Phase 5)
├── infra/            🚀 DEPLOYMENT: docker-compose · Caddy · Vultr                   (Phase 5)
├── tools/            🧰 DEV HELPERS: login · deploy · sql · check_secrets
├── docs/             📚 architecture image · data contract · diagram generator
├── .github/workflows/  secret-scan (every push) · gridwise-hourly (pipeline trigger)
└── .gitleaks.toml    secret-detection rules
```
Each folder has its own `README.md` explaining what's inside and how to run it.

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
