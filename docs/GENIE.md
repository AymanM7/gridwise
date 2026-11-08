# Genie space: "GridWise - Texas Grid" (Phase 4.4)

Natural-language questions over ERCOT grid history and GridWise forecasts, answered by Databricks AI/BI Genie
on the SQL warehouse. The space is **created by code** (the Genie REST API works on Free Edition):

```powershell
python -m tools.job comments   # table + column COMMENTs on the gold tables (via the SQL warehouse)
python -m tools.job genie      # create-or-update the space; saves GENIE_SPACE_ID to .env
```

Open it at `<DATABRICKS_HOST>/genie/rooms/<GENIE_SPACE_ID>` (or sidebar -> **Genie** -> *GridWise - Texas Grid*).
The definition (tables, instructions, example SQL, benchmarks) lives in `tools/job.py`
(`GENIE_TABLES`, `GENIE_INSTRUCTIONS`, `GENIE_QA`); re-running `genie` overwrites the space from code.

## Tables

| Table | Grain | Used for |
|---|---|---|
| `grid.gold.strain_hourly` | 1 row / UTC hour, 2023 -> now (+48 placeholder rows) | net load, strain index, level |
| `grid.gold.spike_events` | 1 row / priced hour | RT price, `is_spike` (> $100/MWh) |
| `grid.gold.strain_reference` | month x percentile | how strain is computed |
| `grid.gold.forecasts` | 48 rows per `run_ts` | current / past 48 h forecasts |
| `grid.gold.forecast_drivers` | 3 rows per forecast hour | "Why Red?" SHAP drivers |
| `grid.gold.report_card` | 1 row per day x source | forecast accuracy |
| `grid.silver.grid_hourly` | 1 row / UTC hour | demand, wind, solar actuals |

### Comments (metadata Genie reads)
Every table above in `gold` has a table COMMENT, and the key columns have column COMMENTs (77 statements,
`TABLE_COMMENTS` / `COLUMN_COMMENTS` in `tools/job.py`). `03_gold` rebuilds `features`, `strain_hourly`,
`strain_reference` and `spike_events` with `CREATE OR REPLACE`, which **drops comments**, so the hourly Job ends
with a generated `genie_comments` task (runs even if an upstream task fails) that re-applies them.

## Instructions (text given to Genie)

```
GridWise forecasts strain on the ERCOT (Texas) power grid.
* Always answer in Texas local time: use ts_local (America/Chicago). For silver.grid_hourly convert with
  from_utc_timestamp(ts_utc, 'America/Chicago').
* IMPORTANT: ts_local values are ALREADY Texas wall-clock time even though results display them with a
  trailing "Z". Never convert ts_local again; report it as-is (e.g. ts_local 2025-07-30T20:00:00Z = 8 PM Texas
  time on July 30). Only ts_utc / run_ts / target_ts are UTC.
* For history, filter is_forecast_row = false (the last 48 rows are future placeholders with no actuals).
* Net load = demand - wind - solar (MW). Strain index (0-100) = percentile of net load within the same calendar
  month; level green <60, yellow 60-85, red >85. "Most strained" = highest strain_index, ties broken by net_load_mw.
* A price spike = hourly average real-time price (price_usd_mwh, HB_HUBAVG hub) above $100/MWh (is_spike = 1).
* Summer = June-August; winter = December-February. "Last <month>" = the most recent completed occurrence.
* gold.forecasts holds one 48-hour batch per run_ts; the current forecast is
  WHERE run_ts = (SELECT max(run_ts) FROM gold.forecasts). spike_prob is 0-1.
* report_card mape / demand_mape / band_coverage are fractions (0.032 = 3.2%).
* Round MW to whole numbers and prices to whole dollars.
```

The `ts_local` rule matters: without it Genie read `2025-07-30T20:00Z` as UTC and said "3 PM CDT".

## The 5 demo questions (from PROJECT_SCOPE.md section 10)

Each one is loaded into the space as a sample question, an example SQL, and a benchmark. Expected answers were
checked with our own SQL (`python -m tools.sql`) and then asked to Genie through the API on **2026-11-07**.
Genie produced the same SQL and numbers for all 5. History numbers shift slightly as new hours land.

