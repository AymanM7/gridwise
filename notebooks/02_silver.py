# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver (Phase 2.1-2.3, DQ 2.6)
# MAGIC Builds the cleaned hourly layer per `docs/PHASE2_CONTRACT.md` §1:
# MAGIC * `silver.weather_hourly` – 1 row / UTC hour, 4 cities + population-weighted means, archive > forecast, ≤6 h gaps interpolated
# MAGIC * `silver.grid_hourly` – 1 row / UTC hour, 2023-01-01 → anchor+48h, ERCOT live > EIA, prices, ERCOT wind/solar forecasts, weather
# MAGIC * `silver.dq_checks` – acceptance checks + missing hours per month
# MAGIC
# MAGIC Rules: dedupe on key keeping latest `_fetched_at_utc`; recover `_rescued_data` numerics (EIA 2023 type mismatch);
# MAGIC grid gaps are **never** filled; forecast rows (`ts_utc > anchor_ts`) carry null actuals.

# COMMAND ----------

dbutils.widgets.text("catalog", "grid")
catalog = dbutils.widgets.get("catalog")
spark.conf.set("spark.sql.session.timeZone", "UTC")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.silver")

import json
from datetime import datetime, timezone
from pyspark.sql import functions as F

B = f"{catalog}.bronze"
S = f"{catalog}.silver"
START = "2023-01-01 00:00:00"
WEIGHTS = {"houston": 7.5, "dfw": 8.1, "austin": 2.5, "san_antonio": 2.7}
CITY_ABBR = {"houston": "hou", "dfw": "dfw", "austin": "aus", "san_antonio": "sat"}


def rescued(df, cols):
    """coalesce(col, cast(get_json_object(_rescued_data,'$.col') as double)) – no-op where nothing was rescued."""
    for c in cols:
        df = df.withColumn(c, F.coalesce(F.col(c).cast("double"),
                                         F.get_json_object(F.col("_rescued_data"), f"$.{c}").cast("double")))
    return df


def dedupe(df, keys):
    """Keep latest _fetched_at_utc (then _ingested_at) per key."""
    return df.selectExpr("*", f"row_number() over (partition by {', '.join(keys)} "
                              "order by _fetched_at_utc desc nulls last, _ingested_at desc nulls last) as _rn") \
             .where("_rn = 1").drop("_rn")

# COMMAND ----------

# MAGIC %md ## 1. Weather → `silver.weather_hourly`

# COMMAND ----------

WX_COLS = ["temperature_2m", "relative_humidity_2m", "apparent_temperature", "wind_speed_10m", "cloud_cover", "shortwave_radiation"]

wx_hist = dedupe(rescued(spark.table(f"{B}.weather_hist"), WX_COLS), ["city", "time_utc"]).withColumn("_prio", F.lit(1)).withColumn("_src", F.lit("archive"))
wx_fc = dedupe(rescued(spark.table(f"{B}.weather_forecast"), WX_COLS), ["city", "time_utc"]).withColumn("_prio", F.lit(2)).withColumn("_src", F.lit("forecast"))
sel = ["city", F.date_trunc("HOUR", "time_utc").alias("ts_utc"), *WX_COLS, "_prio", "_src"]
wx_all = wx_hist.select(*sel).unionByName(wx_fc.select(*sel)).where(F.col("temperature_2m").isNotNull())
wx_all.selectExpr("*", "row_number() over (partition by city, ts_utc order by _prio) rn").where("rn=1").drop("rn", "_prio") \
      .createOrReplaceTempView("wx_city_raw")

wx_max = spark.sql("select max(ts_utc) from wx_city_raw").first()[0]
spark.sql(f"""
  create or replace temp view wx_spine as
  select explode(sequence(timestamp'{START}', timestamp'{wx_max}', interval 1 hour)) ts_utc
""")

# Per city: linear interpolation over gaps of <= 6 missing hours (prev/next known rows at most 7 h apart)
interp_exprs = []
for c in WX_COLS:
    interp_exprs.append(f"""
      case when {c} is not null then {c}
           when timestampdiff(HOUR, prev_ts, next_ts) <= 7 then
             prev_{c} + (next_{c} - prev_{c}) * timestampdiff(HOUR, prev_ts, ts_utc) / timestampdiff(HOUR, prev_ts, next_ts)
      end as {c}""")
