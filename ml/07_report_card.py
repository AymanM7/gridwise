# Databricks notebook source
# MAGIC %md
# MAGIC # 07 · Report card (Phase 3.7)
# MAGIC Scores forecasts against actuals, one row per **local (America/Chicago) date** and `source`, and merges them into
# MAGIC `grid.gold.report_card` (merge key `date + source`, so re-runs are idempotent).
# MAGIC
# MAGIC | source | what is scored |
# MAGIC |---|---|
# MAGIC | `live` | For each local date with actuals: the `gold.forecasts` batch whose `run_ts` is **closest to 24 h before local midnight** that starts the day (ties go to the earlier batch). Every hour of that day that the batch covers and that has an actual is scored. Net load = `net_load_used` (what strain used), band = `band_low/high`, spike = `spike_prob ≥` the validation threshold of that batch's Model B version. |
# MAGIC | `backtest` | The champions re-score the **out-of-sample test window** of the champion Model A run (`ts_utc > test_start_excl`, up to `anchor_ts`) from `gold.features`, as if each hour was issued with the lag-48 floor. Net load = Model A P50, band = Model A's CQR-padded P10..P90, spike = Model B `is_spike_pred` (its `net_load_p50` input = Model A P50, as in training). Only complete local days are kept. |
# MAGIC
# MAGIC Units: `mape`, `wmape`, `band_coverage`, `demand_mape` are **percent (0..100)**; `spike_recall` / `spike_precision` are **0..1**
# MAGIC (null when there is no actual / no predicted spike that day). Extra columns: `demand_mape` (Model D `demand_p50` vs actual demand,
# MAGIC the < 5 % headline), `basis` (which net-load value was scored), `run_ts` (live batch used; null for backtest) and `model_versions`.
# MAGIC
# MAGIC **Backtest caveats.** Backtest hours use archive weather, while live hours use forecast weather, so the backtest is somewhat optimistic.
# MAGIC ERCOT wind and solar forecasts have no history, so the backtest scores Model A, not `demand − ERCOT renewables`. On live days, after
# MAGIC 2026-11-05, `net_load_used` is mostly that alternative. Backtest rows whose dates leave the current champion's test window are deleted,
# MAGIC so the backtest never reports in-sample days. Live rows are kept as history.

# COMMAND ----------

# MAGIC %pip install -q lightgbm==4.5.0 shap==0.46.0 "mlflow>=2.21.3"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import json
import os

os.environ["MLFLOW_USE_DATABRICKS_SDK_MODEL_ARTIFACTS_REPO_FOR_UC"] = "true"   # same UC route as 04/05
from datetime import datetime, timezone

import mlflow
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient
from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "grid")
catalog = dbutils.widgets.get("catalog")
spark.conf.set("spark.sql.session.timeZone", "UTC")
mlflow.set_registry_uri("databricks-uc")
client = MlflowClient()

NAME_A, NAME_B, NAME_D = f"{catalog}.ml.net_load", f"{catalog}.ml.spike", f"{catalog}.ml.demand"
TABLE = f"{catalog}.gold.report_card"
FCST_TABLE = f"{catalog}.gold.forecasts"
COMPUTED_AT = datetime.now(timezone.utc).replace(tzinfo=None)

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


def to_X(df, cols):
    return df[cols].astype("float64")

# COMMAND ----------

# MAGIC %md ## 1 · Actuals and the local-day calendar (from `gold.features`)

# COMMAND ----------

feat_sdf = spark.table(f"{catalog}.gold.features")
need = sorted(set(FEATURES_D + PRICE_FEATURES + ["ts_utc", "ts_local", "is_forecast_row", "anchor_ts",
                                                   "y_net_load_mw", "y_demand_mw", "y_is_spike"]))
missing = sorted(set(need) - set(feat_sdf.columns))
assert not missing, f"gold.features is missing: {missing}"

anchor_ts = pd.Timestamp(feat_sdf.selectExpr("max(anchor_ts) a").first()["a"])

# Calendar: every hour (features is contiguous), so hours_in_day handles 23/25-hour DST days.
cal = (feat_sdf.selectExpr("ts_utc", "to_date(ts_local) AS date").toPandas())
cal["ts_utc"] = pd.to_datetime(cal["ts_utc"])
day_info = cal.groupby("date").agg(day_start_utc=("ts_utc", "min"), hours_in_day=("ts_utc", "size")).reset_index()
print("anchor_ts:", anchor_ts)

