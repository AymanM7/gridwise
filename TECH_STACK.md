# GridWise Tech Stack

See [ARCHITECTURE.md](ARCHITECTURE.md) for how these pieces connect and [.env.example](.env.example) for the keys each one needs.

## Summary

| Layer | Technology | Role | Track |
|---|---|---|---|
| Data sources | **gridstatus** (Python) | Live ERCOT load, RT prices, wind/solar actuals + 7-day forecasts; yearly price archive | — |
| | **EIA-930 API** (free key) | Multi-year hourly ERCOT demand, wind, solar (ERCOT's own reports only keep a few days) | — |
| | **Open-Meteo** API | Historical and forecast weather (no key) | — |
| Ingestion worker | **Python `worker/`** + **GitHub Actions** cron | Fetches sources outside Databricks, uploads parquet into a UC Volume, triggers the Job | — |
| Lakehouse | **Databricks** (Free Edition) | Notebooks, Jobs, Auto Loader, serverless compute | Databricks |
| Storage | **Delta Lake + Unity Catalog** | Bronze / Silver / Gold tables, governance | Databricks |
| ML | **LightGBM**, **SHAP**, scikit-learn | Net load forecast, spike classifier, explanations | Databricks |
| MLOps | **MLflow** + UC Model Registry | Experiment tracking, model versioning | Databricks |
| GenAI | **Gemini** via **Mosaic AI Gateway** + `ai_query()` | Daily advice, "Why Red?" sentences | Gemini + Databricks |
| | **Gemini API** (`google-genai`) | Live chat box in the app | Gemini |
| NL analytics | **Databricks Genie** | Natural-language Q&A over Gold tables | Databricks |
| Serving DB | **Tiger Data** (TimescaleDB / Postgres) | Hypertables plus continuous aggregates for fast charts | Tiger Data |
| API | **FastAPI** + `asyncpg` / `psycopg` | `/forecast`, `/advice`, `/history`, `/simulate`, `/chat` | — |
| Frontend | **Next.js** (React) + **Tailwind** + **Recharts** | Dashboard, Ripple simulator, chat | — |
| Hosting | **Vultr** (Cloud Compute VM, Docker) | API and frontend | Vultr |
| Domain | **GoDaddy Registry** (e.g. `gridwise.tech`) | Public URL | GoDaddy |
| Stretch | **Solana** (devnet) | Off-peak shift reward tokens | Solana |

## Python packages (worker, see `worker/requirements.txt`)

```
gridstatus
pandas
pyarrow
requests
python-dotenv
databricks-sdk       # upload to UC Volume, trigger the Job, (later) read Gold via SQL
```

## Python packages (Databricks notebooks, installed with %pip from PyPI, which Free Edition allows)

```
lightgbm
shap
holidays
mlflow               # preinstalled
scikit-learn         # preinstalled
```

## Python packages (API)

```
fastapi
uvicorn[standard]
asyncpg
pydantic-settings
google-genai
httpx
```

## Frontend packages

```
next react react-dom
tailwindcss
recharts
@tanstack/react-query
```

## Why each choice

- **gridstatus over the raw ERCOT API:** one call returns clean DataFrames and handles ERCOT's report formats.
- **Open-Meteo:** free with no key, and it has both a historical archive and a forecast endpoint with the same schema, so training and inference features match.
- **LightGBM:** fast on tabular lag features, native quantile objective for confidence bands, and SHAP's TreeExplainer runs exactly and quickly on it.
- **AI Gateway + `ai_query()`:** Gemini runs *inside* the SQL pipeline, so advice generation is a scheduled, governed Databricks step instead of an app-side call.
- **Tiger Data:** this is time-series data. Continuous aggregates precompute hourly and daily rollups so the dashboard never scans raw rows.
- **FastAPI:** async, auto-generated OpenAPI docs, quick to write.
- **Vultr + Docker Compose:** one VM runs both API and frontend, with Caddy for automatic HTTPS on the GoDaddy domain.

## Known constraints / fallbacks

| Risk | Fallback |
|---|---|
| **Free Edition blocks outbound internet** except a short trusted list (PyPI works) | The `worker/` fetches ERCOT/EIA/Open-Meteo outside Databricks and uploads parquet *into* a UC Volume; Auto Loader loads Bronze. `notebooks/00_connectivity_check` shows exactly what's blocked. |
| Gemini API / AI Gateway external models unreachable from Free Edition | Worker `publish` step reads `gold.forecasts` via the SQL warehouse, calls Gemini, writes `gold.daily_advice` back to Databricks |
| Tiger Data unreachable from Free Edition | Worker `publish` step syncs Gold → Tiger Data |
| Free Edition limits (1 SQL warehouse 2X-Small, 5 concurrent job tasks, daily compute quota) | Keep the Job to ≤5 parallel tasks; if the quota runs out, run every 3 hours; backfill runs once |
| ERCOT keeps only a few days of wind/solar reports | Use EIA-930 for history, ERCOT for live + forecasts |
| gridstatus endpoint changes or rate limits | Cache Bronze; ingest only the incremental window on each run |
| Tiger Data setup time | API reads Databricks SQL Warehouse directly via `databricks-sql-connector` |
| Vultr setup time | Frontend on Vercel, API on Vultr (or both on Vercel / Render) |
