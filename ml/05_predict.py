# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Predict (Phase 3.6, batch inference)
# MAGIC Scores the 48 forecast rows of `grid.gold.features` with the three `@champion` models and **appends** one batch
# MAGIC per `run_ts` (= `anchor_ts`) to `grid.gold.forecasts`. Re-running for the same `run_ts` first deletes that batch,
# MAGIC so the notebook is idempotent.
# MAGIC
# MAGIC | column | source / rule |
# MAGIC |---|---|
# MAGIC | `net_load_p10/p50/p90` | Model A `grid.ml.net_load@champion` (CQR-padded quantiles) |
# MAGIC | `demand_p50` | Model D `grid.ml.demand@champion` on `FEATURES_D` (all in Gold since the Phase 3 handoff) |
# MAGIC | `wind_fcst_mw`, `solar_fcst_mw` | ERCOT STWPF/STPPF latest publish, from `silver.grid_hourly` (null if missing) |
# MAGIC | `net_load_alt` | `demand_p50 − wind_fcst_mw − solar_fcst_mw` (null if either forecast is missing) |
# MAGIC | `net_load_used`, `strain_source` | `net_load_alt` / `'demand_minus_ercot_renewables'` when both ERCOT forecasts exist, else Model A P50 / `'model_a'` |
# MAGIC | `spike_prob` | Model B `grid.ml.spike@champion`, its `net_load_p50` input = **`net_load_used`** (see §3) |
# MAGIC | `strain_index` | percentile of `net_load_used` in `gold.strain_reference` for the target's **local** month (linear interpolation between the 101 breakpoints, clipped 0..100), `+15` capped at 100 when `spike_prob > 0.5` |
# MAGIC | `level` | `green` < 60 ≤ `yellow` ≤ 85 < `red` (same thresholds as `gold.strain_hourly`) |
# MAGIC | `demand_p10/p90` | Model D calibrated interval (test coverage 86.6 %) |
# MAGIC | `wind_fcst_p80_mw`, `solar_fcst_p80_mw` | ERCOT downside (P80 = low-side) renewable forecasts from Silver |
# MAGIC | `band_low/high` | **alt rows:** `band_low = demand_p10 − wind_fcst − solar_fcst`, `band_high = demand_p90 − wind_p80 − solar_p80` (P80 falls back to the point forecast if null), clamped so `band_low ≤ net_load_used ≤ band_high`. **model_a rows:** Model A P10/P90 shifted by `net_load_used − net_load_p50` (= 0) |
# MAGIC | `band_source` | `'model_d_plus_ercot_p80'` or `'model_a_cqr'` |
# MAGIC | `low_confidence` | `band_high − band_low > 0.2 · net_load_used` |
# MAGIC
# MAGIC **Why `net_load_used` (contract §6 open item 2):** Model A has no wind/solar forecast input (ERCOT forecasts have no
# MAGIC history), and on the current forecast rows its P50 sits ~12 GW below `demand_p50 − ERCOT wind − ERCOT solar`; its
# MAGIC Oct–Nov test MAPE is ~17 %. Model D (demand, 3.45 % test MAPE) plus ERCOT's own renewable forecast is the better
# MAGIC 48 h net-load estimate when ERCOT forecasts exist, so strain must use it, or a tight evening would show green.

# COMMAND ----------

# MAGIC %pip install -q lightgbm==4.5.0 shap==0.46.0 "mlflow>=2.21.3"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import json
import os

# Same UC artifact route as 04_train (Free Edition serverless denies direct S3 access to UC model storage).
os.environ["MLFLOW_USE_DATABRICKS_SDK_MODEL_ARTIFACTS_REPO_FOR_UC"] = "true"
from datetime import datetime, timezone

import mlflow
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient

dbutils.widgets.text("catalog", "grid")
catalog = dbutils.widgets.get("catalog")
spark.conf.set("spark.sql.session.timeZone", "UTC")
mlflow.set_registry_uri("databricks-uc")
client = MlflowClient()

