# ⚡ GridWise

### Know when the Texas grid will be stressed, and what to do about it.

GridWise forecasts **when Texas's power grid (ERCOT) will be strained and when wholesale prices will spike, 24–48 hours ahead**, then turns that forecast into plain-English advice: *"run the dryer after 10 pm, pre-cool the house before 4 pm, charge the EV overnight."*

Built at **TAMUhack 26** · Tracks: **Databricks** · **Gemini** · **Tiger Data** · **Vultr** · **GoDaddy Registry**

> **"GridWise forecasts when Texas's power grid will be stressed and tells you exactly when to run your dryer, charge your EV, or crank the AC, so you save money and help keep the lights on."**

---

## Why this matters

Texas runs its own power grid. ERCOT serves about 90% of the state's electricity load and is mostly **isolated** from the rest of the US, so when supply gets tight, Texas can't just import power from its neighbors.

- **Winter Storm Uri (Feb 2021)** left more than 4.5 million Texas homes and businesses without power, some for days.
- On hot summer evenings, demand peaks just as **solar output fades**. That gap has to be filled by gas plants, and it's when the grid is most fragile.
- **Wholesale prices can jump 50–100×** within hours when reserves run low. Customers on time-of-use, "free nights" or variable-rate plans, and EV owners, feel that directly.

ERCOT publishes a lot of data, but it's raw and hard to read. **Most people have no simple way to know when the grid will be tight tomorrow, or what to do about it.** GridWise closes that gap.

## What GridWise does

| | Feature | What you see |
|---|---|---|
| 🚦 | **Strain timeline** | Tomorrow's 48 hours, colored green / yellow / red by a 0–100 strain index |
| 💸 | **Price-spike risk** | The probability each hour that real-time prices exceed $100/MWh |
| 🕐 | **Best hours card** | The cheapest, lowest-stress windows to run appliances or charge an EV |
| 🤖 | **Gemini advice** | A daily plain-English plan, plus a chat box: *"When should I charge my EV tomorrow?"* |
| 🔎 | **Genie Q&A** | Ask the grid's history in plain English: *"What was the most strained hour of summer 2025?"* |
| 🌊 | **Ripple simulator** *(novel)* | *"What if 5% of Texas homes shifted their dryer to 10 pm?"* Watch the red zone shrink, re-scored by the real models |
| ❓ | **"Why Red?" + report card** *(novel)* | Every red hour explains its top 3 drivers (heat, low wind, solar fade), shows a confidence band, and yesterday's forecast is graded against reality |

The key metric is **net load = demand − wind − solar**: the part of demand that gas plants have to cover. That, more than total demand, is what drives strain and price spikes.

## How it works

![GridWise system architecture](docs/architecture.png)

