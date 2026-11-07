# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Gold (Phase 2.4-2.5)
# MAGIC Builds the model-ready and dashboard layer per `docs/PHASE2_CONTRACT.md` §2:
# MAGIC * `gold.features` – 1 row / UTC hour (same grain as `silver.grid_hourly`, incl. the 48 forecast rows); targets, calendar, weather-at-t,
# MAGIC   AR lags **≥ 48 h** (time-based self-joins), rolling windows ending at t−48, `diag_` lags (banned for models)
# MAGIC * `gold.strain_hourly` – strain index 0–100 = percent rank of net load within the local calendar month; green / yellow / red
# MAGIC * `gold.strain_reference` – percentile breakpoints per month (Phase 3 maps forecast P50 → strain)
# MAGIC * `gold.spike_events` – every priced hour, `is_spike` = hourly avg RT price > $100/MWh
# MAGIC * `gold.dq_checks` – acceptance checks (§4 Gold)
# MAGIC
# MAGIC **Leakage design ("lag-48 floor")**: one direct model serves h = 1..48 from `anchor_ts`; a target hour t only sees history at ≤ t−48
# MAGIC (always ≤ anchor) plus calendar and weather at t.

# COMMAND ----------

# MAGIC %pip install holidays

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "grid")
catalog = dbutils.widgets.get("catalog")
spark.conf.set("spark.sql.session.timeZone", "UTC")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.gold")

import json
from datetime import datetime, timezone
import holidays
from pyspark.sql import functions as F

S = f"{catalog}.silver"
G = f"{catalog}.gold"
SPIKE_USD = 100.0
checks = {}


def chk(name, value, ok):
    checks[name] = {"value": value, "pass": bool(ok)}
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {value}")

# COMMAND ----------

# MAGIC %md ## 1. Calendar helpers – US holidays (local date)

# COMMAND ----------

us_hol = holidays.US(years=range(2022, 2029))
hol_df = spark.createDataFrame([(d, n) for d, n in sorted(us_hol.items())], "hol_date date, hol_name string")
hol_df.createOrReplaceTempView("us_holidays")
display(hol_df.where("year(hol_date) between 2023 and 2026"))

# COMMAND ----------

# MAGIC %md ## 2. `gold.features`
# MAGIC Lags are computed **by time** (`LEFT JOIN ... ON l.ts_utc = t.ts_utc - INTERVAL n HOURS`), never by row offset.
# MAGIC Rolling windows are time-RANGE windows on epoch seconds ending at t−48 h; they ignore nulls and need ≥ 50 % non-null inputs.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TEMP VIEW base AS
SELECT ts_utc, net_load_mw AS nl, demand_mw AS dem, wind_mw AS wnd, solar_mw AS sol, price_usd_mwh AS px,
       CASE WHEN price_usd_mwh IS NULL THEN NULL WHEN price_usd_mwh > {SPIKE_USD} THEN 1 ELSE 0 END AS spk
FROM {S}.grid_hourly
""")

# Rolling windows: rows whose time is within [t-48-(N-1)h, t-48h]
spark.sql("""
CREATE OR REPLACE TEMP VIEW rolls AS
SELECT ts_utc,
  CASE WHEN nl_c24  >= 12 THEN nl_s24  / nl_c24  END AS nl_roll24_mean_l48,
  CASE WHEN nl_c168 >= 84 THEN nl_s168 / nl_c168 END AS nl_roll168_mean_l48,
  CASE WHEN nl_c168 >= 84 THEN nl_m168 END            AS nl_roll168_max_l48,
  CASE WHEN px_c168 >= 84 THEN px_s168 / px_c168 END AS price_roll168_mean_l48,
  CASE WHEN px_c168 >= 84 THEN px_m168 END            AS price_roll168_max_l48,
  CASE WHEN px_c168 >= 84 THEN sp_s168 END            AS spike_count_168_l48
FROM (
  SELECT ts_utc,
    sum(nl)   OVER w24  AS nl_s24,  count(nl) OVER w24  AS nl_c24,
    sum(nl)   OVER w168 AS nl_s168, count(nl) OVER w168 AS nl_c168, max(nl) OVER w168 AS nl_m168,
    sum(px)   OVER w168 AS px_s168, count(px) OVER w168 AS px_c168, max(px) OVER w168 AS px_m168,
    sum(spk)  OVER w168 AS sp_s168
  FROM (SELECT *, unix_timestamp(ts_utc) AS es FROM base)
  WINDOW w24  AS (ORDER BY es RANGE BETWEEN 255600 PRECEDING AND 172800 PRECEDING),   -- (48+23)h .. 48h
         w168 AS (ORDER BY es RANGE BETWEEN 774000 PRECEDING AND 172800 PRECEDING)    -- (48+167)h .. 48h
)
""")

# Weather 24h trailing mean (weather is known-ahead, window t-23..t)
spark.sql(f"""
CREATE OR REPLACE TEMP VIEW wx_roll AS
SELECT ts_utc,
  CASE WHEN count(temp_f) OVER w >= 12 THEN avg(temp_f) OVER w END AS temp_f_roll24_mean
