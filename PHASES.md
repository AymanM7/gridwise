# GridWise Build Phases

Six phases, about 13.5 hours of work (~11.5 h of wall-clock time if Phase 5 starts during Phase 3). Every service runs on a **free tier**.
Tick boxes as you go. Each phase ends with a ✅ checkpoint you can show a judge.

| Phase | Name | Time | Checkpoint |
|---|---|---|---|
| 1 | Setup & Ingestion → Bronze | 2 h | Bronze tables queryable in Databricks |
| 2 | Silver & Gold | 2 h | One clean Gold feature table, 1 row per hour |
| 3 | Machine Learning | 2.5 h | Tomorrow's forecast + MAPE to cite |
| 4 | AI Layer & Automation | 1.5 h | Pipeline runs hourly with no manual steps |
| 5 | Serving & Dashboard | 4 h (start during Phase 3) | Live at gridwise.tech |
| 6 | Ship | 1.5 h | Submitted on Devpost |

> **Free Edition rule that shapes the design:** Databricks Free Edition notebooks can only reach a short list of trusted domains (PyPI works; ERCOT, EIA, Open-Meteo, Gemini and Tiger Data most likely don't).
> So a small **worker** (`worker/`, run locally or by GitHub Actions) fetches the data and uploads it *into* a Unity Catalog Volume. Uploading into Databricks is always allowed. Databricks does everything else.
> Step 1.4 confirms exactly what's blocked in your workspace.

---

## Phase 1: Setup & Ingestion → Bronze (2 h)

### 1.1 Create free accounts and keys
| Service | Free tier | Where | `.env` variable |
|---|---|---|---|
| Databricks | Free Edition | https://www.databricks.com/learn/free-edition | `DATABRICKS_HOST`, `DATABRICKS_TOKEN` |
| EIA | Free API key (instant, by email) | https://www.eia.gov/opendata/register.php | `EIA_API_KEY` |
| Gemini | Google AI Studio free tier | https://aistudio.google.com/apikey | `GEMINI_API_KEY` |
| Tiger Data | Free service | https://console.cloud.timescale.com | `TIGER_DATABASE_URL` |
| GitHub | Free, public repo = unlimited Actions minutes | https://github.com/new | repo secrets |
| Vultr | MLH hackathon credits | MLH sponsor page | `VULTR_API_KEY` (optional) |
| GoDaddy | MLH free domain | MLH sponsor page | `APP_DOMAIN` |
| Open-Meteo / ERCOT (gridstatus) | No key needed | — | — |

- [ ] Databricks: **Settings → Developer → Access tokens → Generate** and copy the workspace URL
- [ ] All keys above created

### 1.2 Repo and local environment
- [ ] `git init`, create a **public** GitHub repo, push
- [ ] `python -m venv .venv` → `.venv\Scripts\activate` → `pip install -r worker/requirements.txt`
- [ ] `copy .env.example .env` and fill in the Databricks + EIA values

### 1.3 Databricks workspace setup
- [x] `python -m worker.login https://<your-workspace>.cloud.databricks.com` opens a browser login, then creates a 90-day token and saves it to `.env`
- [x] `python -m worker.deploy --run 00_setup` uploads `notebooks/` to `/Users/<you>/gridwise/notebooks` and runs setup on serverless
  (or: **Workspace → Create → Git folder** with the GitHub repo URL, then run `00_setup` by hand)
- [x] Created catalog `grid`, schemas `bronze/silver/gold/ml`, and volumes `bronze.landing` and `bronze.checkpoints`
- [ ] If creating the catalog fails, set the widget to `workspace`, re-run, and set `GRIDWISE_CATALOG=workspace` in `.env`

### 1.4 Connectivity check
- [x] `python -m worker.deploy --run 00_connectivity_check`
- [x] Result (Nov 7): ERCOT, EIA, Open-Meteo and the Gemini API are **all reachable** from this workspace. Open-Meteo's archive returned 429 (rate-limited on shared Databricks IPs), so the history backfill runs from the worker.
  - 4.1: Gemini can be called **inside Databricks** (notebook task or `ai_query`)
  - Hourly ingestion *can* move into a Databricks notebook task later, so GitHub Actions becomes optional
  - Tiger Data reachability: re-run with the `tiger_host` widget once the Tiger service exists (5.2)

### 1.5 Historical backfill (one time, ~10 min)
- [x] `python -m worker.cli backfill --start 2023-01-01`
  - EIA-930 hourly demand / demand forecast / wind / solar, 2023 → now
  - ERCOT real-time hub-average price archive, one file per year (~100 s/year)
  - Open-Meteo hourly weather archive for Houston, DFW, Austin, San Antonio
- [x] Files land in `/Volumes/grid/bronze/landing/<source>/` (local copy in `data/landing/`)

### 1.6 Live ingest (the hourly refresh)
- [x] `python -m worker.cli ingest`
  - ERCOT live 5-min load, 15-min prices, wind + solar actuals **and 7-day forecasts**
  - Last 4 days of EIA, plus the Open-Meteo forecast (10 past + 3 future days, which overlaps the ~6-day archive lag)

### 1.7 Load Bronze tables
- [x] Run `notebooks/01_bronze` (Auto Loader picks up only new files each run)
- [x] Spot-check: `SELECT * FROM grid.bronze.eia_hourly ORDER BY interval_start_utc DESC LIMIT 10`

**✅ Checkpoint 1:** all 7 Bronze tables exist and the checkpoint query shows 2023 → today. *(Done Nov 7: EIA 33.9k hourly rows, prices 134.6k, weather 134.5k, all from Jan 2023.)*

---

## Phase 2: Silver & Gold (2 h)

### 2.1 Silver: grid hourly
- [x] ERCOT 5-min load and 15-min prices → hourly averages on `interval_start_utc`
- [x] Wind/solar reports: keep the **latest publish** per hour (actuals) and the latest forecast per hour
- [x] Combine history (EIA) + live (ERCOT): ERCOT wins where both exist *(last 24 actual hours: 24/24 `src_demand = 'ercot'`)*
- [x] **DST check:** show that the fall-back hour (`interval_start_local` with `-05:00` and `-06:00`) maps to two distinct UTC hours *(passes 2023/2024/2025/2026: 01:00 local → 06Z and 07Z, each with its own price; spring-forward days 23 h, fall-back 25 h)*
- [x] Cross-check EIA's hour-ending convention against ERCOT live load on the overlap days *(best offset 0 h, mean abs diff 0.066%)*

### 2.2 Silver: weather
- [x] Union archive + forecast (forecast wins for recent hours) *(`weather_hourly` 33,816 rows, no gaps; 11-01..11-04 gap filled)*
- [x] Pivot the 4 cities and compute a **population-weighted** Texas temperature and heat index

### 2.3 Silver: join
- [x] `silver.grid_hourly`: one row per UTC hour with grid + weather columns *(33,813 rows, 2023-01-01 00Z → anchor + 48 h; 48 forecast rows all with temp)*
- [x] Dedupe; assert no duplicate `ts_utc` *(all distinct, contiguous)*

### 2.4 Gold: features
- [x] `net_load_mw = demand − wind − solar`
- [x] Lags, rolling means, hour, day of week, month, US holidays, CDD/HDD *(deviation: lags start at 48 h (`nl_lag_48h`, `*_l48` rolls) so every feature exists 48 h ahead; 1 h/24 h lags kept as `diag_*` only and banned from models. Leakage join: 0 mismatches over 33,813 rows)*

### 2.5 Gold: strain and spikes
- [x] `gold.strain_hourly`: strain index 0–100 (monthly percentile of net load) + green/yellow/red *(red 14.99–15.03 %, yellow 24.97–25.02 % per month)*
- [x] `gold.spike_events`: `price > $100/MWh` *(907 spikes = 2.69 % of hours; by year 3.95 / 1.83 / 2.48 / 2.45 %)*

### 2.6 Data quality
- [x] Missing-hour count per month, null rates, min/max sanity checks (displayed in the notebook) *(`silver.dq_checks` + `gold.dq_checks`, all_pass = true; actual-row nulls: price 0.018 %, net load 0.083 %, demand 0)*

**✅ Checkpoint 2:** `gold.features` has one clean row per hour from 2023 → now. *(Done Nov 7, PM-approved round 2: 33,813 rows, unique `ts_utc`, all 48 forecast rows have lag, price, calendar and temperature features. Open, within tolerance: 24 h of EIA wind/solar on 2025-12-05/06 (3.2 % of Dec 2025) needs ERCOT API credentials to backfill.)*

---

## Phase 3: Machine Learning (2.5 h)

### 3.1 Split and baseline
- [x] Time-based split: train ≤ 2025-06, validate 2025-07 → 2025-09, test the most recent 3 months *(test = after 2026-08-07 20Z; 2,208 test hours)*
- [x] Seasonal-naive baseline (same hour last week) so the MAPE has something to beat *(net load baseline 18.55 % test MAPE; demand baseline 6.53 %)*

### 3.2 Model A: net load
- [x] LightGBM regressor for t+1 … t+48 h (P50) + quantile models (P10, P90) *(test MAPE 11.79 % vs 18.55 % baseline (36 % better), wMAPE 9.85 %, P10–P90 coverage 80.7 % after conformal calibration on val. Misses the original < 5 % target (contract v1.1 deviation). Added Model D (demand): test MAPE 3.45 %)*

### 3.3 Model B: price spike
- [x] LightGBM classifier, `is_unbalance=True`, features include Model A's forecast and ERCOT's wind/solar forecasts *(PR-AUC 0.213 = 9× the 2.36 % base rate, ROC-AUC 0.934, recall 0.81, precision 0.14 at threshold 0.339. Deviation: uses Model A's P50; ERCOT wind/solar forecasts are excluded because they only exist for recent days)*

### 3.4 MLflow and registry
- [x] Log params, metrics and artifacts; register `grid.ml.net_load` and `grid.ml.spike` with alias `@champion` *(champions: net_load v4, spike v2, demand v1; `@champion` loads and predicts 48×3 with no nulls; metrics in `gold.model_metrics`)*

### 3.5 SHAP drivers
- [x] Top-3 drivers per forecast hour → `gold.forecast_drivers` *(`06_explain`, TreeSHAP on the model behind `strain_source` (Model D demand, minus ERCOT wind/solar as drivers): 144 rows = 48 h × 3, SHAP + base reconstructs `net_load_used` to 0.0 MW, 14/14 checks pass. Top driver every hour: low ERCOT wind forecast, avg +8.2 GW. UI copy still needs plain labels ('Low wind output', 'No solar output (night)'))*

### 3.6 Batch inference
- [ ] Next 48 h → `gold.forecasts` (P10/P50/P90, spike_prob, strain, level) *(Built and all checks pass (`05_predict`, run_ts 2026-11-07 20Z, 48 rows: 8 green / 23 yellow / 17 red, max strain 100, max spike_prob 0.71). Strain uses `demand_minus_ercot_renewables` = Model D demand − ERCOT wind − ERCOT solar on 48/48 rows (Model A P50 kept as a column; fixes the 26.6 vs 38.3 GW gap); band = Model D P10/P90 with ERCOT P80, contains `net_load_used` 48/48. **Held open by PM review:** Model D demand looks ~4–6 GW low vs the latest actuals (49.7 GW at 21Z right after an observed 53.1 GW) because of the lag-48 floor, so some hours may show green/yellow while the grid is tighter. Fix: anchor Model D to the last 6 actual hours (`demand_anchor_adj_mw`, decaying exp(−h/24)) and set `LOW_CONF_REL_WIDTH` 0.20 → 0.50 (currently flags 48/48 hours))*

### 3.7 Report card
- [x] Score yesterday's forecast against actuals → `gold.report_card` (MAPE, spike recall, band coverage) *(`07_report_card`: 91 daily backtest rows 2026-08-08 → 11-06 (basis `model_a_p50`): MAPE 11.74 % (hour-weighted), P10–P90 coverage 80.6 %, demand MAPE 3.44 %, spikes caught 42/52 (recall 0.81); matches 04_train. 0 live rows yet: the first batch's hours get actuals from local 11-08; MERGE is idempotent. The displayed method (Model D − ERCOT renewables) can't be backtested yet (ERCOT forecasts in Silver only since ~11-04); the UI must say so)*

**✅ Checkpoint 3:** a forecast for tomorrow, plus test MAPE (target < 5%), spike recall and band coverage. *(Mostly reached Nov 7; 3.6 held open for the demand-anchor fix. Quote to judges: demand forecast **3.45 % test MAPE** (beats the < 5 % target; seasonal-naive 6.53 %); net-load Model A **11.8 % MAPE, 36 % better than baseline (18.6 %)**, P10–P90 coverage **80.7 %**; spike model **recall 0.81** at 9× the base rate PR-AUC (backtest 42 of 52 spike hours caught). Strain story: our ML net-load model under-read November evenings (26.6 GW vs 38.3 GW), so the live strain uses our demand model minus ERCOT's own wind and solar forecasts whenever those exist (`strain_source`), and Model A is the fallback. Rule: never show green when the grid is tight.)*

---

## Phase 4: AI Layer & Automation (1.5 h)

### 4.1 Gemini daily advice
- [ ] If 1.4 showed external models are allowed: AI Gateway + `ai_query()` in SQL → `gold.daily_advice`
- [ ] Otherwise: the worker's `publish` step reads `gold.forecasts` via the SQL warehouse, calls Gemini, and writes `gold.daily_advice` back

### 4.2 "Why Red?" sentences
- [ ] Gemini turns each red hour's SHAP drivers into one plain sentence

### 4.3 Ripple scenarios
- [ ] Precompute the participation × kWh × window grid → `gold.shift_scenarios`

### 4.4 Genie space
- [ ] Create a Genie space over the Gold tables, add table descriptions + sample SQL
- [ ] Test the 5 demo questions in `PROJECT_SCOPE.md`

### 4.5 Databricks Job
- [ ] Job `gridwise-hourly`: bronze → silver → gold → predict → explain → ripple → report card (serverless)
- [ ] Copy the Job ID into `.env` and GitHub secrets as `DATABRICKS_JOB_ID`

### 4.6 End-to-end automation
- [ ] Add repo secrets and enable `.github/workflows/gridwise-hourly.yml`: ingest → upload → run Job, every hour
- [ ] Watch two consecutive runs succeed

**✅ Checkpoint 4:** the whole pipeline runs every hour with no manual steps.

---

## Phase 5: Serving & Dashboard (4 h, start 5.4 during Phase 3)

### 5.1 Tiger Data schema
- [ ] Hypertables `forecasts`, `actuals`, plus continuous aggregates for hourly/daily rollups (`infra/schema.sql`)

### 5.2 Sync Gold → Tiger
- [ ] Worker `publish` step (or a Databricks task if 1.4 showed Tiger is reachable)

### 5.3 FastAPI
- [ ] `/forecast`, `/forecast/drivers`, `/advice`, `/history`, `/simulate`, `/report-card`, `/chat`

### 5.4 Dashboard core
- [ ] 48 h strain timeline with P10–P90 band, spike risk chart, best-hours card, Gemini advice panel

### 5.5 Ripple panel
- [ ] Sliders → before/after curve, Δ peak MW, Δ spike probability, Δ red hours

### 5.6 Why Red? + report card
- [ ] Hover tooltips on red hours; yesterday's accuracy widget

### 5.7 Chat box
- [ ] "When should I charge my EV?" answered by Gemini using the live forecast

### 5.8 Deploy
- [ ] Vultr VM + Docker Compose + Caddy (HTTPS); GoDaddy A record → Vultr IP
- [ ] Move the hourly worker to a Vultr cron (optional; GitHub Actions is fine)

**✅ Checkpoint 5:** live at `https://gridwise.tech`.

---

## Phase 6: Ship (1.5 h)

### 6.1 Architecture image
- [ ] Re-export `docs/architecture.png` if anything changed; add it to Devpost

### 6.2 Demo video (2–3 min)
- [ ] Forecast → Why Red? → advice → Ripple → report card → Genie → architecture

### 6.3 Devpost write-up
- [ ] Problem, solution, how Databricks is used (call out the Free Edition worker design), tracks: Databricks, Gemini, Tiger Data, Vultr, GoDaddy

### 6.4 Final checks
- [ ] `.env` not committed, repo public, README run steps work, demo URL loads on a phone

**✅ Checkpoint 6:** submitted.

---

**Cut order if behind:** Solana → Model B → Ripple custom inputs → chat box → Vultr (use Vercel) → Tiger Data (query the Databricks SQL warehouse directly).
**Never cut:** the pipeline, Model A, Gemini advice, the dashboard, Why Red? drivers.