NAME_A = f"{catalog}.ml.net_load"
NAME_B = f"{catalog}.ml.spike"
NAME_D = f"{catalog}.ml.demand"
TABLE = f"{catalog}.gold.forecasts"
SPIKE_BOOST_PROB = 0.5
SPIKE_BOOST = 15.0
GREEN_MAX, YELLOW_MAX = 60.0, 85.0      # green < 60, yellow 60..85, red > 85 (contract §2.3)
LOW_CONF_REL_WIDTH = 0.50              # band wider than 50% of the value -> flag (0.20 flagged every hour)
ANCHOR_HOURS = 6                       # demand anchor: mean Model D error over the last 6 actual hours ...
ANCHOR_TAU_H = 12.0                    # ... applied with weight exp(-h / 12): ~92% at h=1, ~2% by h=48
FIRST_HOUR_TOL_PCT, FIRST_HOUR_TOL_MW = 0.05, 2500.0
SRC_ALT, SRC_A = "demand_minus_ercot_renewables", "model_a"

# Feature lists are identical to 04_train (contract §3). The pyfunc wrappers select their own columns, so these are
# used only to check that Gold carries every input and to build the frames.
FEATURES_A = [
    "hour", "dow", "month", "doy", "is_weekend", "is_holiday",
    "hour_sin", "hour_cos", "doy_sin", "doy_cos",
    "temp_f", "heat_index_f", "rh_pct", "wind_mph", "cloud_pct", "ghi_wm2",
    "temp_f_hou", "temp_f_dfw", "temp_f_aus", "temp_f_sat",
    "cdd", "hdd", "temp_f_roll24_mean",
    "nl_lag_48h", "nl_lag_72h", "nl_lag_168h", "nl_lag_336h",
    "demand_lag_48h", "demand_lag_168h", "wind_lag_48h", "wind_lag_168h",
    "solar_lag_48h", "solar_lag_168h",
    "nl_roll24_mean_l48", "nl_roll168_mean_l48", "nl_roll168_max_l48",
]
PRICE_FEATURES = ["price_lag_48h", "price_lag_168h", "price_roll168_mean_l48",
                  "price_roll168_max_l48", "spike_count_168_l48"]
FEATURES_B = FEATURES_A + PRICE_FEATURES + ["net_load_p50"]
DEMAND_EXTRA = ["demand_lag_72h", "demand_lag_336h", "demand_roll24_mean_l48", "demand_roll168_mean_l48",
                "demand_roll168_max_l48"]
FEATURES_D = FEATURES_A + DEMAND_EXTRA

# COMMAND ----------

# MAGIC %md ## 1 · Load the 48 forecast rows (Gold) and the ERCOT renewable forecasts (Silver)

# COMMAND ----------

feat_sdf = spark.table(f"{catalog}.gold.features")
need = set(FEATURES_D + PRICE_FEATURES + ["ts_utc", "ts_local", "is_forecast_row", "anchor_ts"])
missing = sorted(need - set(feat_sdf.columns))
assert not missing, f"gold.features is missing inputs: {missing}"

fcst = (feat_sdf.where("is_forecast_row")
        .select(*sorted(need)).toPandas().sort_values("ts_utc").reset_index(drop=True))
fcst["ts_utc"] = pd.to_datetime(fcst["ts_utc"])
fcst["ts_local"] = pd.to_datetime(fcst["ts_local"])
run_ts = pd.to_datetime(fcst["anchor_ts"].iloc[0])
assert fcst["anchor_ts"].nunique() == 1, "anchor_ts is not constant"

ren = (spark.table(f"{catalog}.silver.grid_hourly").where("is_forecast_row")
       .selectExpr("ts_utc", "wind_forecast_mw AS wind_fcst_mw", "solar_forecast_mw AS solar_fcst_mw",
                   "wind_forecast_p80_mw AS wind_fcst_p80_mw", "solar_forecast_p80_mw AS solar_fcst_p80_mw")
       .toPandas())
