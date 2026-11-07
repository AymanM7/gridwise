# GridWise: Texas Grid Stress Forecaster

Forecasts when the ERCOT grid will be strained and tells Texans when to run the dryer, charge the EV or pre-cool the house.

| Doc | What's in it |
|---|---|
| [PROJECT_SCOPE.md](PROJECT_SCOPE.md) | Problem, scope, novel features, success criteria, demo script |
| [PHASES.md](PHASES.md) | Step-by-step build plan, 1.1 → 6.4 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design diagrams, data model, ML, API, deployment |
| [TECH_STACK.md](TECH_STACK.md) | Tools, packages, free-tier constraints |

## Quick start (Phase 1)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r worker/requirements.txt
copy .env.example .env        # fill in DATABRICKS_HOST, DATABRICKS_TOKEN, EIA_API_KEY
```

1. In Databricks, add this repo as a **Git folder**, then run `notebooks/00_setup` and `notebooks/00_connectivity_check`.
2. Load history (one time, about 10 minutes):
   ```powershell
   python -m worker.cli backfill --start 2023-01-01
   ```
3. Pull the latest data (this runs hourly later):
   ```powershell
   python -m worker.cli ingest
   ```
4. In Databricks, run `notebooks/01_bronze`. The Bronze tables now hold 2023 → today.

Add `--local-only` to either worker command to test without Databricks (it writes to `data/landing/`).

## Layout

```text
worker/       fetches ERCOT (gridstatus), EIA-930, Open-Meteo → uploads parquet to the UC Volume
notebooks/    Databricks notebooks (setup, bronze, then silver/gold/ML in later phases)
.github/      hourly GitHub Actions schedule (Phase 4.6)
docs/         architecture diagram (svg/png)
```