win_exprs = []
for c in WX_COLS:
    win_exprs.append(f"last(r.{c}, true) over (partition by c.city order by s.ts_utc rows between unbounded preceding and 1 preceding) prev_{c}")
    win_exprs.append(f"first(r.{c}, true) over (partition by c.city order by s.ts_utc rows between 1 following and unbounded following) next_{c}")

spark.sql(f"""
create or replace temp view wx_city as
with grid as (
  select c.city, s.ts_utc, r._src, {", ".join("r." + c for c in WX_COLS)},
         last(case when r.temperature_2m is not null then s.ts_utc end, true)
           over (partition by c.city order by s.ts_utc rows between unbounded preceding and 1 preceding) prev_ts,
         first(case when r.temperature_2m is not null then s.ts_utc end, true)
           over (partition by c.city order by s.ts_utc rows between 1 following and unbounded following) next_ts,
         {", ".join(win_exprs)}
  from wx_spine s
  cross join (select distinct city from wx_city_raw) c
  left join wx_city_raw r on r.city = c.city and r.ts_utc = s.ts_utc
)
select city, ts_utc,
       case when _src is not null then _src
            when timestampdiff(HOUR, prev_ts, next_ts) <= 7 then 'interp' end as _src,
       {", ".join(interp_exprs)}
from grid
""")

# Wide table: per-city columns + population-weighted means normalised over cities present
def wavg(col):
    num = " + ".join(f"coalesce({col}_{a} * {WEIGHTS[c]}, 0)" for c, a in CITY_ABBR.items())
    den = " + ".join(f"case when {col}_{a} is not null then {WEIGHTS[c]} else 0 end" for c, a in CITY_ABBR.items())
    return f"case when ({den}) > 0 then ({num}) / ({den}) end"

pivot_cols = []
for c, a in CITY_ABBR.items():
    for src, short in [("temperature_2m", "temp_f"), ("relative_humidity_2m", "rh"), ("apparent_temperature", "app"),
                       ("wind_speed_10m", "wind"), ("cloud_cover", "cloud"), ("shortwave_radiation", "ghi")]:
        pivot_cols.append(f"max(case when city = '{c}' then {src} end) as {short}_{a}")

spark.sql(f"""
create or replace temp view wx_wide as
select ts_utc, {", ".join(pivot_cols)},
       case when sum(case when _src = 'interp' then 1 else 0 end) > 0 then 'interp'
            when sum(case when _src = 'forecast' then 1 else 0 end) > 0 then 'forecast'
            when sum(case when _src = 'archive' then 1 else 0 end) > 0 then 'archive' end as wx_source
from wx_city group by ts_utc
""")

hi_T, hi_R = "temp_f", "rh_pct"
rothfusz = (f"(-42.379 + 2.04901523*{hi_T} + 10.14333127*{hi_R} - 0.22475541*{hi_T}*{hi_R} - 0.00683783*{hi_T}*{hi_T}"
            f" - 0.05481717*{hi_R}*{hi_R} + 0.00122874*{hi_T}*{hi_T}*{hi_R} + 0.00085282*{hi_T}*{hi_R}*{hi_R}"
            f" - 0.00000199*{hi_T}*{hi_T}*{hi_R}*{hi_R})")
adj = (f"case when {hi_R} < 13 and {hi_T} between 80 and 112 then -((13-{hi_R})/4)*sqrt((17-abs({hi_T}-95))/17)"
       f" when {hi_R} > 85 and {hi_T} between 80 and 87 then (({hi_R}-85)/10)*((87-{hi_T})/5) else 0 end")
simple = f"0.5*({hi_T} + 61.0 + ({hi_T}-68.0)*1.2 + {hi_R}*0.094)"