ren["ts_utc"] = pd.to_datetime(ren["ts_utc"])
fcst = fcst.merge(ren, on="ts_utc", how="left")
print(f"run_ts (anchor_ts) = {run_ts} | forecast rows = {len(fcst)} | "
      f"ERCOT wind non-null {fcst['wind_fcst_mw'].notna().sum()} / solar non-null {fcst['solar_fcst_mw'].notna().sum()}")


def to_X(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """All model inputs are float64 (NaN = missing); the registered signatures expect doubles."""
    return df[cols].astype("float64")

# COMMAND ----------

# MAGIC %md ## 2 · Load the `@champion` models and score A and D

# COMMAND ----------


def champion(name):
    mv = client.get_model_version_by_alias(name, "champion")
    return mlflow.pyfunc.load_model(f"models:/{name}@champion"), str(mv.version)


model_A, ver_A = champion(NAME_A)
model_B, ver_B = champion(NAME_B)
model_D, ver_D = champion(NAME_D)
print(f"champions: net_load v{ver_A} | spike v{ver_B} | demand v{ver_D}")

out_A = model_A.predict(to_X(fcst, FEATURES_A)).reset_index(drop=True)
out_D = model_D.predict(to_X(fcst, FEATURES_D)).reset_index(drop=True)
assert out_A.shape == (48, 3) and out_D.shape == (48, 3), (out_A.shape, out_D.shape)

res = pd.DataFrame({
    "run_ts": run_ts,
    "target_ts": fcst["ts_utc"].values,
    "horizon_h": ((fcst["ts_utc"] - run_ts) / pd.Timedelta(hours=1)).round().astype(int).values,
    "net_load_p10": out_A["net_load_p10"].values,
    "net_load_p50": out_A["net_load_p50"].values,
    "net_load_p90": out_A["net_load_p90"].values,
    "demand_p10": out_D["demand_p10"].values,
    "demand_p50": out_D["demand_p50"].values,
    "demand_p90": out_D["demand_p90"].values,
    "wind_fcst_p80_mw": fcst["wind_fcst_p80_mw"].astype("float64").values,
    "solar_fcst_p80_mw": fcst["solar_fcst_p80_mw"].astype("float64").values,
    "wind_fcst_mw": fcst["wind_fcst_mw"].astype("float64").values,
    "solar_fcst_mw": fcst["solar_fcst_mw"].astype("float64").values,
})
# COMMAND ----------

# MAGIC %md ## 2b · Demand anchor (recency correction)
# MAGIC The lag-48 floor means Model D never sees the last 48 h of demand, so the start of the forecast can sit several GW
# MAGIC away from what is happening right now (PM review: 49.7 GW forecast right after an observed, rising 53.1 GW).
# MAGIC We score Model D on the last `ANCHOR_HOURS` **actual** hours, take its mean error (`demand_bias_mw`), and add
# MAGIC `bias × exp(−h / ANCHOR_TAU_H)` to demand P10/P50/P90. The correction is strongest at h=1 and fades to ~0 by
# MAGIC h=48, where the model's own seasonal and weather signal takes over. This is standard forecast "anchoring", and
# MAGIC it uses only data known at `run_ts`.

# COMMAND ----------

from pyspark.sql import functions as F

hist = (feat_sdf.where("NOT is_forecast_row").orderBy(F.col("ts_utc").desc()).limit(ANCHOR_HOURS)
        .select("ts_utc", *FEATURES_D).toPandas())
act = (spark.table(f"{catalog}.silver.grid_hourly").where("NOT is_forecast_row AND demand_mw IS NOT NULL")
       .orderBy(F.col("ts_utc").desc()).limit(ANCHOR_HOURS * 2).select("ts_utc", "demand_mw").toPandas())
hist["ts_utc"], act["ts_utc"] = pd.to_datetime(hist["ts_utc"]), pd.to_datetime(act["ts_utc"])
hist = hist.merge(act, on="ts_utc", how="inner").sort_values("ts_utc")
last_actual_demand = float(act.sort_values("ts_utc")["demand_mw"].iloc[-1])
if len(hist) >= 3:
    hist_pred = model_D.predict(to_X(hist, FEATURES_D))["demand_p50"].astype("float64").values
    demand_bias = float(np.mean(hist["demand_mw"].values - hist_pred))
else:
    demand_bias = 0.0
print(f"demand anchor: {len(hist)} recent actual hours, mean Model D error = {demand_bias:+,.0f} MW, "
      f"latest actual demand = {last_actual_demand:,.0f} MW")

res["demand_p50_raw"] = res["demand_p50"]
res["demand_bias_mw"] = demand_bias
res["demand_anchor_adj_mw"] = demand_bias * np.exp(-res["horizon_h"] / ANCHOR_TAU_H)
for q in ("demand_p10", "demand_p50", "demand_p90"):
    res[q] = res[q] + res["demand_anchor_adj_mw"]

res["net_load_alt"] = res["demand_p50"] - res["wind_fcst_mw"] - res["solar_fcst_mw"]   # NaN if a forecast is missing
has_ren = res["wind_fcst_mw"].notna() & res["solar_fcst_mw"].notna()
res["strain_source"] = np.where(has_ren, SRC_ALT, SRC_A)
res["net_load_used"] = np.where(has_ren, res["net_load_alt"], res["net_load_p50"])

# COMMAND ----------

# MAGIC %md ## 3 · Model B (spike) — fed `net_load_used` as its `net_load_p50` input
# MAGIC Model B's only net-load feature is named `net_load_p50` (Model A's P50 at training time). At inference it receives
# MAGIC **`net_load_used`**: the spike risk should follow the best available net-load estimate, and when ERCOT forecasts
# MAGIC exist that is `net_load_alt`, not Model A. Model B was trained on Model A's P50 distribution, which is in the
# MAGIC same MW units and range, so the input stays in-distribution. For transparency the probability with Model A's P50
# MAGIC is also stored as `spike_prob_model_a_input`.

# COMMAND ----------

xb_used = to_X(fcst.assign(net_load_p50=res["net_load_used"].values), FEATURES_B)
xb_a = to_X(fcst.assign(net_load_p50=res["net_load_p50"].values), FEATURES_B)
res["spike_prob"] = model_B.predict(xb_used)["spike_prob"].astype("float64").values
res["spike_prob_model_a_input"] = model_B.predict(xb_a)["spike_prob"].astype("float64").values

# COMMAND ----------

# MAGIC %md ## 4 · Strain index, level, centred band, confidence

# COMMAND ----------

ref = spark.table(f"{catalog}.gold.strain_reference").toPandas()
ref_by_month = {int(m): g.sort_values("pct") for m, g in ref.groupby("month")}
assert set(ref_by_month) == set(range(1, 13)), f"strain_reference months: {sorted(ref_by_month)}"

local_month = fcst["ts_local"].dt.month.astype(int).values   # ts_local = America/Chicago wall clock (contract §1.2)


def percentile_in_month(value, month):
    g = ref_by_month[int(month)]
    xp = np.maximum.accumulate(g["net_load_mw"].to_numpy(float))   # breakpoints are monotone; guard float ties
    return float(np.interp(value, xp, g["pct"].to_numpy(float), left=0.0, right=100.0))


res["local_month"] = local_month
res["strain_base"] = [percentile_in_month(v, m) for v, m in zip(res["net_load_used"], local_month)]
res["strain_index"] = np.where(res["spike_prob"] > SPIKE_BOOST_PROB,
                               np.minimum(100.0, res["strain_base"] + SPIKE_BOOST), res["strain_base"])
res["level"] = np.select([res["strain_index"] < GREEN_MAX, res["strain_index"] <= YELLOW_MAX],
                         ["green", "yellow"], "red")

# Band = uncertainty of the number strain actually uses.
#  alt rows : low  = demand_p10 - wind_fcst - solar_fcst (low demand, renewables as forecast)
#             high = demand_p90 - wind_p80 - solar_p80   (high demand, ERCOT's low-side renewables; P80 -> point if null)
#             then clamped so band_low <= net_load_used <= band_high.
#  model_a  : Model A CQR P10/P90 shifted by (net_load_used - net_load_p50), which is 0 on these rows.
shift = res["net_load_used"] - res["net_load_p50"]
a_low, a_high = res["net_load_p10"] + shift, res["net_load_p90"] + shift
wind_lo = res["wind_fcst_p80_mw"].fillna(res["wind_fcst_mw"])
solar_lo = res["solar_fcst_p80_mw"].fillna(res["solar_fcst_mw"])
d_low = np.minimum(res["demand_p10"] - res["wind_fcst_mw"] - res["solar_fcst_mw"], res["net_load_used"])
d_high = np.maximum(res["demand_p90"] - wind_lo - solar_lo, res["net_load_used"])
res["band_low"] = np.where(has_ren, d_low, a_low)
res["band_high"] = np.where(has_ren, d_high, a_high)
res["band_source"] = np.where(has_ren, "model_d_plus_ercot_p80", "model_a_cqr")
res["low_confidence"] = (res["band_high"] - res["band_low"]) > LOW_CONF_REL_WIDTH * res["net_load_used"]

res["model_a_version"], res["model_b_version"], res["model_d_version"] = ver_A, ver_B, ver_D
res["created_at"] = datetime.now(timezone.utc).replace(tzinfo=None)

COLS = ["run_ts", "target_ts", "horizon_h", "net_load_p10", "net_load_p50", "net_load_p90", "demand_p50",
        "wind_fcst_mw", "solar_fcst_mw", "net_load_alt", "net_load_used", "strain_source", "spike_prob",
        "spike_prob_model_a_input", "local_month", "strain_base", "strain_index", "level", "band_low", "band_high",
        "low_confidence", "model_a_version", "model_b_version", "model_d_version", "created_at",
        "demand_p10", "demand_p90", "wind_fcst_p80_mw", "solar_fcst_p80_mw", "band_source",
        "demand_p50_raw", "demand_bias_mw", "demand_anchor_adj_mw"]
res = res[COLS]
display(res)
print(res[["target_ts", "horizon_h", "net_load_p50", "demand_p50", "wind_fcst_mw", "solar_fcst_mw", "net_load_alt",
           "net_load_used", "strain_source", "spike_prob", "strain_index", "level", "demand_p10", "demand_p90",
           "band_low", "band_high", "low_confidence"]].round(1).to_string())

# COMMAND ----------

# MAGIC %md ## 5 · Write: delete this `run_ts` batch, then append

# COMMAND ----------

SCHEMA = """run_ts TIMESTAMP, target_ts TIMESTAMP, horizon_h INT, net_load_p10 DOUBLE, net_load_p50 DOUBLE,
  net_load_p90 DOUBLE, demand_p50 DOUBLE, wind_fcst_mw DOUBLE, solar_fcst_mw DOUBLE, net_load_alt DOUBLE,
  net_load_used DOUBLE, strain_source STRING, spike_prob DOUBLE, spike_prob_model_a_input DOUBLE, local_month INT,
  strain_base DOUBLE, strain_index DOUBLE, level STRING, band_low DOUBLE, band_high DOUBLE, low_confidence BOOLEAN,
  model_a_version STRING, model_b_version STRING, model_d_version STRING, created_at TIMESTAMP,
  demand_p10 DOUBLE, demand_p90 DOUBLE, wind_fcst_p80_mw DOUBLE, solar_fcst_p80_mw DOUBLE, band_source STRING,
  demand_p50_raw DOUBLE, demand_bias_mw DOUBLE, demand_anchor_adj_mw DOUBLE"""
spark.sql(f"CREATE TABLE IF NOT EXISTS {TABLE} ({SCHEMA}) USING DELTA "
          f"COMMENT 'GridWise 48 h forecasts, one batch per run_ts (= anchor_ts); written by ml/05_predict'")
# Schema evolution for tables created by the first version of this notebook: add any new columns.
_existing = set(spark.table(TABLE).columns)
_new = [c.strip() for c in SCHEMA.replace("\n", " ").split(",") if c.split()[0] not in _existing]
if _new:
    spark.sql(f"ALTER TABLE {TABLE} ADD COLUMNS ({', '.join(_new)})")
    print("added columns:", _new)

def py(v):
    """numpy/pandas scalars -> plain Python for createDataFrame; NaN -> NULL."""
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.generic):
        v = v.item()
    return None if (isinstance(v, float) and np.isnan(v)) else v


