# 🖥️ GridWise Dashboard V2

What each part of the redesigned dashboard does, which API feeds it, and how Databricks powers it, plus the deployment decision (Vultr or not).

Related: [DASHBOARD.md](DASHBOARD.md) (architecture + user guide) · [JUDGES.md](JUDGES.md) (demo script) · [ARCHITECTURE.md](ARCHITECTURE.md)

---

## 1. The idea in one picture

GridWise is a **weather forecast for the Texas power grid**: how stressed it will be over the next 48 hours, why, and when to use electricity.

```text
 ┌──────────────── DATABRICKS: does all the thinking, ahead of time ────────────────┐
 │  ERCOT · EIA-930 · Open-Meteo                                                     │
 │     → Auto Loader → Bronze → Silver → Gold                                        │
 │     → Model A (net load) · Model B (price spikes) · Model D (demand)  [MLflow/UC] │
 │     → SHAP explanations → Ripple scenarios → Gemini advice → Report card          │
 │  all chained in one Databricks Job: gridwise-hourly (9 tasks)                     │
 └───────────────────────────────────────┬───────────────────────────────────────────┘
                                         │  db.sync (copies Gold tables)
                                         ▼
                            TIGER DATA (TimescaleDB): stores results
                                         │  SQL
                                         ▼
                            FASTAPI: 8 endpoints  ───►  Gemini (live chat only)
                                         │  JSON
                                         ▼
                            NEXT.JS DASHBOARD (V2)
```

**The rule:** Databricks *produces* every number; the dashboard only *displays* them. A page view never runs a model and never touches Databricks, so it loads in **< 0.5 s** and costs **no Databricks compute**.

---

## 2. What's new in V2

| V1 | V2 |
|---|---|
| Emoji icons | Clean line icons (lucide), Geist font, dot-grid backdrop |
| Plain header text | **Hero**: big verdict, animated strain ring, stat chips, Live pill |
| Recharts bar chart | Hand-built timeline: bars grow in, sliding selection, "Now" marker, keyboard navigation |
| Static lists | Staggered entrances, numbers count up, hover lifts |
| Basic chat box | AI-chat style: bubbles, typing indicator, highlighted-hours chip |
| Native sliders | Custom Ripple sliders, segmented controls, a before/after chart that morphs |
| Long single column | Sticky nav (Timeline · Plan · Spikes · Ask · Ripple · Accuracy) and a two-column layout |

All animations switch off automatically for users who prefer reduced motion.

---

## 3. Each part of the dashboard

For each section: **what it shows → API → where in Databricks it comes from.**

### 3.1 Sticky top bar
- **Shows:** GridWise logo and jump links; the active link follows your scroll.
- **API:** none (pure frontend).
- **Databricks:** none.

### 3.2 Hero: tomorrow at a glance
- **Shows:** the verdict (*"Tight grid ahead: 18 red hours"*), the peak-strain ring (0–100), the green/yellow/red hour mix, peak net load, max spike risk, and a **Live / Delayed / Demo** pill with data freshness.
- **API:** `GET /api/health` (freshness), `GET /api/forecast?hours=48` (everything else).
- **Databricks:** `ml/05_predict.py` writes `gold.forecasts`: Model A net load, Model B spike risk, and the strain index.

### 3.3 48-hour strain timeline
- **Shows:** one bar per hour. Height = forecast **net load** (demand − wind − solar); color = strain (🟢 < 60 · 🟡 60–85 · 🔴 > 85). A grey band = P10–P90 uncertainty, and a dotted cap = uncertain hour. Tap or arrow-key through hours; chat suggestions glow here.
- **API:** `GET /api/forecast?hours=48`.
- **Databricks:**
  - **Model A** (LightGBM quantile regression, in MLflow / Unity Catalog `@champion`) gives P10/P50/P90. Test MAPE is 11.8% vs an 18.6% baseline.
  - **Model D** forecasts demand, anchored on the last 6 actual hours.
  - **Strain** = the percentile of net load against the same month over 3 years (`gold.strain_reference`, built in `pipeline/03_gold.py`), +15 if spike risk > 50%.