FROM (SELECT ts_utc, temp_f, unix_timestamp(ts_utc) es FROM {S}.grid_hourly)
WINDOW w AS (ORDER BY es RANGE BETWEEN 82800 PRECEDING AND CURRENT ROW)
""")

feat = spark.sql(f"""
SELECT
  g.ts_utc, g.ts_local, g.is_forecast_row, g.anchor_ts,
  -- targets
  g.net_load_mw AS y_net_load_mw,
  g.price_usd_mwh AS y_price_usd_mwh,
  CASE WHEN g.price_usd_mwh IS NULL THEN NULL WHEN g.price_usd_mwh > {SPIKE_USD} THEN 1 ELSE 0 END AS y_is_spike,
  -- calendar (local wall clock)
  hour(g.ts_local) AS hour,
  ((dayofweek(g.ts_local) + 5) % 7) + 1 AS dow,
  month(g.ts_local) AS month,
  dayofyear(g.ts_local) AS doy,
  CASE WHEN dayofweek(g.ts_local) IN (1, 7) THEN 1 ELSE 0 END AS is_weekend,
  CASE WHEN h.hol_date IS NOT NULL THEN 1 ELSE 0 END AS is_holiday,
  sin(2 * pi() * hour(g.ts_local) / 24.0) AS hour_sin,
  cos(2 * pi() * hour(g.ts_local) / 24.0) AS hour_cos,
  sin(2 * pi() * dayofyear(g.ts_local) / 365.25) AS doy_sin,
  cos(2 * pi() * dayofyear(g.ts_local) / 365.25) AS doy_cos,
  -- weather at t
  g.temp_f, g.heat_index_f, g.rh_pct, g.wind_mph, g.cloud_pct, g.ghi_wm2,
  g.temp_f_hou, g.temp_f_dfw, g.temp_f_aus, g.temp_f_sat,
  greatest(g.temp_f - 65, 0D) AS cdd,
  greatest(65 - g.temp_f, 0D) AS hdd,
  wr.temp_f_roll24_mean,
  -- AR lags >= 48h (time-based joins)
  l48.nl  AS nl_lag_48h,  l72.nl AS nl_lag_72h, l168.nl AS nl_lag_168h, l336.nl AS nl_lag_336h,
  l48.dem AS demand_lag_48h, l168.dem AS demand_lag_168h,
  l48.wnd AS wind_lag_48h,   l168.wnd AS wind_lag_168h,
  l48.sol AS solar_lag_48h,  l168.sol AS solar_lag_168h,
  l48.px  AS price_lag_48h,  l168.px  AS price_lag_168h,
  -- AR rolling ending at t-48
  r.nl_roll24_mean_l48, r.nl_roll168_mean_l48, r.nl_roll168_max_l48,
  r.price_roll168_mean_l48, r.price_roll168_max_l48, CAST(r.spike_count_168_l48 AS DOUBLE) AS spike_count_168_l48,
  -- diagnostics (BANNED for models)
  l1.nl AS diag_nl_lag_1h, l24.nl AS diag_nl_lag_24h,
  -- live ERCOT (BANNED for training; inference display only)
  g.wind_forecast_mw, g.solar_forecast_mw,
  current_timestamp() AS _built_at