rows = [tuple(py(v) for v in r) for r in res.itertuples(index=False, name=None)]
sdf = spark.createDataFrame(rows, SCHEMA.replace("\n", " "))
run_ts_sql = run_ts.strftime("%Y-%m-%d %H:%M:%S")
spark.sql(f"DELETE FROM {TABLE} WHERE run_ts = TIMESTAMP '{run_ts_sql}'")
sdf.select(*spark.table(TABLE).columns).write.mode("append").saveAsTable(TABLE)

# COMMAND ----------

# MAGIC %md ## 6 · Validation (read back from the table)

# COMMAND ----------

back = spark.sql(f"SELECT * FROM {TABLE} WHERE run_ts = TIMESTAMP '{run_ts_sql}'").toPandas()
levels = back["level"].value_counts().to_dict()
sources = back["strain_source"].value_counts().to_dict()

# Sanity: every hour whose net_load_alt is above its month's 60th-percentile breakpoint must not be green
# (strain uses net_load_alt there), and if any such hour exists the batch cannot be all-green.
p60 = {m: float(np.interp(60, g["pct"], g["net_load_mw"])) for m, g in ref_by_month.items()}
high_alt = back["net_load_alt"].notna() & (back["net_load_alt"] > back["local_month"].map(p60))
green_while_high = int((high_alt & (back["level"] == "green")).sum())