### 3.4 Why this color? *(novel feature)*
- **Shows:** for the selected hour, the **top 3 drivers** in ± GW (e.g. *"Light wind: only 4.8 GW → +8.2 GW net load"*), a plain-English sentence, and a confidence meter.
- **API:** `GET /api/forecast/drivers?ts=<hour>`; the sentence comes from `GET /api/advice` (`why_red`).
- **Databricks:**
  - `ml/06_explain.py` computes **SHAP** values for every forecast hour → `gold.forecast_drivers`.
  - `ml/09_advice.py` writes the sentence with Gemini.

### 3.5 Best hours
- **Shows:** the calmest windows to use power and the windows to avoid, each with a mini strain bar and its spike risk.
- **API:** `GET /api/forecast` (`summary.best_windows` / `avoid_windows`).
- **Databricks:** derived from the `gold.forecasts` hours.

### 3.6 Your plan
- **Shows:** a headline plus 3–5 actions (*pre-cool before 4 pm, charge the EV 1–4 am…*). A badge shows **Gemini** (animated border) or **Rules**.
- **API:** `GET /api/advice`.
- **Databricks:** `ml/09_advice.py` sends the forecast summary to **Gemini** inside the Job → `gold.daily_advice`. It falls back to a rules engine if Gemini is unavailable.

### 3.7 Spike risk
- **Shows:** the chance each hour that real-time prices exceed **$100/MWh**, the 50% line, the peak marked. Click a point to explain that hour.
- **API:** `GET /api/forecast`.
- **Databricks:** **Model B** (LightGBM classifier). It catches 81% of spike hours, though spikes happen in only about 2.4% of hours.

### 3.8 Ask GridWise (chat)
- **Shows:** a chat thread. Answers can **highlight hours on the timeline**.
- **API:** `POST /api/chat` `{question}` → `{answer, highlight_hours}`.
- **Databricks:** indirect. The API sends your question plus the Databricks forecast and plan (from Tiger) to **Gemini 2.5 Flash** live. If Gemini fails, a rules engine answers.

### 3.9 Ripple: what if Texas shifted? *(novel feature)*
- **Shows:** sliders for **homes participating** (1–25%) and **kWh shifted** (1–8), *from* (4–8 / 5–9 pm) and *to* (solar hours / late night / overnight) controls, four live stats (**peak cut**, **gas peakers avoided**, max spike risk, red hours), a summary sentence, and a before/after curve.
- **API:** `GET /api/simulate?pct=&kwh=&from=&to=`, debounced 250 ms.
- **Databricks:** `ml/08_ripple.py` precomputes **210 scenarios** on about 9 M homes, re-scored with Model B → `gold.shift_scenarios` and `gold.shift_scenario_curves`. The API snaps the sliders to the nearest scenario, so the result is instant.

### 3.10 Report card
- **Shows:** yesterday's net-load error, demand error, spikes caught, % of actuals inside the band (target 80%), and a 7-day table with good/ok/poor chips and an error sparkline.
- **API:** `GET /api/report-card?days=7`.
- **Databricks:** `ml/07_report_card.py` grades published forecasts against ERCOT actuals → `gold.report_card`. Older days are backtests.