# COMMAND ----------

# MAGIC %md ## 2 · Champions, their thresholds and the out-of-sample window

# COMMAND ----------

_model_cache = {}


def load_version(name, version):
    key = (name, str(version))
    if key not in _model_cache:
        _model_cache[key] = mlflow.pyfunc.load_model(f"models:/{name}/{version}")
    return _model_cache[key]


def spike_threshold(version):
    """Validation-chosen decision threshold stored inside the SpikeModel wrapper (fallback: run metric)."""
    try:
        return float(load_version(NAME_B, version).unwrap_python_model().threshold)
    except Exception:
        mv = client.get_model_version(NAME_B, str(version))
        return float(client.get_run(mv.run_id).data.metrics["threshold"])


champ = {}
for nm in (NAME_A, NAME_B, NAME_D):
    mv = client.get_model_version_by_alias(nm, "champion")
    run = client.get_run(mv.run_id)
    champ[nm] = {"version": str(mv.version), "params": run.data.params, "metrics": run.data.metrics}
ver_A, ver_B, ver_D = (champ[n]["version"] for n in (NAME_A, NAME_B, NAME_D))

# Out-of-sample window = the champion runs' test window (latest test start across A/B/D, so no model is in-sample).
starts = [pd.Timestamp(champ[n]["params"]["test_start_excl"]) for n in (NAME_A, NAME_B, NAME_D)
          if "test_start_excl" in champ[n]["params"]]
assert starts, "champion runs carry no test_start_excl param"
TEST_START = max(starts)
thr_B = spike_threshold(ver_B)
print(f"champions A v{ver_A} B v{ver_B} D v{ver_D} | test window: ts_utc > {TEST_START} .. {anchor_ts} | "
      f"spike threshold {thr_B:.4f}")

# COMMAND ----------

# MAGIC %md ## 3 · Per-day metric function (shared by live and backtest)

# COMMAND ----------


def day_metrics(g, y_col, p_col, lo_col, hi_col, ys_col, ps_col, yd_col=None, pd_col=None):
    """g = the scored hours of one local date. Net-load metrics use hours with both actual and prediction."""
    ok = g[y_col].notna() & g[p_col].notna()
    y, p = g.loc[ok, y_col].to_numpy(float), g.loc[ok, p_col].to_numpy(float)
    lo, hi = g.loc[ok, lo_col].to_numpy(float), g.loc[ok, hi_col].to_numpy(float)
    n = int(ok.sum())
    out = {"n_hours": n}
    if n:
        out["mape"] = float(np.mean(np.abs(y - p) / np.abs(y)) * 100)
        out["wmape"] = float(np.sum(np.abs(y - p)) / np.sum(np.abs(y)) * 100)
        out["band_coverage"] = float(np.mean((y >= lo) & (y <= hi)) * 100)
    else:
        out.update(mape=None, wmape=None, band_coverage=None)
    s = g[ys_col].notna() & g[ps_col].notna()
    ys, ps = g.loc[s, ys_col].astype(int).to_numpy(), g.loc[s, ps_col].astype(int).to_numpy()
    actual, pred, caught = int(ys.sum()), int(ps.sum()), int((ys & ps).sum())
    out["spike_hours_actual"], out["spike_hours_caught"] = actual, caught
    out["spike_recall"] = caught / actual if actual else None
    out["spike_precision"] = caught / pred if pred else None
    out["demand_mape"] = None
    if yd_col is not None:
        d = g[yd_col].notna() & g[pd_col].notna()
        if d.any():
            yd, pdm = g.loc[d, yd_col].to_numpy(float), g.loc[d, pd_col].to_numpy(float)
            out["demand_mape"] = float(np.mean(np.abs(yd - pdm) / np.abs(yd)) * 100)
    return out

# COMMAND ----------

# MAGIC %md ## 4 · Backtest: champions re-score the test window

# COMMAND ----------

bt = (feat_sdf.where(f"NOT is_forecast_row AND ts_utc > TIMESTAMP '{TEST_START:%Y-%m-%d %H:%M:%S}' "
                     f"AND ts_utc <= TIMESTAMP '{anchor_ts:%Y-%m-%d %H:%M:%S}'")
      .select(*need).withColumn("date", F.to_date("ts_local"))
      .toPandas().sort_values("ts_utc").reset_index(drop=True))
bt["ts_utc"] = pd.to_datetime(bt["ts_utc"])