FROM {S}.grid_hourly g
LEFT JOIN us_holidays h ON h.hol_date = to_date(g.ts_local)
LEFT JOIN wx_roll wr ON wr.ts_utc = g.ts_utc
LEFT JOIN rolls r    ON r.ts_utc  = g.ts_utc
LEFT JOIN base l1   ON l1.ts_utc   = g.ts_utc - INTERVAL 1 HOURS
LEFT JOIN base l24  ON l24.ts_utc  = g.ts_utc - INTERVAL 24 HOURS
LEFT JOIN base l48  ON l48.ts_utc  = g.ts_utc - INTERVAL 48 HOURS
LEFT JOIN base l72  ON l72.ts_utc  = g.ts_utc - INTERVAL 72 HOURS
LEFT JOIN base l168 ON l168.ts_utc = g.ts_utc - INTERVAL 168 HOURS
LEFT JOIN base l336 ON l336.ts_utc = g.ts_utc - INTERVAL 336 HOURS
""")
feat.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{G}.features")
print("gold.features rows:", spark.table(f"{G}.features").count())

# COMMAND ----------

# MAGIC %md ## 3. `gold.strain_reference` and `gold.strain_hourly`
# MAGIC Strain = 100 × percent rank of actual net load within the same **local calendar month** across all history.
# MAGIC Levels: green < 60, yellow 60–85, red > 85. (Phase 3 adds the +15 spike boost in `gold.forecasts`.)

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {G}.strain_reference AS
SELECT month, CAST(pos AS INT) AS pct, net_load_mw
FROM (
  SELECT month(ts_local) AS month,
         percentile(net_load_mw, array({", ".join(f"{p/100:.2f}" for p in range(101))})) AS ps
  FROM {S}.grid_hourly
  WHERE NOT is_forecast_row AND net_load_mw IS NOT NULL
  GROUP BY month(ts_local)
) LATERAL VIEW posexplode(ps) e AS pos, net_load_mw
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {G}.strain_hourly AS
SELECT ts_utc, ts_local, month, net_load_mw, strain_index,
       CASE WHEN strain_index > 85 THEN 'red' WHEN strain_index >= 60 THEN 'yellow' ELSE 'green' END AS level,
       is_forecast_row
FROM (
  SELECT ts_utc, ts_local, month(ts_local) AS month, net_load_mw, is_forecast_row,
         100.0 * percent_rank() OVER (PARTITION BY month(ts_local) ORDER BY net_load_mw) AS strain_index
  FROM {S}.grid_hourly
  WHERE NOT is_forecast_row AND net_load_mw IS NOT NULL
)
""")

# COMMAND ----------

# MAGIC %md ## 4. `gold.spike_events`

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {G}.spike_events AS
SELECT ts_utc, ts_local, price_usd_mwh, price_max_usd_mwh,
       CASE WHEN price_usd_mwh > {SPIKE_USD} THEN 1 ELSE 0 END AS is_spike
FROM {S}.grid_hourly
WHERE price_usd_mwh IS NOT NULL
""")

# COMMAND ----------

# MAGIC %md ## 5. Displays – strain and spikes

# COMMAND ----------

# Strain level distribution
display(spark.sql(f"""
SELECT level, count(*) AS hours, round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct_hours,
       round(min(strain_index), 1) AS min_strain, round(max(strain_index), 1) AS max_strain
FROM {G}.strain_hourly GROUP BY level ORDER BY min_strain"""))

# COMMAND ----------

# Top 10 most strained hours (highest net load relative to its month; ties broken by absolute net load)
display(spark.sql(f"""
SELECT s.ts_utc, s.ts_local, round(s.net_load_mw) AS net_load_mw, round(s.strain_index, 3) AS strain_index, s.level,
       g.temp_f, g.price_usd_mwh
FROM {G}.strain_hourly s JOIN {S}.grid_hourly g USING (ts_utc)
ORDER BY s.strain_index DESC, s.net_load_mw DESC LIMIT 10"""))

# COMMAND ----------

# Spike counts per year
display(spark.sql(f"""
SELECT year(ts_local) AS year, count(*) AS priced_hours, sum(is_spike) AS spike_hours,
       round(100.0 * avg(is_spike), 2) AS spike_rate_pct, round(max(price_usd_mwh), 0) AS max_hourly_price
FROM {G}.spike_events GROUP BY 1 ORDER BY 1"""))

# COMMAND ----------

# Monthly spike rate
display(spark.sql(f"""
SELECT date_format(ts_local, 'yyyy-MM') AS month, count(*) AS priced_hours, sum(is_spike) AS spike_hours,
       round(100.0 * avg(is_spike), 2) AS spike_rate_pct