1. **Ingest:** a Python worker pulls ERCOT data (via [gridstatus](https://github.com/gridstatus/gridstatus)), EIA-930 hourly history, and Open-Meteo weather for Houston, DFW, Austin and San Antonio. It lands raw parquet into a Unity Catalog Volume every hour.
2. **Lakehouse (Databricks):** Auto Loader → **Bronze** (raw) → **Silver** (hourly UTC, DST-safe, deduped, grid + weather joined) → **Gold** (net load, strain index, spike events, model features).
3. **Machine learning (MLflow + Unity Catalog):**
   - **Model A:** a LightGBM net-load forecast for the next 1–48 h, with P10/P50/P90 bands.
   - **Model B:** a price-spike classifier.
   - **SHAP:** explains every forecast hour.
4. **AI layer:** **Gemini** writes the daily advice and "Why Red?" sentences inside the pipeline; **Genie** answers natural-language questions over the Gold tables.
5. **Serving:** forecasts sync to **Tiger Data** (TimescaleDB hypertables + continuous aggregates), a **FastAPI** service on **Vultr** serves them, and the dashboard lives on a **GoDaddy** domain.

More detail: [ARCHITECTURE.md](ARCHITECTURE.md) (box diagrams for every flow) · [DASHBOARD.md](DASHBOARD.md) (dashboard architecture + user guide) · [DASHBOARD_V3.md](DASHBOARD_V3.md) (full architecture diagrams) · [JUDGES.md](JUDGES.md) (demo script) · [TECH_STACK.md](TECH_STACK.md)

### A detail judges ask about: daylight saving time

ERCOT reports in Central time. Every November, the 1:00 am hour happens **twice**, and every March, 2:00 am **doesn't exist**. Joined naively, that hour gets dropped or double-counted. GridWise keeps the original local time with its UTC offset, converts everything to UTC before aggregating, and shows the check in the Silver notebook.

## Who it's for

- **Households on time-of-use or variable-rate plans:** shift laundry, dishwashers and pool pumps to save money.
- **EV owners:** charge in the cheapest, cleanest hours.
- **Anyone who wants to help prevent outages:** small shifts by many homes add up (that's what Ripple shows).
- **Businesses:** retail electricity providers, EV fleets, smart-home and demand-response companies.

👉 Full personas, user journeys and business use cases: **[CUSTOMERS.md](CUSTOMERS.md)**

## Project status

| Phase | Status |
|---|---|
| 1. Setup & ingestion → Bronze | ✅ Done: 2023 → today loaded (EIA 33.9k hours, prices 134.6k rows, weather 134.5k rows) |
| 2. Silver & Gold | ✅ Done: `gold.features` has one clean row per hour (33.8k rows), plus strain index and spike events; DST-safe |
| 3. Machine learning | ✅ Done: demand **3.45 % test MAPE**, net load 11.8 % (36 % better than baseline), P10–P90 coverage 80.7 %, spike recall 0.81; SHAP drivers; daily report card |
| 4. AI layer & automation | 🟡 Mostly done: Gemini advice + "Why Red?" (rules fallback live until the `gridwise` secret scope exists), Ripple grid (210 scenarios), Genie space (5 demo questions verified), 9-task Job. Open: one all-green Job run; hourly schedule held back by the Free Edition quota |
| 5. Serving & dashboard | 🟡 Runs locally: Tiger Data sync, FastAPI (8 endpoints), Next.js dashboard (timeline, Why Red?, advice, Ripple, report card, chat). Open: Vultr + GoDaddy deploy |
| 6. Ship | ⏳ |

The step-by-step plan is in [PHASES.md](PHASES.md); the scope and success criteria are in [PROJECT_SCOPE.md](PROJECT_SCOPE.md).

## Run it yourself

**Prerequisites:** Python 3.12, a free [Databricks Free Edition](https://www.databricks.com/learn/free-edition) workspace, and a free [EIA API key](https://www.eia.gov/opendata/register.php).

```powershell
git clone https://github.com/AymanM7/gridwise.git
cd gridwise
python -m venv .venv
.venv\Scripts\activate                      # macOS/Linux: source .venv/bin/activate
pip install -r ingestion/requirements.txt
copy .env.example .env                      # then fill in EIA_API_KEY (and others as you reach them)
python tools/check_secrets.py --install   # blocks commits that contain secrets

python -m tools.login https://<your-workspace>.cloud.databricks.com   # browser login, saves a token to .env
python -m tools.deploy --run 00_setup      # creates catalog/schemas/volumes
python -m ingestion.cli backfill --start 2023-01-01   # ~10 min, history → Databricks
python -m ingestion.cli ingest                 # latest live data
python -m tools.deploy --run 01_bronze     # load Bronze tables
python -m tools.sql "SELECT count(*) FROM grid.bronze.eia_hourly"
```

Add `--local-only` to any `ingestion.cli` command to test without Databricks (it writes to `data/landing/`).

### Pipeline, ML and the Databricks Job

```powershell
python -m tools.deploy --run 02_silver 03_gold 04_train 05_predict 06_explain 08_ripple 09_advice 07_report_card
python -m tools.setup_secrets              # one time: puts GEMINI_API_KEY in Databricks secret scope 'gridwise'
python -m tools.setup_secrets --check
python -m tools.job create                 # creates/updates job 'gridwise-hourly', saves DATABRICKS_JOB_ID to .env
python -m tools.job run                    # runs all 9 tasks and prints each task's status
python -m tools.job last                   # status of the latest run (no compute)
python -m tools.job genie                  # creates/updates the Genie space (see docs/GENIE.md)
python -m ingestion.cli ingest --trigger-job   # the hourly unit: fetch → upload → run the Job
```

### Serving: Tiger Data, API, dashboard

Needs `TIGER_DATABASE_URL` in `.env` (Tiger Data / TimescaleDB) and Node 22.

**One command for everything:** syncs Tiger, starts the API on :8000 and the dashboard on :3000, then opens the browser. Ctrl+C stops it all.

```powershell
python -m tools.dev              # add --no-sync to skip the Tiger sync, --fixtures for demo data only
```

Or start each part separately:

```powershell
pip install -r backend/requirements.txt
python -m db.sync                          # applies db/schema.sql, copies Gold → Tiger (--if-newer, --skip-actuals)

# Terminal 1: API on http://localhost:8000 (docs at /docs); re-syncs Tiger after each Job run
python -m uvicorn backend.app.main:app --port 8000

# Terminal 2: dashboard on http://localhost:3000
cd frontend
npm install
npm run dev                                # live API (NEXT_PUBLIC_API_BASE_URL, default http://localhost:8000)
# npm run dev:fixtures                     # demo mode with bundled data, no backend needed
# npm run build && npm run start           # production build (no dev badge)
```

### Demo-morning refresh (one line)

Fresh data end to end (ingest -> Databricks Job -> Tiger), from the repo root:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python -m ingestion.cli ingest --trigger-job && PYTHONIOENCODING=utf-8 .venv/Scripts/python -m db.sync
```

The Job takes ~10-15 min of the Free Edition daily quota. If the API is running, the `db.sync` half is
automatic: the API's background refresher (`backend/app/refresh.py`) polls the Jobs API every 5 min (no compute)
and re-syncs Tiger as soon as a Job run finishes. `python -m db.sync --if-newer` does the same check by hand.
The dashboard's "pipeline may be delayed" banner appears only when the newest forecast batch was *produced*
more than 2 h ago (`gold.forecasts.created_at`), not from the data anchor hour, which always trails ERCOT/EIA by ~3 h.

### Why there's a "worker"

Databricks Free Edition restricts outbound internet from notebooks, so a small worker fetches data outside Databricks and uploads it **into** a Unity Catalog Volume, which is always allowed. Everything else (transforms, ML, Gemini, Genie, the hourly Job) runs in Databricks.

## Repository layout

```text
gridwise/
├── ingestion/        📥 DATA INGESTION: fetch ERCOT · EIA · Open-Meteo, upload into Databricks
│   └── sources/        ercot.py · eia.py · weather.py
├── pipeline/         🏗️ DATABRICKS PIPELINE: 00_setup → 01_bronze → 02_silver → 03_gold
├── ml/               🤖 MACHINE LEARNING + AI: 04_train · 05_predict · 06_explain · 07_report_card · 08_ripple · 09_advice
├── db/               🗄️ SERVING DATABASE: Tiger Data schema + Gold → Tiger sync (db.sync)
├── backend/          🔌 API: FastAPI (8 endpoints) + Tiger auto-refresh
├── frontend/         🖥️ DASHBOARD: Next.js 15 (target: gridwise.tech)
├── infra/            🚀 DEPLOYMENT: docker-compose · Caddy · Vultr                   (Phase 5)
├── tools/            🧰 DEV HELPERS: login · deploy · sql · job · setup_secrets · check_secrets
├── docs/             📚 architecture image · data contract · diagram generator
├── .github/workflows/  secret-scan (every push) · gridwise-hourly (pipeline trigger)
└── .gitleaks.toml    secret-detection rules
```
Each folder has its own `README.md` explaining what's inside and how to run it.

## Security

API keys live **only** in `.env`, which is git-ignored. A pre-commit hook (`tools/check_secrets.py`) and a gitleaks GitHub Action (rules in `.gitleaks.toml`) block any commit that contains a key, token or database password.

## Data sources & credits

- **ERCOT** public data via the open-source [gridstatus](https://github.com/gridstatus/gridstatus) library
- **U.S. EIA** Hourly Electric Grid Monitor (EIA-930)
- **Open-Meteo** weather API (free, no key)

GridWise is a hackathon project and **not affiliated with ERCOT**. Forecasts are informational, not grid-operations or financial advice.