model_A, model_B, model_D = (load_version(NAME_A, ver_A), load_version(NAME_B, ver_B), load_version(NAME_D, ver_D))
pa = model_A.predict(to_X(bt, FEATURES_A)).reset_index(drop=True)
pdm = model_D.predict(to_X(bt, FEATURES_D)).reset_index(drop=True)
bt["net_load_p10"], bt["net_load_p50"], bt["net_load_p90"] = (pa[c].values for c in
                                                               ("net_load_p10", "net_load_p50", "net_load_p90"))
bt["demand_p50"] = pdm["demand_p50"].values
pb = model_B.predict(to_X(bt, FEATURES_B)).reset_index(drop=True)   # FEATURES_B's net_load_p50 = Model A P50 (as trained)
bt["spike_prob"] = pb["spike_prob"].values
bt["spike_pred"] = (bt["spike_prob"] >= thr_B).astype(int)
assert int((bt["spike_pred"] != pb["is_spike_pred"].astype(int).values).sum()) == 0, "threshold mismatch with wrapper"

bt = bt.merge(day_info[["date", "hours_in_day"]], on="date", how="left")
bt_rows = []
for d, g in bt.groupby("date"):
    if len(g) != int(g["hours_in_day"].iloc[0]):      # partial first / last local day of the window
        continue
    m = day_metrics(g, "y_net_load_mw", "net_load_p50", "net_load_p10", "net_load_p90", "y_is_spike", "spike_pred",
                    "y_demand_mw", "demand_p50")
    bt_rows.append({"date": d, "source": "backtest", **m, "basis": "model_a_p50", "run_ts": None,
                    "model_versions": f"net_load v{ver_A}, spike v{ver_B}, demand v{ver_D}"})
bt_df = pd.DataFrame(bt_rows)
print(f"backtest: {len(bt)} hours scored, {len(bt_df)} complete local days "
      f"({bt_df['date'].min()} .. {bt_df['date'].max()})")

# Pooled (hour-weighted) backtest metrics, to compare with what 04_train logged for the champion runs.
okp = bt["y_net_load_mw"].notna()
pooled = {
    "mape": float(np.mean(np.abs(bt.loc[okp, "y_net_load_mw"] - bt.loc[okp, "net_load_p50"])
                          / bt.loc[okp, "y_net_load_mw"].abs()) * 100),
    "band_coverage": float(((bt.loc[okp, "y_net_load_mw"] >= bt.loc[okp, "net_load_p10"])
                            & (bt.loc[okp, "y_net_load_mw"] <= bt.loc[okp, "net_load_p90"])).mean() * 100),
    "demand_mape": float(np.mean(np.abs(bt["y_demand_mw"] - bt["demand_p50"]) / bt["y_demand_mw"].abs()) * 100),
    "spike_recall": float(((bt["y_is_spike"] == 1) & (bt["spike_pred"] == 1)).sum() / max(1, (bt["y_is_spike"] == 1).sum())),
}
registered = {"a_test_mape": champ[NAME_A]["metrics"].get("test_mape"),
              "a_test_coverage": champ[NAME_A]["metrics"].get("test_p10_p90_coverage"),
              "d_test_mape": champ[NAME_D]["metrics"].get("test_mape"),
              "b_test_recall": champ[NAME_B]["metrics"].get("test_recall")}
print("pooled backtest:", {k: round(v, 3) for k, v in pooled.items()}, "| registered:", registered)

# COMMAND ----------

# MAGIC %md ## 5 · Live: the batch issued closest to 24 h before each local day

# COMMAND ----------