| # | Question | Expected answer (verified 2026-11-07) |
|---|---|---|
| 1 | What was the most strained hour of summer 2025? | **Jul 30 2025, 8 PM Texas time**: net load 67,697 MW, strain 99.8 (red). Runners-up: Jul 31 8 PM (67,473 MW), Jul 29 8 PM (65,890 MW). |
| 2 | How does wind output change on peak-demand days? | Barely. On the top-10% peak-demand days (140 days, avg peak 84,900 MW) average wind is **13,057 MW** vs **12,974 MW** on the other 1,267 days. Wind doesn't rise to meet peak demand, so the gap falls on gas and solar. |
| 3 | How many hours had real-time prices above $100/MWh last August? | **16 hours** in August 2026; highest hourly average price **$535/MWh**. |
| 4 | What's the average net load at 6pm in July vs. January? | **July 50,042 MW** vs **January 41,437 MW** (124 six-pm hours each, 2023-2026); July is about 21% higher. |
| 5 | Which weekday has the highest average strain index? | **Thursday 52.4**, then Wednesday 52.3, Monday 52.1, Tuesday 51.7, Friday 50.5; weekends lowest (Saturday 45.9, Sunday 45.1). |

<details><summary>Verification SQL</summary>

```sql
-- 1
SELECT ts_local, round(net_load_mw,0) net_load_mw, round(strain_index,1) strain_index, level
FROM grid.gold.strain_hourly
WHERE NOT is_forecast_row AND ts_local >= '2025-06-01' AND ts_local < '2025-09-01'
ORDER BY strain_index DESC, net_load_mw DESC LIMIT 3;
-- 2
WITH d AS (SELECT to_date(from_utc_timestamp(ts_utc,'America/Chicago')) day, max(demand_mw) peak_demand_mw,
                  avg(wind_mw) avg_wind_mw
           FROM grid.silver.grid_hourly
           WHERE NOT is_forecast_row AND demand_mw IS NOT NULL AND wind_mw IS NOT NULL GROUP BY 1),
     r AS (SELECT *, percent_rank() OVER (ORDER BY peak_demand_mw) pr FROM d)
SELECT CASE WHEN pr >= 0.9 THEN 'peak-demand days (top 10%)' ELSE 'all other days' END day_type,
       count(*) days, round(avg(peak_demand_mw),0) avg_peak_demand_mw, round(avg(avg_wind_mw),0) avg_wind_mw
FROM r GROUP BY 1;
-- 3
SELECT count(*) hours_above_100, round(max(price_usd_mwh),0) max_hourly_price
FROM grid.gold.spike_events
WHERE price_usd_mwh > 100 AND ts_local >= '2026-08-01' AND ts_local < '2026-09-01';
-- 4
SELECT CASE month(ts_local) WHEN 1 THEN 'January' ELSE 'July' END month_name, count(*) hours,
       round(avg(net_load_mw),0) avg_net_load_mw_6pm
FROM grid.gold.strain_hourly
WHERE NOT is_forecast_row AND hour(ts_local) = 18 AND month(ts_local) IN (1,7) GROUP BY 1;
-- 5
SELECT date_format(ts_local,'EEEE') weekday, round(avg(strain_index),1) avg_strain_index, count(*) hours
FROM grid.gold.strain_hourly WHERE NOT is_forecast_row GROUP BY 1 ORDER BY avg_strain_index DESC;
```
</details>

## Manual fallback (click by click)

Use this only if the API path stops working (for example, a new workspace without API access).

1. Run `python -m tools.job comments` (or let one Job run finish) so the tables carry descriptions.
2. Workspace sidebar -> **Genie** -> **+ New**.
3. **Choose data sources** -> catalog `grid` -> add the 7 tables listed above -> **Create**.
4. Top right **Settings**: title `GridWise - Texas Grid`; description *"Ask questions about ERCOT grid history
   (net load, strain index, price spikes, wind/solar) and GridWise's 48h forecasts and accuracy report card."*;
   SQL warehouse = the one in `.env` `DATABRICKS_WAREHOUSE_ID` (Serverless Starter Warehouse) -> **Save**.
5. **Instructions** -> **General instructions** -> paste the instructions block above -> **Save**.
6. **Instructions** -> **SQL queries** -> **+ Add** for each of the 5 questions: paste the question as the title and
   the matching verification SQL above (use the `LIMIT 1` form for #1) -> **Save**.
7. **Settings** -> **Sample questions** -> add the 5 questions so they appear as chips.
8. Optional: **Benchmarks** -> **+ Add benchmark** with the same question + SQL pairs -> **Run benchmarks**.
9. Ask each question in a new chat and compare with the table above. **Share** -> *Can run* for teammates/judges.

## Demo tip
Script step 7: open the space, click the chip "What was the most strained hour of summer 2025?". It answers
in about 10 s with "8 PM on July 30, 2025, 67,697 MW, strain 99.8 (red)". Click **Show code** to show the SQL.
