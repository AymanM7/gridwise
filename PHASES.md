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
> So a small **worker** (`ingestion/`, run locally or by GitHub Actions) fetches the data and uploads it *into* a Unity Catalog Volume. Uploading into Databricks is always allowed. Databricks does everything else.
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
- [ ] `python -m venv .venv` → `.venv\Scripts\activate` → `pip install -r ingestion/requirements.txt`
- [ ] `copy .env.example .env` and fill in the Databricks + EIA values

### 1.3 Databricks workspace setup
- [x] `python -m tools.login https://<your-workspace>.cloud.databricks.com` opens a browser login, then creates a 90-day token and saves it to `.env`
- [x] `python -m tools.deploy --run 00_setup` uploads `pipeline/` + `ml/` to `/Users/<you>/gridwise/{pipeline,ml}` and runs setup on serverless
  (or: **Workspace → Create → Git folder** with the GitHub repo URL, then run `00_setup` by hand)
- [x] Created catalog `grid`, schemas `bronze/silver/gold/ml`, and volumes `bronze.landing` and `bronze.checkpoints`
- [ ] If creating the catalog fails, set the widget to `workspace`, re-run, and set `GRIDWISE_CATALOG=workspace` in `.env`

### 1.4 Connectivity check
- [x] `python -m tools.deploy --run 00_connectivity_check`
- [x] Result (Nov 7): ERCOT, EIA, Open-Meteo and the Gemini API are **all reachable** from this workspace. Open-Meteo's archive returned 429 (rate-limited on shared Databricks IPs), so the history backfill runs from the worker.
  - 4.1: Gemini can be called **inside Databricks** (notebook task or `ai_query`)
  - Hourly ingestion *can* move into a Databricks notebook task later, so GitHub Actions becomes optional
  - Tiger Data reachability: re-run with the `tiger_host` widget once the Tiger service exists (5.2)

### 1.5 Historical backfill (one time, ~10 min)
- [x] `python -m ingestion.cli backfill --start 2023-01-01`
  - EIA-930 hourly demand / demand forecast / wind / solar, 2023 → now
  - ERCOT real-time hub-average price archive, one file per year (~100 s/year)
  - Open-Meteo hourly weather archive for Houston, DFW, Austin, San Antonio
- [x] Files land in `/Volumes/grid/bronze/landing/<source>/` (local copy in `data/landing/`)

### 1.6 Live ingest (the hourly refresh)
- [x] `python -m ingestion.cli ingest`
  - ERCOT live 5-min load, 15-min prices, wind + solar actuals **and 7-day forecasts**
  - Last 4 days of EIA, plus the Open-Meteo forecast (10 past + 3 future days, which overlaps the ~6-day archive lag)

