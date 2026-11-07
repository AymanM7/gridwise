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
- [ ] ERCOT 5-min load and 15-min prices → hourly averages on `interval_start_utc`
- [ ] Wind/solar reports: keep the **latest publish** per hour (actuals) and the latest forecast per hour
- [ ] Combine history (EIA) + live (ERCOT): ERCOT wins where both exist
- [ ] **DST check:** show that the fall-back hour (`interval_start_local` with `-05:00` and `-06:00`) maps to two distinct UTC hours
- [ ] Cross-check EIA's hour-ending convention against ERCOT live load on the overlap days

### 2.2 Silver: weather
- [ ] Union archive + forecast (forecast wins for recent hours)
- [ ] Pivot the 4 cities and compute a **population-weighted** Texas temperature and heat index

### 2.3 Silver: join
- [ ] `silver.grid_hourly`: one row per UTC hour with grid + weather columns
- [ ] Dedupe; assert no duplicate `ts_utc`

### 2.4 Gold: features
- [ ] `net_load_mw = demand − wind − solar`
- [ ] Lags (1, 24, 168 h), rolling means, hour, day of week, month, US holidays, CDD/HDD

### 2.5 Gold: strain and spikes
- [ ] `gold.strain_hourly`: strain index 0–100 (monthly percentile of net load) + green/yellow/red
- [ ] `gold.spike_events`: `price > $100/MWh`

### 2.6 Data quality
- [ ] Missing-hour count per month, null rates, min/max sanity checks (displayed in the notebook)

**✅ Checkpoint 2:** `gold.features` has one clean row per hour from 2023 → now.

---

## Phase 3: Machine Learning (2.5 h)

### 3.1 Split and baseline
- [ ] Time-based split: train ≤ 2025-06, validate 2025-07 → 2025-09, test the most recent 3 months
- [ ] Seasonal-naive baseline (same hour last week) so the MAPE has something to beat

### 3.2 Model A: net load
- [ ] LightGBM regressor for t+1 … t+48 h (P50) + quantile models (P10, P90)

### 3.3 Model B: price spike
- [ ] LightGBM classifier, `is_unbalance=True`, features include Model A's forecast and ERCOT's wind/solar forecasts

### 3.4 MLflow and registry
- [ ] Log params, metrics and artifacts; register `grid.ml.net_load` and `grid.ml.spike` with alias `@champion`

### 3.5 SHAP drivers
- [ ] Top-3 drivers per forecast hour → `gold.forecast_drivers`

### 3.6 Batch inference
- [ ] Next 48 h → `gold.forecasts` (P10/P50/P90, spike_prob, strain, level)

### 3.7 Report card
- [ ] Score yesterday's forecast against actuals → `gold.report_card` (MAPE, spike recall, band coverage)

**✅ Checkpoint 3:** a forecast for tomorrow, plus test MAPE (target < 5%), spike recall and band coverage.

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