weather = spark.sql(f"""
with w as (
  select ts_utc,
         temp_f_hou, temp_f_dfw, temp_f_aus, temp_f_sat,
         rh_hou, rh_dfw, rh_aus, rh_sat,
         {wavg('temp_f')} temp_f, {wavg('rh')} rh_pct, {wavg('app')} apparent_temp_f,
         {wavg('wind')} wind_mph, {wavg('cloud')} cloud_pct, {wavg('ghi')} ghi_wm2, wx_source
  from wx_wide
)
select ts_utc, temp_f_hou, temp_f_dfw, temp_f_aus, temp_f_sat, rh_hou, rh_dfw, rh_aus, rh_sat,
       temp_f, rh_pct, apparent_temp_f, wind_mph, cloud_pct, ghi_wm2,
       case when temp_f is null or rh_pct is null then temp_f
            when temp_f < 80 then temp_f
            when ({simple} + temp_f) / 2 < 80 then {simple}
            else {rothfusz} + {adj} end as heat_index_f,
       wx_source
from w
""")
weather.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{S}.weather_hourly")
spark.sql(f"select wx_source, count(*) n, min(ts_utc), max(ts_utc) from {S}.weather_hourly group by 1 order by 1").show()

# COMMAND ----------

# MAGIC %md ## 2. Grid sources (dedupe + rescue + hourly)

# COMMAND ----------

# EIA-930 hourly (history backbone)
eia = dedupe(rescued(spark.table(f"{B}.eia_hourly"), ["demand_mw", "wind_mw", "solar_mw", "demand_forecast_mw"]), ["interval_start_utc"])
eia.selectExpr("date_trunc('HOUR', interval_start_utc) ts_utc", "demand_mw", "wind_mw", "solar_mw", "demand_forecast_mw") \
   .where(f"interval_start_utc >= timestamp'{START}'").createOrReplaceTempView("eia_h")

# ERCOT live load: time-weighted hourly mean; complete only when covered minutes >= 55
load = dedupe(rescued(spark.table(f"{B}.ercot_load"), ["load_mw"]), ["interval_start_utc"])
load.createOrReplaceTempView("ercot_load_d")
spark.sql("""
create or replace temp view ercot_load_h as
select date_trunc('HOUR', interval_start_utc) ts_utc,
       sum(load_mw * timestampdiff(MINUTE, interval_start_utc, interval_end_utc)) / sum(timestampdiff(MINUTE, interval_start_utc, interval_end_utc)) load_mw,
       least(60, sum(timestampdiff(MINUTE, interval_start_utc, interval_end_utc))) covered_min,
       count(*) n_rows
from ercot_load_d where load_mw is not null
group by 1
""")

# ERCOT wind / solar: actual = latest publish with non-null gen_mw; forecast fields = latest publish covering the hour
REN_COLS = ["gen_mw", "forecast_mw", "forecast_p80_mw", "hsl_mw", "cop_hsl_mw"]
for kind in ["wind", "solar"]:
    d = dedupe(rescued(spark.table(f"{B}.ercot_{kind}"), REN_COLS), ["interval_start_utc", "publish_time_utc"])
    d.createOrReplaceTempView(f"ercot_{kind}_d")
    spark.sql(f"""
    create or replace temp view ercot_{kind}_h as
    with a as (
      select date_trunc('HOUR', interval_start_utc) ts_utc, gen_mw,
             row_number() over (partition by date_trunc('HOUR', interval_start_utc) order by publish_time_utc desc, _fetched_at_utc desc) rn
      from ercot_{kind}_d where gen_mw is not null),
    f as (
      select date_trunc('HOUR', interval_start_utc) ts_utc, forecast_mw, forecast_p80_mw, hsl_mw,
             row_number() over (partition by date_trunc('HOUR', interval_start_utc) order by publish_time_utc desc, _fetched_at_utc desc) rn
      from ercot_{kind}_d)
    select coalesce(a.ts_utc, f.ts_utc) ts_utc, a.gen_mw {kind}_gen_mw,
           f.forecast_mw {kind}_forecast_mw, f.forecast_p80_mw {kind}_forecast_p80_mw, f.hsl_mw {kind}_hsl_mw
    from (select * from a where rn = 1) a full outer join (select * from f where rn = 1) f on a.ts_utc = f.ts_utc
    """)