live_rows, live_expected_dates = [], []
fc_exists = spark.catalog.tableExists(FCST_TABLE)
if fc_exists:
    fc = spark.table(FCST_TABLE).select("run_ts", "target_ts", "net_load_used", "band_low", "band_high",
                                        "spike_prob", "demand_p50", "model_a_version", "model_b_version",
                                        "model_d_version").toPandas()
    fc["run_ts"], fc["target_ts"] = pd.to_datetime(fc["run_ts"]), pd.to_datetime(fc["target_ts"])
    act = (feat_sdf.where("NOT is_forecast_row AND y_net_load_mw IS NOT NULL")
           .where(f"ts_utc >= TIMESTAMP '{fc['target_ts'].min():%Y-%m-%d %H:%M:%S}'")
           .selectExpr("ts_utc AS target_ts", "to_date(ts_local) AS date", "y_net_load_mw", "y_demand_mw", "y_is_spike")
           if len(fc) else None)
    act = act.toPandas() if act is not None else pd.DataFrame(columns=["target_ts", "date"])
    act["target_ts"] = pd.to_datetime(act["target_ts"])
    j = fc.merge(act, on="target_ts", how="inner")            # forecast hours that now have actuals
    j = j.merge(day_info[["date", "day_start_utc"]], on="date", how="left")
    thr_cache = {}
    for d, g in j.groupby("date"):
        live_expected_dates.append(d)
        ideal = g["day_start_utc"].iloc[0] - pd.Timedelta(hours=24)
        cands = pd.DataFrame({"run_ts": g["run_ts"].unique()})
        cands["dist"] = (cands["run_ts"] - ideal).abs()
        best = cands.sort_values(["dist", "run_ts"]).iloc[0]["run_ts"]
        h = g[g["run_ts"] == best].copy()
        vb = str(h["model_b_version"].iloc[0])
        if vb not in thr_cache:
            thr_cache[vb] = spike_threshold(vb)
        h["spike_pred"] = (h["spike_prob"] >= thr_cache[vb]).astype(int)
        m = day_metrics(h, "y_net_load_mw", "net_load_used", "band_low", "band_high", "y_is_spike", "spike_pred",
                        "y_demand_mw", "demand_p50")
        live_rows.append({"date": d, "source": "live", **m, "basis": "net_load_used", "run_ts": best,
                          "model_versions": f"net_load v{h['model_a_version'].iloc[0]}, spike v{vb}, "
                                            f"demand v{h['model_d_version'].iloc[0]}"})
live_df = pd.DataFrame(live_rows)
print(f"live: forecasts table exists={fc_exists}, dates scored={len(live_df)}")
if len(live_df):
    display(live_df)

# COMMAND ----------

# MAGIC %md ## 6 · Merge into `gold.report_card` (key `date + source`)

# COMMAND ----------

SCHEMA = """date DATE, source STRING, mape DOUBLE, wmape DOUBLE, spike_recall DOUBLE, spike_precision DOUBLE,
  spike_hours_actual INT, spike_hours_caught INT, band_coverage DOUBLE, n_hours INT, computed_at TIMESTAMP,
  demand_mape DOUBLE, basis STRING, run_ts TIMESTAMP, model_versions STRING"""
COLS = [c.strip().split(" ")[0] for c in SCHEMA.replace("\n", " ").split(",")]
spark.sql(f"CREATE TABLE IF NOT EXISTS {TABLE} ({SCHEMA}) USING DELTA COMMENT 'GridWise daily report card "
          f"(live forecasts vs actuals, plus champion backtest on the test window); written by ml/07_report_card'")

stage = pd.concat([df for df in (bt_df, live_df) if len(df)], ignore_index=True)
stage["computed_at"] = COMPUTED_AT
stage = stage[COLS]


def py(v):
    if v is None or (not isinstance(v, (str, bytes)) and pd.isna(v)):   # None / NaN / NaT -> NULL
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and np.isnan(v):
        return None
    return v


rows = [tuple(py(v) for v in r) for r in stage.astype(object).itertuples(index=False, name=None)]
stage_sdf = spark.createDataFrame(rows, SCHEMA.replace("\n", " "))
stage_sdf.createOrReplaceTempView("report_card_stage")

MERGE_SQL = f"""MERGE INTO {TABLE} t USING report_card_stage s
  ON t.date = s.date AND t.source = s.source
  WHEN MATCHED THEN UPDATE SET *
  WHEN NOT MATCHED THEN INSERT *"""
spark.sql(MERGE_SQL)
# Backtest rows outside the current champion's out-of-sample window would be in-sample: drop them.
bt_dates_sql = ", ".join(f"DATE '{d}'" for d in sorted(bt_df["date"]))
spark.sql(f"DELETE FROM {TABLE} WHERE source = 'backtest' AND date NOT IN ({bt_dates_sql})")
count_after_1 = spark.table(TABLE).count()
spark.sql(MERGE_SQL)                                   # idempotency proof: a second merge changes nothing
count_after_2 = spark.table(TABLE).count()

# COMMAND ----------

# MAGIC %md ## 7 · Validation (read back from the table)

# COMMAND ----------

back = spark.table(TABLE).toPandas()
bb, lb = back[back["source"] == "backtest"], back[back["source"] == "live"]


def chk(value, ok):
    return {"value": value if not isinstance(value, float) else round(value, 4), "pass": bool(ok)}


