# 🏗️ pipeline/: Databricks Data Pipeline (Bronze → Silver → Gold)

Databricks notebooks (SOURCE `.py` format) that turn raw uploads into clean, model-ready Delta tables in Unity Catalog (`grid.*`).

| Notebook | Output | What it does |
|---|---|---|
| `00_setup` | catalog `grid`, schemas, volumes | One-time layout: `bronze/silver/gold/ml`, `bronze.landing`, `bronze.checkpoints` |
| `00_connectivity_check` | (report) | Shows which outside services Free Edition can reach (ERCOT, EIA, Open-Meteo, Gemini, Tiger) |
| `01_bronze` | `bronze.*` (7 tables) | Auto Loader: incrementally loads new parquet files from the landing volume, as-is plus lineage columns |
| `02_silver` | `silver.grid_hourly`, `silver.weather_hourly`, `silver.dq_checks` | One row per UTC hour; ERCOT live data wins over EIA history; DST fall-back check; population-weighted weather; data-quality checks |
| `03_gold` | `gold.features`, `gold.strain_hourly`, `gold.strain_reference`, `gold.spike_events`, `gold.dq_checks` | Net load, lag-48 model features (no leakage), 0–100 strain index, price-spike events |

The data contract (columns, rules, acceptance checks) is in [`docs/PHASE2_CONTRACT.md`](../docs/PHASE2_CONTRACT.md).

## Run

```powershell
python -m tools.deploy --run 01_bronze 02_silver 03_gold
```
In the workspace these live at `/Users/<you>/gridwise/pipeline/`. Each notebook ends with a JSON summary (`all_pass`, `failed`) printed by `tools.deploy`.

## Hourly Job: `gridwise-hourly` (Phase 4.5 / 4.6)

Defined in code by [`tools/job.py`](../tools/job.py). It's a Databricks Job of serverless notebook tasks
with job parameter `catalog=grid`, `max_concurrent_runs=1`, queueing on, and **no schedule**:

```
01_bronze -> 02_silver -> 03_gold -> 05_predict -> 06_explain -> 07_report_card --> 09_advice -> genie_comments
                                                              \-> 08_ripple ------/
```

* Every task is pinned to **serverless environment version 2 (Python 3.11)** via a job environment. The
  `@champion` pyfunc models were pickled by `04_train` on Python 3.11, and on the newer default environment
  (Python 3.12) `model.predict` fails with `SystemError: unknown opcode`. If you bump `ENV_VERSION` in
  `tools/job.py`, re-train in that same environment.
* Each task runs only if its upstream tasks succeeded, so a failed Silver/Gold never feeds stale data to predict.
  The exception is `genie_comments`, which always runs.
* `genie_comments` is a small notebook that `tools/job.py` generates and uploads to `/Users/<you>/gridwise/tools/`.
  It re-applies the Genie table and column COMMENTs, which `03_gold`'s `CREATE OR REPLACE` drops. It runs last so
  no `ALTER` races an append to `gold.forecasts`. See [`docs/GENIE.md`](../docs/GENIE.md).

```powershell
python -m tools.job create     # upload notebooks + create-or-update the job; saves DATABRICKS_JOB_ID to .env
python -m tools.job show       # task graph
python -m tools.job run        # run_now, wait, print per-task status + notebook summaries
python -m tools.job last       # per-task status of the latest run (no compute)
python -m tools.job comments   # Genie COMMENTs now via the SQL warehouse;  python -m tools.job genie = Genie space
python -m ingestion.cli ingest --trigger-job   # the hourly unit: fetch -> upload to Volume -> run the job
```

**Trigger:** Free Edition notebooks can't reach ERCOT, EIA or Open-Meteo. The hourly run is therefore
`ingestion.cli ingest --trigger-job`, run locally or by `.github/workflows/gridwise-hourly.yml` (manual dispatch;
the cron is commented out because of the daily serverless quota). The workflow lists the repo secrets it needs.
`ingestion.cli` doesn't upload notebooks, so run `python -m tools.deploy` or `tools.job create` after editing one.
The workflow already syncs notebooks first.
