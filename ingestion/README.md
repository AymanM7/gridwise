# 📥 ingestion/: Data Ingestion

Fetches raw grid and weather data **outside Databricks** and uploads it **into** a Unity Catalog Volume (`/Volumes/grid/bronze/landing/<source>/`).
It runs outside Databricks because Free Edition restricts outbound internet from notebooks; uploading *into* Databricks is always allowed.

| File | What it does |
|---|---|
| `cli.py` | Entry point: `backfill` (one-time history) and `ingest` (hourly refresh) |
| `sources/ercot.py` | ERCOT via [gridstatus]: live load, 15-min prices, wind/solar actuals + 7-day forecasts, yearly price archive |
| `sources/eia.py` | EIA-930: hourly ERCOT demand, wind, solar history (2023 → now) |
| `sources/weather.py` | Open-Meteo: hourly weather for Houston, DFW, Austin, San Antonio (archive + forecast) |
| `sources/common.py` | Column tidying, UTC conversion (keeps the local time + offset for DST checks) |
| `landing.py` | Writes parquet locally (`data/landing/`) and uploads it to the Volume; can trigger the Databricks Job |
| `config.py` | Reads `.env`; city coordinates and population weights; price hub |
| `requirements.txt` | Python dependencies for ingestion + tools |

## Run

```powershell
python -m ingestion.cli backfill --start 2023-01-01   # ~10 min, one time
python -m ingestion.cli ingest                        # latest live data (hourly)
python -m ingestion.cli ingest --trigger-job          # ... then run the Databricks Job (Phase 4.5)
```
Add `--local-only` to skip the Databricks upload.

**Needs** in `.env`: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `EIA_API_KEY` (and optionally `GRIDWISE_CATALOG`, `DATABRICKS_JOB_ID`).

[gridstatus]: https://github.com/gridstatus/gridstatus