### 3.11 Last 30 days
- **Shows:** daily peak net load (bars colored by that day's max strain) and the max real-time price (line).
- **API:** `GET /api/history?days=30`.
- **Databricks:** hourly actuals from Silver/Gold, rolled up daily in Tiger by the `actuals_daily` **continuous aggregate**.

### 3.12 Footer
- **Shows:** data credits and the not-affiliated-with-ERCOT disclaimer. **API:** none.

---

## 4. API reference

### 4.1 GridWise API (FastAPI, port 8000)

Docs at `/api/docs`. All return 200 today, each in 0.25–0.6 s.

| Endpoint | Reads (Tiger table) | Feeds |
|---|---|---|
| `GET /api/health` | `forecasts` (latest run) | Live pill, freshness, delayed notice |
| `GET /api/forecast?hours=48` | `forecasts` | Hero, timeline, spike risk, best hours |
| `GET /api/forecast/drivers?ts=` | `forecast_drivers` | Why this color? |
| `GET /api/advice` | `daily_advice` | Your plan, Why-red sentence |
| `GET /api/simulate?pct=&kwh=&from=&to=` | `shift_scenarios`, `shift_scenario_curves` | Ripple |
| `GET /api/report-card?days=7` | `report_card` | Report card |
| `GET /api/history?days=30` | `actuals_daily` | Last 30 days |
| `POST /api/chat` | `forecasts`, `daily_advice` → **Gemini** | Ask GridWise |

### 4.2 External services

| Service | Role | When it's called | Status |
|---|---|---|---|
| **Tiger Data** (PostgreSQL + TimescaleDB) | Serving database | Every API request | ✅ |
| **Google Gemini** 2.5 Flash | Chat (live) + plan (in the Databricks Job) | On chat questions; once per Job run | ⚠️ quota exceeded (429), so the rules fallback is active |
| **Databricks Jobs API** | Detect a finished pipeline run → auto re-sync Tiger | Background, every 5 min (no compute) | ✅ |
| **Databricks SQL warehouse** | `db.sync` reads Gold; freshness check | Background, only if the forecast is > 2 h old | ✅ |
| **ERCOT** (gridstatus) · **EIA-930** · **Open-Meteo** | Raw data | Ingestion only, never on a page view | ✅ |

---

## 5. How Databricks is integrated

### 5.1 Databricks features used

| Databricks feature | What GridWise does with it | Dashboard parts it powers |
|---|---|---|
| **Unity Catalog Volume** | The ingestion worker uploads raw parquet to `/Volumes/grid/bronze/landing/` (Free Edition blocks most outbound internet from notebooks) | All, as the entry point |
| **Auto Loader** | `pipeline/01_bronze.py` loads only new files into Bronze | All |
| **Delta Lake medallion** | Bronze (raw) → Silver (hourly UTC, safe across daylight-saving changes, deduplicated, joined) → Gold (features, strain reference, spikes) | All |
| **MLflow + UC model registry** | Models A, B and D trained in `ml/04_train.py`, versioned, loaded by the `@champion` alias | Hero, timeline, spike risk, Ripple |
| **Serverless notebooks** | Predict, SHAP, Ripple, advice, report card | Every data section |
| **Databricks Job** `gridwise-hourly` | 9 chained tasks: bronze → silver → gold → predict → explain → ripple → advice → report card → genie comments | Keeps everything fresh with one trigger |
| **SQL warehouse** | `db.sync` copies Gold → Tiger; freshness checks | The bridge to the dashboard |
| **Genie** | "GridWise - Texas Grid" space: plain-English questions over the Gold tables | Shown in the demo next to the dashboard (lives in Databricks) |

### 5.2 Notebook → table → endpoint → section

| Notebook | Gold table | API | Dashboard section |
|---|---|---|---|
| `ml/05_predict.py` | `forecasts` | `/forecast`, `/health` | Hero, timeline, spike risk, best hours |
| `ml/06_explain.py` | `forecast_drivers` | `/forecast/drivers` | Why this color? |
| `ml/08_ripple.py` | `shift_scenarios`, `shift_scenario_curves` | `/simulate` | Ripple |
| `ml/09_advice.py` | `daily_advice` | `/advice`, `/chat` | Your plan, Why-red sentence, chat context |
| `ml/07_report_card.py` | `report_card` | `/report-card` | Report card |
| `pipeline/02_silver.py` | Silver/Gold actuals → Tiger `actuals_daily` | `/history` | Last 30 days |
| `pipeline/03_gold.py` | `strain_reference` | inside `/forecast` | Every strain color |

### 5.3 How fresh data reaches the page

```text
python -m ingestion.cli ingest --trigger-job      (or the GitHub Action)
   → new files land in the UC Volume → the Databricks Job runs its 9 tasks
   → the API's background loop sees the finished run (Jobs API, every 5 min)
   → it runs db.sync → Tiger is updated → the dashboard refetches every 10 min
```

### 5.4 Why the dashboard doesn't query Databricks directly

- **Speed:** Tiger answers in milliseconds; a serverless warehouse can take seconds to wake up.
- **Cost:** Free Edition has a daily compute quota, and per-page-view queries would burn through it.
- **Reliability:** if Databricks is paused or the quota runs out, the dashboard keeps serving the last forecast.

---

## 6. Should we use Vultr?

### Recommendation: **Yes, deploy the API + dashboard on one small Vultr VM.**

| Reason | Why it matters |
|---|---|
| **Sponsor tracks** | Deploying on Vultr (and pointing a GoDaddy domain at it) is what qualifies GridWise for the **Vultr** and **GoDaddy** tracks. Without it, those two tracks are off the table |
| **Judges get a live URL** | Judges and the Devpost page can open `https://<your-domain>` on their phones. A localhost demo only works on your laptop |
| **Our stack fits it** | One VM runs Docker Compose (FastAPI + Next.js) behind Caddy for automatic HTTPS. Tiger and Databricks stay where they are, so the VM is lightweight |
| **Cheap** | The smallest shared-CPU VM (≈ 1 vCPU / 1–2 GB) is enough. Ask the Vultr booth for hackathon credits |

### When to skip Vultr

- You're short on time near the deadline, and **local + fixtures demo** is enough for you. You'd give up the Vultr and GoDaddy tracks.
- **Fallback if Vultr setup stalls:** the frontend on **Vercel** (free) in fixtures mode for a public link, with a live local demo for judges. It's simpler, but it doesn't count for the Vultr track.

### Option comparison

| Option | Setup time | Public URL | Live data | Vultr / GoDaddy tracks |
|---|---|---|---|---|
| **Vultr VM + GoDaddy domain** ✅ | ~45–60 min | ✅ `https://gridwise.<tld>` | ✅ | ✅ both |
| Vercel (frontend, fixtures) | ~10 min | ✅ | ❌ snapshot only | ❌ |
| Localhost only | 0 min | ❌ | ✅ | ❌ |

### What deployment needs (Phase 5.8)

**You do these** (accounts and payment are yours):
1. Create a Vultr account → deploy an Ubuntu 24.04 VM → note its IP.
2. Register a domain at GoDaddy → add an **A record** pointing to the VM IP.

**Then I can build:**
- `infra/docker-compose.yml`: `api` (FastAPI :8000) + `web` (Next.js :3000) + `caddy` (:80/:443).
- `infra/Caddyfile`: `/api/*` → api, everything else → web, automatic HTTPS.
- A `frontend/Dockerfile` (production build; `backend/Dockerfile` already exists).
- `infra/vultr.md`: copy-paste setup steps for the VM.
- The VM's `.env` needs `TIGER_DATABASE_URL`, `GEMINI_API_KEY`, `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_WAREHOUSE_ID` and `DATABRICKS_JOB_ID`. Copy it over with `scp`; **never commit it**.

---

## 7. Status (2026-11-07)

| Item | Status |
|---|---|
| Dashboard V2 (redesign) | ✅ Running locally, tsc + eslint clean |
| All 8 API endpoints | ✅ 200 |
| Tiger Data | ✅ synced (latest run Nov 7, 22:00 UTC) |
| Databricks Job | ⚠️ last run *success with failures*. Needs one fully green run (`python -m tools.job run`) |
| Gemini | ⚠️ quota exceeded, so the rules fallback is showing |
| Databricks secret scope | ❌ run `python -m tools.setup_secrets` |
| Vultr + GoDaddy deploy | ⏳ waiting on accounts (Phase 5.8) |

**Run locally:** `python -m tools.dev` → http://localhost:3000 · API docs: http://localhost:8000/api/docs