### 1.7 Load Bronze tables
- [x] Run `pipeline/01_bronze` (Auto Loader picks up only new files each run)
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
- [x] Next 48 h → `gold.forecasts` (P10/P50/P90, spike_prob, strain, level) *(Done Nov 7 (`05_predict`, run_ts 2026-11-07 20Z, all checks pass): strain uses Model D demand − ERCOT wind − ERCOT solar on 48/48 rows (Model A fallback). **Demand anchor** added: Model D's mean error over the last 6 actual hours (+2.9 GW) is added with weight exp(−h/12), so the first hour is 52.3 GW vs 53.1 GW actual (gap 0.8 GW, was 3.4 GW). Low-confidence threshold 0.20 → 0.50 (13/48 hours flagged). Levels 8 green / 21 yellow / 19 red; tomorrow 4–10 pm red (spike risk up to 0.71), midday green with solar. `06_explain` adds a "Recent demand level" driver for the anchor.)*

### 3.7 Report card
- [x] Score yesterday's forecast against actuals → `gold.report_card` (MAPE, spike recall, band coverage) *(`07_report_card`: 91 daily backtest rows 2026-08-08 → 11-06 (basis `model_a_p50`): MAPE 11.74 % (hour-weighted), P10–P90 coverage 80.6 %, demand MAPE 3.44 %, spikes caught 42/52 (recall 0.81); matches 04_train. 0 live rows yet: the first batch's hours get actuals from local 11-08; MERGE is idempotent. The displayed method (Model D − ERCOT renewables) can't be backtested yet (ERCOT forecasts in Silver only since ~11-04); the UI must say so)*

**✅ Checkpoint 3:** a forecast for tomorrow, plus test MAPE (target < 5%), spike recall and band coverage. *(Reached Nov 7, including the demand-anchor fix. Quote to judges: demand forecast **3.45 % test MAPE** (beats the < 5 % target; seasonal-naive 6.53 %); net-load Model A **11.8 % MAPE, 36 % better than baseline (18.6 %)**, P10–P90 coverage **80.7 %**; spike model **recall 0.81** at 9× the base rate PR-AUC (backtest 42 of 52 spike hours caught). Strain story: our ML net-load model under-read November evenings (26.6 GW vs 38.3 GW), so the live strain uses our demand model minus ERCOT's own wind and solar forecasts whenever those exist (`strain_source`), and Model A is the fallback. Rule: never show green when the grid is tight.)*

---

## Phase 4: AI Layer & Automation (1.5 h)

### 4.1 Gemini daily advice
- [ ] ~~If 1.4 showed external models are allowed: AI Gateway + `ai_query()` in SQL → `gold.daily_advice`~~ *(not used: Gemini is called from a notebook task instead)*
- [x] Gemini → `gold.daily_advice` *(deviation: done inside Databricks by `ml/09_advice.py` (Gemini REST, key from secret scope `gridwise`), with a deterministic **rules** fallback. Verified Nov 7: a local harness run called Gemini for real (`generated_by=gemini`, all checks pass); the Databricks run on 22Z wrote the row for 2026-11-08 with `generated_by=rules` because the secret scope doesn't exist yet. Open: human runs `python -m tools.setup_secrets`; the free-tier key also hit HTTP 429)*

### 4.2 "Why Red?" sentences
- [x] Gemini turns each red hour's SHAP drivers into one plain sentence *(`09_advice` writes `why_red` per red hour (18/18 covered in the Gemini test); rules sentences are used when Gemini is off. The API's `/api/forecast/drivers` also returns a plain-English `why_red`)*

### 4.3 Ripple scenarios
- [x] Precompute the participation × kWh × window grid → `gold.shift_scenarios` *(`ml/08_ripple.py`: 210 scenarios + 10,080 curve rows per run, re-scored by Models A/B. Hard checks: energy conserved (error 0), unshifted re-score equals `gold.forecasts` exactly. Afternoon runs now shift the rest of tonight's window too. Demo (5 %, 3 kWh, 4–8 pm → 10 pm–2 am): −338 MW; UI default (15 %, 5 kWh, 5–9 pm → 10 am–2 pm): −1,688 MW ≈ 17 peakers; best: −1,833 MW. Caveat: Model B barely reacts, so the UI leads with peak cut and peakers)*

### 4.4 Genie space
- [x] Create a Genie space over the Gold tables, add table descriptions + sample SQL *(space "GridWise - Texas Grid" over 6 gold tables + `silver.grid_hourly`; 77 table/column COMMENTs, re-applied by the Job's last task; `python -m tools.job genie`; see `docs/GENIE.md`)*
- [x] Test the 5 demo questions in `PROJECT_SCOPE.md` *(all 5 asked through the API and matched our own SQL; a time-zone instruction was added after Q1 first answered in the wrong zone)*

### 4.5 Databricks Job
- [~] Job `gridwise-hourly`: bronze → silver → gold → predict → explain → ripple → advice → report card → genie_comments (serverless, pinned to environment v2 / Python 3.11 to match the pickled models) *(job 128080440835123 created by `python -m tools.job create`. Last recorded run: bronze/silver/gold/predict/explain/report_card/genie_comments SUCCESS, ripple FAILED (a time-of-day assert, since fixed and passing in standalone runs), advice UPSTREAM_FAILED. **Open: one full `python -m tools.job run` with all 9 tasks green**)*
- [~] Copy the Job ID into `.env` and GitHub secrets as `DATABRICKS_JOB_ID` *(`.env` done; GitHub repo secret is for the human)*

### 4.6 End-to-end automation
- [ ] Add repo secrets and enable `.github/workflows/gridwise-hourly.yml`: ingest → upload → run Job, every hour *(workflow updated (deploy → ingest → Job → `tools.job last`); manual `workflow_dispatch` only, the cron is commented out because silver alone uses ~12 min of the Free Edition daily quota. Repo secrets not added yet)*
- [ ] Watch two consecutive runs succeed
- [x] Hourly unit works by command: `python -m ingestion.cli ingest --trigger-job` *(one end-to-end run on Nov 7 landed all 6 sources and ran the Job)*

**⚠️ Checkpoint 4 (partial):** the whole pipeline runs from **one command** with no manual steps in between, and the API re-syncs Tiger by itself after each Job run. Not yet: a fully green Job run, and an hourly schedule (held back by the Free Edition compute quota).

---

## Phase 5: Serving & Dashboard (4 h, start 5.4 during Phase 3)

### 5.1 Tiger Data schema
- [x] Hypertables `forecasts`, `actuals`, plus continuous aggregates for hourly/daily rollups *(`db/schema.sql` (not `infra/`): hypertables `forecasts` and `actuals` + `actuals_daily` continuous aggregate with refresh policy, plus drivers, report_card, shift_scenarios (+ curve), daily_advice, sync_log. Live on Tiger (Postgres 18 + TimescaleDB 2.31))*

### 5.2 Sync Gold → Tiger
- [x] Worker `publish` step *(`python -m db.sync` (SQL warehouse → Tiger; `--if-newer`, `--skip-actuals`). Tiger holds 9,598 actuals, 96 forecasts, 288 drivers, 92 report-card rows, 210 scenarios / 10,080 curve rows. `backend/app/refresh.py` polls the Jobs API every 5 min (no compute) and re-syncs after each Job run. Tiger's shift_scenarios is one sync behind gold until the next Job run)*

### 5.3 FastAPI
- [x] `/forecast`, `/forecast/drivers`, `/advice`, `/history`, `/simulate`, `/report-card`, `/chat` *(+ `/api/health`; all 8 return 200 and match the contract keys (PM check, Nov 7). Forecast band re-expressed in net-load space and brackets net load in 48/48 hours. Health age is measured from when the batch was produced (`created_at`): 28 min)*

### 5.4 Dashboard core
- [x] 48 h strain timeline with P10–P90 band, spike risk chart, best-hours card, Gemini advice panel *(Next.js 15 in `frontend/`; hero verdict ("18 red hours, peaks Sat 6 pm, 71 % spike risk"), colour-coded timeline, best/avoid windows; advice panel says honestly when it is rules-based. Lint + build clean; 390 px mobile layout checked)*

### 5.5 Ripple panel
- [x] Sliders → before/after curve, Δ peak MW, Δ spike probability, Δ red hours *(sliders snap to the precomputed grid, so live results are exact; headline tiles show peak cut (GW) and gas peakers avoided; spike/red-hour changes appear on a secondary line only when they change)*

### 5.6 Why Red? + report card
- [x] Hover tooltips on red hours; yesterday's accuracy widget *("Why this color?" panel with ranked drivers in GW and a plain sentence; report card shows backtest MAPE / band coverage / spike recall and labels backtest vs live)*

### 5.7 Chat box
- [x] "When should I charge my EV?" answered by Gemini using the live forecast *(`POST /api/chat` uses Gemini with the live forecast as context and returns `highlight_hours`. Verified: a clean fallback to the rules answer. Currently rules-only because the Gemini key returned HTTP 429 (quota); re-check `generated_by` before the demo)*

### 5.8 Deploy
- [ ] Vultr VM + Docker Compose + Caddy (HTTPS); GoDaddy A record → Vultr IP *(`backend/Dockerfile` exists; the container needs `DATABRICKS_HOST/TOKEN/WAREHOUSE_ID/JOB_ID` + `TIGER_DATABASE_URL` + `GEMINI_API_KEY` in its env)*
- [ ] Move the hourly worker to a Vultr cron (optional; GitHub Actions is fine)

**⚠️ Checkpoint 5 (local only):** the full dashboard runs locally against live Tiger data (API on :8000, Next.js on :3000). Not yet live at `https://gridwise.tech` (5.8).

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