def chk(value, ok):
    return {"value": value if not isinstance(value, float) else round(value, 4), "pass": bool(ok)}


checks = {
    "rows_48": chk(len(back), len(back) == 48),
    "distinct_target_ts_48": chk(int(back["target_ts"].nunique()), back["target_ts"].nunique() == 48),
    "horizon_1_to_48": chk(f"{back['horizon_h'].min()}..{back['horizon_h'].max()}",
                           sorted(back["horizon_h"].tolist()) == list(range(1, 49))),
    "no_null_used_strain_spike": chk(int(back[["net_load_used", "strain_index", "spike_prob"]].isna().sum().sum()),
                                     back[["net_load_used", "strain_index", "spike_prob"]].notna().all().all()),
    "strain_in_0_100": chk(f"{back['strain_index'].min():.1f}..{back['strain_index'].max():.1f}",
                           back["strain_index"].between(0, 100).all()),
    "spike_prob_in_0_1": chk(float(back["spike_prob"].max()), back["spike_prob"].between(0, 1).all()),
    "quantiles_ordered": chk("p10<=p50<=p90", ((back["net_load_p10"] <= back["net_load_p50"])
                                                & (back["net_load_p50"] <= back["net_load_p90"])).all()),
    "band_contains_used": chk("band_low<=used<=band_high", ((back["band_low"] <= back["net_load_used"])
                                                             & (back["net_load_used"] <= back["band_high"])).all()),
    "strain_source_consistent": chk(sources, (
        (back["strain_source"] == SRC_ALT) == (back["wind_fcst_mw"].notna() & back["solar_fcst_mw"].notna())).all()
        and np.allclose(back.loc[back["strain_source"] == SRC_ALT, "net_load_used"],
                        back.loc[back["strain_source"] == SRC_ALT, "net_load_alt"])),
    "no_green_when_alt_high": chk({"high_alt_hours": int(high_alt.sum()), "green_while_high": green_while_high},
                                  green_while_high == 0 and (high_alt.sum() == 0 or levels.get("green", 0) < 48)),
    "level_thresholds": chk(levels, (
        (back["level"] == np.select([back["strain_index"] < GREEN_MAX, back["strain_index"] <= YELLOW_MAX],
                                    ["green", "yellow"], "red"))).all()),
    "band_source_consistent": chk(back["band_source"].value_counts().to_dict(),
                                  ((back["band_source"] == "model_d_plus_ercot_p80")
                                   == (back["strain_source"] == SRC_ALT)).all()),
    "demand_quantiles_ordered": chk("d10<=d50<=d90", ((back["demand_p10"] <= back["demand_p50"])
                                                      & (back["demand_p50"] <= back["demand_p90"])).all()),
    "single_batch_per_run_ts": chk(int(spark.sql(f"SELECT count(*) c FROM {TABLE} WHERE run_ts = TIMESTAMP "
                                                 f"'{run_ts_sql}'").first()["c"]), True),
}
checks["single_batch_per_run_ts"]["pass"] = checks["single_batch_per_run_ts"]["value"] == 48
_h1 = float(back.sort_values("target_ts")["demand_p50"].iloc[0])
_gap = abs(_h1 - last_actual_demand)
checks["first_hour_near_actual"] = chk(
    {"h1_demand": round(_h1), "last_actual": round(last_actual_demand), "gap_mw": round(_gap),
     "bias_mw": round(demand_bias)},
    _gap <= max(FIRST_HOUR_TOL_PCT * last_actual_demand, FIRST_HOUR_TOL_MW))