# ERCOT RT hub-average prices: hourly mean only when all 4 15-min intervals exist
px = dedupe(rescued(spark.table(f"{B}.ercot_prices"), ["price_usd_mwh"]).where("location = 'HB_HUBAVG'"), ["location", "interval_start_utc"])
px.createOrReplaceTempView("prices_d")
spark.sql("""
create or replace temp view prices_h as
select date_trunc('HOUR', interval_start_utc) ts_utc,
       case when count(distinct interval_start_utc) = 4 then avg(price_usd_mwh) end price_usd_mwh,
       max(price_usd_mwh) price_max_usd_mwh,
       count(distinct interval_start_utc) n_intervals,
       max(case when minute(interval_start_utc) = 0 then right(interval_start_local, 6) end) utc_offset_src
from prices_d where price_usd_mwh is not null
group by 1
""")

# Combined actuals (ERCOT live > EIA) on the union of hours, to find anchor_ts
spark.sql("""
create or replace temp view actual_h as
with keys as (select ts_utc from eia_h union select ts_utc from ercot_load_h union select ts_utc from ercot_wind_h union select ts_utc from ercot_solar_h)
select k.ts_utc,
       case when l.covered_min >= 55 then l.load_mw else e.demand_mw end demand_mw,
       case when l.covered_min >= 55 then 'ercot' when e.demand_mw is not null then 'eia' end src_demand,
       coalesce(w.wind_gen_mw, e.wind_mw) wind_mw,
       case when w.wind_gen_mw is not null then 'ercot' when e.wind_mw is not null then 'eia' end src_wind,
       coalesce(s.solar_gen_mw, e.solar_mw) solar_mw,
       case when s.solar_gen_mw is not null then 'ercot' when e.solar_mw is not null then 'eia' end src_solar
from keys k
left join eia_h e on e.ts_utc = k.ts_utc
left join ercot_load_h l on l.ts_utc = k.ts_utc
left join ercot_wind_h w on w.ts_utc = k.ts_utc
left join ercot_solar_h s on s.ts_utc = k.ts_utc
""")
anchor_ts = spark.sql("select max(ts_utc) from actual_h where demand_mw is not null and wind_mw is not null and solar_mw is not null").first()[0]
print("anchor_ts =", anchor_ts)

# COMMAND ----------

# MAGIC %md ## 3. `silver.grid_hourly`

# COMMAND ----------

wx_cols = [c for c in spark.table(f"{S}.weather_hourly").columns if c != "ts_utc"]
grid = spark.sql(f"""
with spine as (
  select explode(sequence(timestamp'{START}', timestamp'{anchor_ts}' + interval 48 hours, interval 1 hour)) ts_utc
),
j as (
  select s.ts_utc, s.ts_utc > timestamp'{anchor_ts}' is_forecast_row,
         a.demand_mw, a.wind_mw, a.solar_mw, a.src_demand, a.src_wind, a.src_solar,
         p.price_usd_mwh, p.price_max_usd_mwh, p.utc_offset_src,
         e.demand_forecast_mw,
         w.wind_forecast_mw, w.wind_forecast_p80_mw, w.wind_hsl_mw,
         so.solar_forecast_mw, so.solar_forecast_p80_mw, so.solar_hsl_mw
  from spine s
  left join actual_h a on a.ts_utc = s.ts_utc
  left join prices_h p on p.ts_utc = s.ts_utc
  left join eia_h e on e.ts_utc = s.ts_utc
  left join ercot_wind_h w on w.ts_utc = s.ts_utc
  left join ercot_solar_h so on so.ts_utc = s.ts_utc
)
select j.ts_utc,
       from_utc_timestamp(j.ts_utc, 'America/Chicago') ts_local,
       coalesce(j.utc_offset_src,
                case when timestampdiff(HOUR, j.ts_utc, from_utc_timestamp(j.ts_utc, 'America/Chicago')) = -5 then '-05:00' else '-06:00' end) utc_offset,
       case when is_forecast_row then null else demand_mw end demand_mw,
       case when is_forecast_row then null else wind_mw end wind_mw,
       case when is_forecast_row then null else solar_mw end solar_mw,
       case when is_forecast_row then null else demand_mw - wind_mw - solar_mw end net_load_mw,
       case when is_forecast_row then null else price_usd_mwh end price_usd_mwh,
       case when is_forecast_row then null else price_max_usd_mwh end price_max_usd_mwh,
       demand_forecast_mw,
       wind_forecast_mw, solar_forecast_mw, wind_forecast_p80_mw, solar_forecast_p80_mw, wind_hsl_mw, solar_hsl_mw,
       {", ".join("wx." + c for c in wx_cols)},
       case when is_forecast_row then null else src_demand end src_demand,
       case when is_forecast_row then null else src_wind end src_wind,
       case when is_forecast_row then null else src_solar end src_solar,
       is_forecast_row,
       timestamp'{anchor_ts}' anchor_ts,
       current_timestamp() _built_at
from j left join {S}.weather_hourly wx on wx.ts_utc = j.ts_utc
""")
grid.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{S}.grid_hourly")
G = f"{S}.grid_hourly"
display(spark.sql(f"select * from {G} where ts_utc >= timestamp'{anchor_ts}' - interval 3 hours order by ts_utc limit 10"))