FROM {G}.spike_events GROUP BY 1 ORDER BY 1"""))

# COMMAND ----------

# MAGIC %md ## 6. Acceptance checks (contract §4 Gold)

# COMMAND ----------

FEATURES_A = [
    "hour", "dow", "month", "doy", "is_weekend", "is_holiday", "hour_sin", "hour_cos", "doy_sin", "doy_cos",
    "temp_f", "heat_index_f", "rh_pct", "wind_mph", "cloud_pct", "ghi_wm2",
    "temp_f_hou", "temp_f_dfw", "temp_f_aus", "temp_f_sat", "cdd", "hdd", "temp_f_roll24_mean",
    "nl_lag_48h", "nl_lag_72h", "nl_lag_168h", "nl_lag_336h", "demand_lag_48h", "demand_lag_168h",
    "wind_lag_48h", "wind_lag_168h", "solar_lag_48h", "solar_lag_168h",
    "nl_roll24_mean_l48", "nl_roll168_mean_l48", "nl_roll168_max_l48",
]
F_ = f"{G}.features"

# grain
r = spark.sql(f"""SELECT (SELECT count(*) FROM {F_}) n, (SELECT count(DISTINCT ts_utc) FROM {F_}) nd,
                         (SELECT count(*) FROM {S}.grid_hourly) ns""").first()
chk("features_grain", {"rows": r.n, "distinct_ts": r.nd, "silver_rows": r.ns}, r.n == r.nd == r.ns)

# leakage guard 1: nl_lag_48h equals net_load at t-48 for EVERY row (exact independent join)
r = spark.sql(f"""
SELECT count(*) n,
       sum(CASE WHEN NOT (f.nl_lag_48h <=> s.net_load_mw) THEN 1 ELSE 0 END) mismatches
FROM {F_} f LEFT JOIN {S}.grid_hourly s ON s.ts_utc = f.ts_utc - INTERVAL 48 HOURS""").first()
chk("leakage_nl_lag_48h_exact", {"rows": r.n, "mismatches": r.mismatches}, r.mismatches == 0)

# leakage guard 2: nl_roll24_mean_l48 recomputed from rows <= t-48 only, on a sample of 500 rows
r = spark.sql(f"""
WITH samp AS (SELECT ts_utc, nl_roll24_mean_l48 v FROM {F_} WHERE nl_roll24_mean_l48 IS NOT NULL ORDER BY hash(ts_utc) LIMIT 500),
rec AS (
  SELECT x.ts_utc, avg(s.net_load_mw) re, max(s.ts_utc) max_used, x.v
  FROM samp x JOIN {S}.grid_hourly s
    ON s.ts_utc BETWEEN x.ts_utc - INTERVAL 71 HOURS AND x.ts_utc - INTERVAL 48 HOURS
  GROUP BY x.ts_utc, x.v)
SELECT count(*) n, sum(CASE WHEN abs(re - v) > 1e-6 THEN 1 ELSE 0 END) mism,
       sum(CASE WHEN max_used > ts_utc - INTERVAL 48 HOURS THEN 1 ELSE 0 END) future
FROM rec""").first()
chk("leakage_roll24_l48_sample", {"sampled": r.n, "mismatches": r.mism, "uses_after_t_minus_48": r.future},
    r.n > 0 and r.mism == 0 and r.future == 0)

# forecast rows
r = spark.sql(f"""
SELECT count(*) n, count(nl_lag_48h) lag_nn,
       sum(CASE WHEN hour IS NOT NULL AND dow IS NOT NULL AND month IS NOT NULL AND doy IS NOT NULL
                 AND is_holiday IS NOT NULL AND hour_sin IS NOT NULL THEN 1 ELSE 0 END) cal_nn,
       count(temp_f) temp_nn
FROM {F_} WHERE is_forecast_row""").first()
chk("forecast_rows", {"rows": r.n, "nl_lag_48h_nonnull": r.lag_nn, "calendar_nonnull": r.cal_nn, "temp_nonnull": r.temp_nn},
    r.n == 48 and r.lag_nn >= 46 and r.cal_nn == 48)

# forecast rows must carry price history features for Model B (PM round-1 requirement: >= 46/48 each)
r = spark.sql(f"""
SELECT count(*) n, count(price_lag_48h) p48, count(price_roll168_mean_l48) pr168,
       count(spike_count_168_l48) sc168, count(price_lag_168h) p168