def in_range(s, lo, hi):
    s = s.dropna()
    return bool(((s >= lo) & (s <= hi)).all())


rng = lambda s: f"{s.min():.3f}..{s.max():.3f}" if s.notna().any() else "all null"
checks = {
    "backtest_days_80_95": chk(len(bb), 80 <= len(bb) <= 95),
    "backtest_matches_stage": chk(len(bb), len(bb) == len(bt_df)),
    "backtest_full_days": chk(rng(bb["n_hours"].astype(float)), bb["n_hours"].between(23, 25).all()),
    "live_rows_match_expected": chk({"live_rows": len(lb), "expected_dates": len(set(live_expected_dates))},
                                    set(lb["date"]) >= set(live_expected_dates)),
    "unique_date_source": chk(len(back), len(back) == len(back[["date", "source"]].drop_duplicates())),
    "source_values": chk(sorted(back["source"].unique().tolist()), set(back["source"]) <= {"live", "backtest"}),
    "idempotent_merge": chk({"after_1": count_after_1, "after_2": count_after_2}, count_after_1 == count_after_2),
    "mape_0_100_nonnull": chk(rng(back["mape"]), back["mape"].notna().all() and in_range(back["mape"], 0, 100)),
    "wmape_0_100": chk(rng(back["wmape"]), in_range(back["wmape"], 0, 100)),
    "band_coverage_0_100": chk(rng(back["band_coverage"]), in_range(back["band_coverage"], 0, 100)),
    "demand_mape_0_100": chk(rng(back["demand_mape"]), in_range(back["demand_mape"], 0, 100)),
    "recall_precision_0_1": chk(f"recall {rng(back['spike_recall'])}, precision {rng(back['spike_precision'])}",
                                in_range(back["spike_recall"], 0, 1) and in_range(back["spike_precision"], 0, 1)),
    "caught_le_actual": chk(int((back["spike_hours_caught"] > back["spike_hours_actual"]).sum()),
                            (back["spike_hours_caught"] <= back["spike_hours_actual"]).all()),
    "recall_null_iff_no_spike": chk("ok", ((back["spike_hours_actual"] == 0) == back["spike_recall"].isna()).all()),
    "n_hours_1_25": chk(rng(back["n_hours"].astype(float)), back["n_hours"].between(1, 25).all()),
    # Pooled backtest must reproduce what 04_train logged for the champions (same window minus partial days).
    "backtest_mape_matches_registered": chk({"pooled": round(pooled["mape"], 3), "registered": registered["a_test_mape"]},
                                            registered["a_test_mape"] is None
                                            or abs(pooled["mape"] - registered["a_test_mape"]) <= 1.5),
    "backtest_coverage_matches_registered": chk({"pooled": round(pooled["band_coverage"], 2),
                                                 "registered": registered["a_test_coverage"]},
                                                registered["a_test_coverage"] is None
                                                or abs(pooled["band_coverage"] - registered["a_test_coverage"]) <= 3.0),
    "backtest_demand_mape_lt_5": chk(round(pooled["demand_mape"], 3), pooled["demand_mape"] < 5),
}
failed = [k for k, v in checks.items() if not v["pass"]]

display(back.sort_values(["source", "date"]))
summary = {
    **checks,
    "all_pass": not failed,
    "failed": failed,
    "table": TABLE,
    "rows": {"backtest": len(bb), "live": len(lb)},
    "backtest_window": {"test_start_excl": str(TEST_START), "anchor_ts": str(anchor_ts),
                        "first_date": str(bb["date"].min()), "last_date": str(bb["date"].max())},
    "pooled_backtest": {k: round(v, 4) for k, v in pooled.items()},
    "registered": registered,
    "backtest_daily_mean": {c: round(float(bb[c].mean()), 4) for c in ["mape", "wmape", "band_coverage", "demand_mape",
                                                                        "spike_recall", "spike_precision"]},
    "backtest_spike_hours": {"actual": int(bb["spike_hours_actual"].sum()), "caught": int(bb["spike_hours_caught"].sum())},
    "worst_backtest_days": bb.nlargest(3, "mape")[["date", "mape"]].astype(str).to_dict("records"),
    "models": {"net_load": ver_A, "spike": ver_B, "demand": ver_D, "spike_threshold": round(thr_B, 4)},
}
print(json.dumps(summary, indent=1, default=str))
assert not failed, f"failed checks: {failed}"

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary, default=str))