# COMMAND ----------

# MAGIC %md ## 4. DST demonstration (fall-back: two distinct UTC hours for local 01:00; spring-forward: 23 local hours)

# COMMAND ----------

dst_fall = spark.sql(f"""
select to_date(substr(p.interval_start_local, 1, 10)) local_date, p.interval_start_local, p.interval_start_utc ts_utc,
       p.price_usd_mwh price_15min_at_hour_start, g.price_usd_mwh hourly_price_grid, g.utc_offset, g.ts_local
from prices_d p join {G} g on g.ts_utc = p.interval_start_utc
where substr(p.interval_start_local, 1, 19) in ('2023-11-05T01:00:00', '2024-11-03T01:00:00', '2025-11-02T01:00:00')
order by p.interval_start_utc
""")
display(dst_fall)
dst_fall.createOrReplaceTempView("dst_fall")
fall_rows = spark.sql("""
  select local_date d, count(distinct ts_utc) n_utc, count(distinct right(interval_start_local, 6)) n_offsets,
         count(hourly_price_grid) n_prices, count(distinct hourly_price_grid) n_distinct_prices,
         min(ts_utc) utc_first, max(ts_utc) utc_second
  from dst_fall group by 1 order by 1""").collect()
display(spark.createDataFrame(fall_rows))
fall_ok = len(fall_rows) == 3 and all(r.n_utc == 2 and r.n_offsets == 2 and r.n_prices == 2 and r.n_distinct_prices == 2
                                      and (r.utc_second - r.utc_first).total_seconds() == 3600 for r in fall_rows)

spring_rows = spark.sql(f"""
  select to_date(ts_local) local_date, count(*) n_utc_hours, count(distinct hour(ts_local)) n_local_hours,
         sum(case when hour(ts_local) = 2 then 1 else 0 end) n_hour_02,
         timestampdiff(HOUR, min(ts_utc), max(ts_utc)) + 1 utc_span
  from {G} where to_date(ts_local) in (date'2023-03-12', date'2024-03-10', date'2025-03-09')
  group by 1 order by 1""").collect()
display(spark.createDataFrame(spring_rows))
spring_ok = len(spring_rows) == 3 and all(r.n_utc_hours == 23 and r.n_local_hours == 23 and r.n_hour_02 == 0 and r.utc_span == 23 for r in spring_rows)
print("dst_fallback_distinct_utc =", fall_ok, "| spring_forward_23h =", spring_ok)

# COMMAND ----------

# MAGIC %md ## 5. EIA vs ERCOT live-load cross-check (confirms EIA hour-ending → interval-start conversion)

# COMMAND ----------

