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