FROM {F_} WHERE is_forecast_row""").first()
chk("forecast_rows_price_features",
    {"rows": r.n, "price_lag_48h": r.p48, "price_roll168_mean_l48": r.pr168,
     "spike_count_168_l48": r.sc168, "price_lag_168h_info": r.p168},
    r.n == 48 and r.p48 >= 46 and r.pr168 >= 46 and r.sc168 >= 46)

# feature null rates on actual rows from 2023-01-15
exprs = ", ".join(f"avg(CASE WHEN {c} IS NULL THEN 1.0 ELSE 0 END) AS {c}" for c in FEATURES_A)
nr = spark.sql(f"SELECT {exprs} FROM {F_} WHERE NOT is_forecast_row AND ts_utc >= '2023-01-15'").first().asDict()
nr = {k: round(float(v) * 100, 3) for k, v in nr.items()}
worst = max(nr, key=nr.get)
chk("feature_null_pct_max", {"worst_col": worst, "pct": nr[worst], "over_3pct": [k for k, v in nr.items() if v >= 3]},
    nr[worst] < 3)

# strain range + per-month red/yellow shares
r = spark.sql(f"SELECT min(strain_index) mn, max(strain_index) mx, count(*) n FROM {G}.strain_hourly").first()
chk("strain_range", {"min": r.mn, "max": r.mx, "rows": r.n}, r.mn >= 0 and r.mx <= 100)
m = spark.sql(f"""
SELECT month, 100 * avg(CASE WHEN level='red' THEN 1.0 ELSE 0 END) red,
              100 * avg(CASE WHEN level='yellow' THEN 1.0 ELSE 0 END) yellow
FROM {G}.strain_hourly GROUP BY month ORDER BY month""").collect()
red = {x.month: round(float(x.red), 2) for x in m}
yel = {x.month: round(float(x.yellow), 2) for x in m}
chk("strain_red_15pct_by_month", red, len(m) == 12 and all(abs(v - 15) <= 3 for v in red.values()))
chk("strain_yellow_25pct_by_month", yel, len(m) == 12 and all(abs(v - 25) <= 3 for v in yel.values()))
r = spark.sql(f"SELECT count(*) n, count(DISTINCT month) m, min(pct) a, max(pct) b FROM {G}.strain_reference").first()
chk("strain_reference_shape", {"rows": r.n, "months": r.m, "pct_min": r.a, "pct_max": r.b}, r.n == 12 * 101 and r.m == 12)

# spikes
r = spark.sql(f"SELECT avg(is_spike) a, count(*) n, sum(is_spike) s FROM {G}.spike_events").first()
chk("spike_rate_overall_pct", {"pct": round(100 * float(r.a), 3), "priced_hours": r.n, "spike_hours": r.s}, 0.01 <= r.a <= 0.06)
EXPECTED = {2023: 3.9, 2024: 1.8, 2025: 2.5, 2026: 2.4}
yr = {x.y: round(100 * float(x.a), 2) for x in spark.sql(f"SELECT year(ts_utc) y, avg(is_spike) a FROM {G}.spike_events GROUP BY 1").collect()}
chk("spike_rate_by_year_pct", {"measured": yr, "expected": EXPECTED},
    all(y in yr and abs(yr[y] - e) <= 0.3 for y, e in EXPECTED.items()))
r = spark.sql(f"""SELECT (SELECT count(*) FROM {G}.spike_events) se,
                         (SELECT count(price_usd_mwh) FROM {S}.grid_hourly) sp""").first()
chk("spike_events_all_priced_hours", {"spike_events": r.se, "silver_priced_hours": r.sp}, r.se == r.sp)

# holidays
hd = {str(x.d): x.h for x in spark.sql(f"""
SELECT to_date(ts_local) d, min(is_holiday) h FROM {F_}
WHERE to_date(ts_local) IN (DATE'2024-07-04', DATE'2025-12-25', DATE'2024-07-05') GROUP BY 1""").collect()}
chk("holidays", hd, hd.get("2024-07-04") == 1 and hd.get("2025-12-25") == 1 and hd.get("2024-07-05") == 0)

# banned columns are flagged by name only (sanity: diag columns exist, distinct from model lags)
cols = set(spark.table(F_).columns)
chk("diag_and_live_columns_present", sorted(c for c in cols if c.startswith("diag_") or c.endswith("_forecast_mw")),
    {"diag_nl_lag_1h", "diag_nl_lag_24h", "wind_forecast_mw", "solar_forecast_mw"} <= cols)

# COMMAND ----------

all_pass = all(v["pass"] for v in checks.values())
built = datetime.now(timezone.utc).isoformat()
dq_rows = [(k, json.dumps(v["value"], default=str), v["pass"], built) for k, v in checks.items()]
dq_rows.append(("all_pass", str(all_pass), all_pass, built))
spark.createDataFrame(dq_rows, "check string, value string, pass boolean, built_at string") \
     .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{G}.dq_checks")
display(spark.table(f"{G}.dq_checks"))

# COMMAND ----------

summary = dict(checks)
summary["feature_null_pct"] = nr
summary["anchor_ts"] = str(spark.sql(f"SELECT max(anchor_ts) FROM {F_}").first()[0])
summary["all_pass"] = all_pass
dbutils.notebook.exit(json.dumps(summary, default=str))