xchk = spark.sql("""
select o.offset_h,
       avg(abs(e.demand_mw - l.load_mw) / l.load_mw) * 100 mean_abs_pct_diff,
       count(*) n_hours
from ercot_load_h l
cross join (select explode(sequence(-2, 2)) offset_h) o
join eia_h e on e.ts_utc = timestampadd(HOUR, o.offset_h, l.ts_utc)
where l.covered_min >= 55 and e.demand_mw is not null
group by o.offset_h order by o.offset_h
""")
display(xchk)
xr = xchk.collect()
best = min(xr, key=lambda r: r.mean_abs_pct_diff) if xr else None
xchk_best_offset = best.offset_h if best else None
xchk_mape0 = next((r.mean_abs_pct_diff for r in xr if r.offset_h == 0), None)
ren_x = spark.sql("""
select 'wind' kind, avg(abs(e.wind_mw - w.wind_gen_mw)) mean_abs_diff_mw, count(*) n from eia_h e join ercot_wind_h w using (ts_utc) where e.wind_mw is not null and w.wind_gen_mw is not null
union all
select 'solar', avg(abs(e.solar_mw - s.solar_gen_mw)), count(*) from eia_h e join ercot_solar_h s using (ts_utc) where e.solar_mw is not null and s.solar_gen_mw is not null
""")
display(ren_x)
print(f"best offset = {xchk_best_offset} h, mean abs % diff at offset 0 = {xchk_mape0}")

# COMMAND ----------

# MAGIC %md ## 6. Data quality: acceptance checks + missing hours per month → `silver.dq_checks`

# COMMAND ----------

def q1(sql):
    return spark.sql(sql).first()

checks = {}
def chk(name, value, ok):
    checks[name] = {"value": value, "pass": bool(ok)}

r = q1(f"select count(*) n, count(distinct ts_utc) d, timestampdiff(HOUR, min(ts_utc), max(ts_utc)) + 1 span, min(ts_utc) mn, max(ts_utc) mx from {G}")
chk("grid_unique_grain", f"{r.n} rows / {r.d} distinct", r.n == r.d)
chk("grid_continuity", f"{r.n} rows / span {r.span}", r.n == r.span)
chk("grid_min_ts", str(r.mn), str(r.mn) == "2023-01-01 00:00:00")
chk("grid_max_ts_eq_anchor_plus_48h", str(r.mx), (r.mx - anchor_ts).total_seconds() == 48 * 3600)
w = q1(f"select count(*) n, count(distinct ts_utc) d, timestampdiff(HOUR, min(ts_utc), max(ts_utc)) + 1 span from {S}.weather_hourly")
chk("weather_unique_grain", f"{w.n} rows / {w.d} distinct", w.n == w.d)
chk("weather_continuity", f"{w.n} rows / span {w.span}", w.n == w.span)
now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
lag_h = round((now_utc - anchor_ts).total_seconds() / 3600, 2)
chk("anchor_fresh_within_6h", f"anchor {anchor_ts}, {lag_h} h behind now", lag_h <= 6)

r = q1(f"select count_if(is_forecast_row) n, avg(case when temp_f is not null then 1.0 else 0 end) filter (where is_forecast_row) t from {G}")
chk("forecast_rows_eq_48", r.n, r.n == 48)
chk("forecast_rows_temp_nonnull", round(float(r.t or 0), 4), (r.t or 0) >= 0.95)

r = q1(f"select avg(case when demand_mw is null then 1.0 else 0 end) x from {G} where year(ts_utc) = 2023")
chk("eia_rescue_2023_demand_null_rate", round(float(r.x), 5), r.x < 0.01)

r = q1(f"""select avg(case when demand_mw is null then 1.0 else 0 end) d, avg(case when net_load_mw is null then 1.0 else 0 end) n,
               avg(case when price_usd_mwh is null then 1.0 else 0 end) p, avg(case when temp_f is null then 1.0 else 0 end) t,
               avg(case when wind_mw is null then 1.0 else 0 end) w, avg(case when solar_mw is null then 1.0 else 0 end) s
        from {G} where not is_forecast_row""")
chk("null_rate_demand", round(float(r.d), 5), r.d < 0.01)
chk("null_rate_net_load", round(float(r.n), 5), r.n < 0.01)
chk("null_rate_price", round(float(r.p), 5), r.p < 0.01)
chk("null_rate_temp", round(float(r.t), 5), r.t < 0.02)
chk("null_rate_wind_info", round(float(r.w), 5), True)
chk("null_rate_solar_info", round(float(r.s), 5), True)