checks["low_conf_not_all"] = chk(int(back["low_confidence"].sum()), int(back["low_confidence"].sum()) < 48)
failed = [k for k, v in checks.items() if not v["pass"]]

first = back.sort_values("target_ts").iloc[0]
summary = {
    **checks,
    "all_pass": not failed,
    "failed": failed,
    "run_ts": str(run_ts),
    "table": TABLE,
    "levels": levels,
    "strain_source": sources,
    "low_confidence_hours": int(back["low_confidence"].sum()),
    "low_confidence_share": round(float(back["low_confidence"].mean()), 3),
    "band_width_mw": {k: round(float(v), 0) for k, v in (back["band_high"] - back["band_low"]).describe()
                      [["mean", "min", "50%", "max"]].items()},
    "band_rel_width": {k: round(float(v), 3) for k, v in ((back["band_high"] - back["band_low"])
                       / back["net_load_used"]).quantile([0.25, 0.5, 0.75, 0.9, 1.0]).items()},
    "spike_boosted_hours": int((back["spike_prob"] > SPIKE_BOOST_PROB).sum()),
    "max_strain": round(float(back["strain_index"].max()), 1),
    "max_net_load_used": round(float(back["net_load_used"].max()), 0),
    "mean_gap_alt_minus_a_mw": round(float((back["net_load_alt"] - back["net_load_p50"]).mean()), 0),
    "first_hour": {k: (round(float(first[k]), 1) if isinstance(first[k], (float, np.floating)) else str(first[k]))
                   for k in ["target_ts", "net_load_p50", "demand_p50", "wind_fcst_mw", "solar_fcst_mw",
                             "net_load_alt", "net_load_used", "spike_prob", "strain_index", "level"]},
    "models": {"net_load": ver_A, "spike": ver_B, "demand": ver_D},
    "notes": ["spike_prob uses net_load_used as Model B's net_load_p50 input; spike_prob_model_a_input kept",
              "alt band = [demand_p10 - wind - solar, demand_p90 - wind_p80 - solar_p80] clamped around used; "
              "model_a band = Model A P10/P90",
              "strain percentile linearly interpolated in gold.strain_reference by local month"],
}
print(json.dumps(summary, indent=1, default=str))
assert not failed, f"failed checks: {failed}"

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary, default=str))
