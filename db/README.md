# 🗄️ db/: Serving Database (Tiger Data)

> **Status:** planned for **Phase 5.1–5.2**. Not built yet.

The website never queries Databricks directly. Each hour the pipeline copies the latest Gold results into **Tiger Data** (TimescaleDB on Postgres), which serves the dashboard in milliseconds.

**Planned contents**

| File | Purpose |
|---|---|
| `schema.sql` | Hypertables: `forecasts`, `actuals`, `forecast_drivers`, `daily_advice`, `shift_scenarios`, `report_card` |
| `aggregates.sql` | Continuous aggregates for hourly/daily rollups (instant history charts) |
| `sync.py` (or a Databricks task) | Upserts Gold → Tiger each hour |

Databricks can reach Tiger directly (checked by `pipeline/00_connectivity_check`), so the sync can run inside the hourly Databricks Job.

**Needs** in `.env`: `TIGER_DATABASE_URL`.