r = q1(f"""select min(demand_mw) dmin, max(demand_mw) dmax, min(net_load_mw) nmin, max(net_load_mw) nmax,
               min(wind_mw) wmin, max(wind_mw) wmax, min(solar_mw) smin, max(solar_mw) smax,
               min(price_usd_mwh) pmin, max(price_usd_mwh) pmax, max(price_max_usd_mwh) pmax15,
               count_if(demand_mw not between 30000 and 95000) bd, count_if(net_load_mw not between 3000 and 80000) bn,
               count_if(wind_mw not between 0 and 40000) bw, count_if(solar_mw not between 0 and 35000) bs,
               count_if(price_max_usd_mwh not between -250 and 5100 or price_usd_mwh not between -250 and 5100) bp
        from {G}""")
chk("plaus_demand_30_95gw", f"{r.dmin}..{r.dmax}, {r.bd} out", r.bd == 0)
chk("plaus_net_load_3_80gw", f"{r.nmin}..{r.nmax}, {r.bn} out", r.bn == 0)
chk("plaus_wind_0_40gw", f"{r.wmin}..{r.wmax}, {r.bw} out", r.bw == 0)
chk("plaus_solar_0_35gw", f"{r.smin}..{r.smax}, {r.bs} out", r.bs == 0)
chk("price_sanity_-250_5100", f"{r.pmin}..{r.pmax} (15-min max {r.pmax15}), {r.bp} out", r.bp == 0)

chk("dst_fallback_distinct_utc", [f"{x.d}: {x.utc_first}/{x.utc_second} prices {x.n_distinct_prices}" for x in fall_rows], fall_ok)
chk("dst_spring_forward_23h", [f"{x.local_date}: {x.n_local_hours}h" for x in spring_rows], spring_ok)

r = q1(f"""select count(*) n, count_if(src_demand = 'ercot') e from
          (select src_demand from {G} where not is_forecast_row order by ts_utc desc limit 24)""")
chk("src_last24_demand_ercot", f"{r.e}/{r.n}", r.e == 24)
chk("xchk_eia_vs_ercot_best_offset_h", xchk_best_offset, xchk_best_offset == 0)
chk("xchk_eia_vs_ercot_mean_abs_pct_diff", None if xchk_mape0 is None else round(float(xchk_mape0), 4), xchk_mape0 is not None and xchk_mape0 < 1.0)

r = q1(f"select count_if(price_usd_mwh > 100) / count(price_usd_mwh) x from {G} where not is_forecast_row")
chk("spike_rate_info", round(float(r.x), 4), 0.01 <= r.x <= 0.06)

# Missing hours per month per column (actual rows only)
miss = spark.sql(f"""
select date_format(ts_utc, 'yyyy-MM') month, count(*) hours,
       count_if(demand_mw is null) demand_mw, count_if(wind_mw is null) wind_mw, count_if(solar_mw is null) solar_mw,
       count_if(net_load_mw is null) net_load_mw, count_if(price_usd_mwh is null) price_usd_mwh, count_if(temp_f is null) temp_f
from {G} where not is_forecast_row group by 1 order by 1""")
display(miss)
display(spark.sql(f"""select src_demand, src_wind, src_solar, count(*) n, min(ts_utc), max(ts_utc) from {G}
                      where not is_forecast_row group by all order by 5"""))
display(spark.sql(f"select wx_source, count(*) n, min(ts_utc), max(ts_utc) from {G} group by 1 order by 3"))

rows = [(k, json.dumps(v["value"], default=str), v["pass"]) for k, v in checks.items()]
for m in miss.collect():
    for c in ["demand_mw", "wind_mw", "solar_mw", "net_load_mw", "price_usd_mwh", "temp_f"]:
        if m[c] > 0:
            rows.append((f"missing_hours|{c}|{m.month}", json.dumps({"missing": m[c], "hours": m.hours}), m[c] <= 0.05 * m.hours))
spark.createDataFrame(rows, "check string, value string, pass boolean") \
     .withColumn("_built_at", F.current_timestamp()) \
     .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{S}.dq_checks")
display(spark.table(f"{S}.dq_checks"))

# COMMAND ----------

all_pass = all(v["pass"] for v in checks.values())
summary = {**checks, "anchor_ts": str(anchor_ts), "all_pass": all_pass,
           "failed": [k for k, v in checks.items() if not v["pass"]]}
dbutils.notebook.exit(json.dumps(summary, default=str))
