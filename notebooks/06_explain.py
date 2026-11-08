# Databricks notebook source
# MAGIC %md
# MAGIC # 06 · Explain (Phase 3.5, SHAP drivers)
# MAGIC For the **latest `run_ts` in `grid.gold.forecasts`**, writes the top 3 drivers of each hour's net-load forecast
# MAGIC to `grid.gold.forecast_drivers` (48 × 3 rows). Re-running deletes that `run_ts` batch first, so it is idempotent.
# MAGIC
# MAGIC **Which model is explained: the one `strain_source` says was used, row by row.**
# MAGIC * `strain_source = 'demand_minus_ercot_renewables'` (all 48 h when ERCOT forecasts exist):
# MAGIC   `net_load_used = demand_p50 − wind_fcst − solar_fcst`. Model D's P50 LightGBM booster
# MAGIC   (`grid.ml.demand`, the version stored in `gold.forecasts.model_d_version`) is explained with
# MAGIC   `shap.TreeExplainer`. ERCOT's wind and solar forecasts enter net load **linearly with weight −1**, so their exact
# MAGIC   contribution relative to a baseline is `−(forecast − mean)`. The baseline means are actual wind/solar over the same
# MAGIC   rows Model D's final booster was fit on (`ts_utc ≤ test_start_excl` of the model's MLflow run), which is the same
# MAGIC   data the TreeExplainer's `expected_value` comes from. This gives an exact additive split:
# MAGIC   `net_load_used = base_mw + Σ demand SHAP + wind term + solar term`, with
# MAGIC   `base_mw = E[demand] − E[wind] − E[solar]` (a typical hour).
# MAGIC * `strain_source = 'model_a'`: Model A's P50 booster (`grid.ml.net_load`, `model_a_version`) is explained the
# MAGIC   same way, and `net_load_used = base_mw + Σ SHAP`.
# MAGIC
# MAGIC **Grouping:** cyclic encodings are summed with their raw column so one concept cannot take two of the three slots:
# MAGIC `time_of_day` = `hour + hour_sin + hour_cos` (value = local hour) and `season` = `doy + doy_sin + doy_cos + month`
# MAGIC (value = local day of year). SHAP values are additive, so the sum is exact.
# MAGIC
# MAGIC | column | meaning |
# MAGIC |---|---|
# MAGIC | `run_ts`, `target_ts`, `horizon_h` | forecast batch and hour (UTC) |
# MAGIC | `rank` | 1..3 by `abs(shap_mw)` |
# MAGIC | `feature`, `feature_label` | model column (or group / ERCOT pseudo-feature) and a readable label |
# MAGIC | `feature_value` | the input value for that hour (°F, MW, %, local hour, ...) |
# MAGIC | `shap_mw` | signed contribution to `net_load_used`, MW, relative to `base_mw` |
# MAGIC | `direction` | `'raises'` if `shap_mw > 0`, else `'lowers'` |
# MAGIC | `driver_source` | `model_d_shap`, `model_a_shap` or `ercot_forecast` |
# MAGIC | `strain_source`, `model_name`, `model_version`, `base_mw`, `net_load_used`, `created_at` | lineage |
# MAGIC
# MAGIC SHAP is computed with `shap.TreeExplainer` and cross-checked against LightGBM's native TreeSHAP
# MAGIC (`pred_contrib=True`); if `shap` cannot be imported the native values are used (`shap_method` in the exit JSON).

# COMMAND ----------

# MAGIC %pip install -q lightgbm==4.5.0 shap==0.46.0 "mlflow>=2.21.3"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import json
import os

os.environ["MLFLOW_USE_DATABRICKS_SDK_MODEL_ARTIFACTS_REPO_FOR_UC"] = "true"   # same UC artifact route as 04/05
import tempfile
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
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
NAME_D = f"{catalog}.ml.demand"
FCST = f"{catalog}.gold.forecasts"
TABLE = f"{catalog}.gold.forecast_drivers"
SRC_ALT, SRC_A = "demand_minus_ercot_renewables", "model_a"
TOP_K = 3

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
DEMAND_EXTRA = ["demand_lag_72h", "demand_lag_336h", "demand_roll24_mean_l48", "demand_roll168_mean_l48",
                "demand_roll168_max_l48"]
FEATURES_D = FEATURES_A + DEMAND_EXTRA

# Groups: member columns are summed; feature_value comes from the value column.
GROUPS = {"time_of_day": (["hour", "hour_sin", "hour_cos"], "hour"),
          "season": (["doy", "doy_sin", "doy_cos", "month"], "doy")}
ERCOT_PSEUDO = {"ercot_wind_forecast": "wind_fcst_mw", "ercot_solar_forecast": "solar_fcst_mw"}

LABELS = {
    "time_of_day": "Time of day (local hour)",
    "season": "Season (local day of year)",
    "dow": "Day of week",
    "is_weekend": "Weekend",
    "is_holiday": "Holiday",
    "temp_f": "Texas temperature (population-weighted)",
    "heat_index_f": "Texas heat index",
    "rh_pct": "Texas humidity",
    "wind_mph": "Texas wind speed",
    "cloud_pct": "Texas cloud cover",
    "ghi_wm2": "Texas sunlight (irradiance)",
    "temp_f_hou": "Houston temperature",
    "temp_f_dfw": "DFW temperature",
    "temp_f_aus": "Austin temperature",
    "temp_f_sat": "San Antonio temperature",
    "cdd": "Cooling degrees (above 65°F)",
    "hdd": "Heating degrees (below 65°F)",
    "temp_f_roll24_mean": "Texas temperature, 24 h average",
    "nl_lag_48h": "Net load 2 days earlier",
    "nl_lag_72h": "Net load 3 days earlier",
    "nl_lag_168h": "Net load 1 week earlier",
    "nl_lag_336h": "Net load 2 weeks earlier",
    "demand_lag_48h": "Demand 2 days earlier",
    "demand_lag_72h": "Demand 3 days earlier",
    "demand_lag_168h": "Demand 1 week earlier",
    "demand_lag_336h": "Demand 2 weeks earlier",
    "wind_lag_48h": "Wind output 2 days earlier",
    "wind_lag_168h": "Wind output 1 week earlier",
    "solar_lag_48h": "Solar output 2 days earlier",
    "solar_lag_168h": "Solar output 1 week earlier",
    "nl_roll24_mean_l48": "Net load, 24 h average (2+ days ago)",
    "nl_roll168_mean_l48": "Net load, 7-day average (2+ days ago)",
    "nl_roll168_max_l48": "Net load, 7-day peak (2+ days ago)",
    "demand_roll24_mean_l48": "Demand, 24 h average (2+ days ago)",
    "demand_roll168_mean_l48": "Demand, 7-day average (2+ days ago)",
    "demand_roll168_max_l48": "Demand, 7-day peak (2+ days ago)",
    "ercot_wind_forecast": "ERCOT wind forecast",
    "ercot_solar_forecast": "ERCOT solar forecast",
}
grouped_members = {c for m, _ in GROUPS.values() for c in m}
_all_drivers = set(GROUPS) | set(ERCOT_PSEUDO) | (set(FEATURES_D) - grouped_members)
assert _all_drivers <= set(LABELS), f"missing labels: {sorted(_all_drivers - set(LABELS))}"

# COMMAND ----------

# MAGIC %md ## 1 · Latest forecast batch and its inputs

# COMMAND ----------

run_ts = spark.sql(f"SELECT max(run_ts) r FROM {FCST}").first()["r"]
assert run_ts is not None, f"{FCST} is empty; run 05_predict first"
run_ts = pd.Timestamp(run_ts)
run_ts_sql = run_ts.strftime("%Y-%m-%d %H:%M:%S")

fc = spark.sql(f"""SELECT target_ts, horizon_h, strain_source, net_load_used, net_load_p50, demand_p50,
                          wind_fcst_mw, solar_fcst_mw, model_a_version, model_d_version
                   FROM {FCST} WHERE run_ts = TIMESTAMP '{run_ts_sql}'""").toPandas()
fc["target_ts"] = pd.to_datetime(fc["target_ts"])
fc = fc.sort_values("target_ts").reset_index(drop=True)
assert len(fc) == 48 and fc["target_ts"].nunique() == 48, f"forecast batch has {len(fc)} rows"
ver_A, ver_D = str(fc["model_a_version"].iloc[0]), str(fc["model_d_version"].iloc[0])
assert fc["model_a_version"].nunique() == 1 and fc["model_d_version"].nunique() == 1

# Inputs: the Gold forecast rows of that same anchor (the rows 05_predict scored).
feat = (spark.table(f"{catalog}.gold.features")
        .where(f"is_forecast_row AND anchor_ts = TIMESTAMP '{run_ts_sql}'")
        .select("ts_utc", *FEATURES_D).toPandas())
feat["ts_utc"] = pd.to_datetime(feat["ts_utc"])
X_all = fc[["target_ts"]].merge(feat, left_on="target_ts", right_on="ts_utc", how="left")
assert X_all["ts_utc"].notna().all(), ("gold.features no longer holds the forecast rows of run_ts "
                                       f"{run_ts}; re-run 05_predict for the current anchor first")
X_D = X_all[FEATURES_D].astype("float64").reset_index(drop=True)
X_A = X_all[FEATURES_A].astype("float64").reset_index(drop=True)
print(f"run_ts {run_ts} | sources {fc['strain_source'].value_counts().to_dict()} | "
      f"Model A v{ver_A}, Model D v{ver_D}")

# COMMAND ----------

# MAGIC %md ## 2 · Load the exact model versions used and compute SHAP

# COMMAND ----------


def load_booster(name, version):
    """P50 LGBMRegressor inside the NetLoadQuantileModel pyfunc, plus the MLflow run that trained it."""
    pm = mlflow.pyfunc.load_model(f"models:/{name}/{version}")
    inner = pm.unwrap_python_model()
    mv = client.get_model_version(name, version)
    return inner.models["p50"], inner.features, mv.run_id


booster_D, feats_D_model, run_id_D = load_booster(NAME_D, ver_D)
booster_A, feats_A_model, run_id_A = load_booster(NAME_A, ver_A)
assert list(feats_D_model) == FEATURES_D, "Model D feature order differs from FEATURES_D"
assert list(feats_A_model) == FEATURES_A, "Model A feature order differs from FEATURES_A"

try:
    import shap
    shap_method = f"shap.TreeExplainer {shap.__version__}"
except Exception as e:   # native TreeSHAP gives identical values
    shap, shap_method = None, f"lightgbm pred_contrib (shap import failed: {str(e)[:120]})"


def tree_shap(model, X):
    """Returns (shap matrix n×p, expected value, prediction, max |shap - native contrib|)."""
    native = model.booster_.predict(X, pred_contrib=True)   # last column = expected value
    pred = model.booster_.predict(X)
    if shap is None:
        return native[:, :-1], float(native[0, -1]), pred, None
    global shap_method
    try:
        ex = shap.TreeExplainer(model)
        sv = np.asarray(ex.shap_values(X))
        ev = float(np.ravel(ex.expected_value)[0])
    except Exception as e:   # fall back to the identical native TreeSHAP rather than lose the run
        shap_method += f" -> native fallback ({str(e)[:120]})"
        return native[:, :-1], float(native[0, -1]), pred, None
    return sv, ev, pred, float(np.abs(sv - native[:, :-1]).max())


sv_D, ev_D, pred_D, diff_native_D = tree_shap(booster_D, X_D)
sv_A, ev_A, pred_A, diff_native_A = tree_shap(booster_A, X_A)
additivity_D = float(np.abs(ev_D + sv_D.sum(1) - pred_D).max())
additivity_A = float(np.abs(ev_A + sv_A.sum(1) - pred_A).max())
print(f"{shap_method} | E[demand] {ev_D:,.0f} MW, E[net load A] {ev_A:,.0f} MW | additivity max err "
      f"D {additivity_D:.4f} / A {additivity_A:.4f} MW | vs native D {diff_native_D} A {diff_native_A}")

# Renewables baseline: actual wind/solar means over the rows Model D's final booster was fit on.
test_start = client.get_run(run_id_D).data.params["test_start_excl"]
base_ren = spark.sql(f"""SELECT avg(wind_mw) w, avg(solar_mw) s, count(*) n FROM {catalog}.silver.grid_hourly
                         WHERE NOT is_forecast_row AND ts_utc <= TIMESTAMP '{pd.Timestamp(test_start):%Y-%m-%d %H:%M:%S}'
                           AND demand_mw IS NOT NULL AND wind_mw IS NOT NULL AND solar_mw IS NOT NULL""").first()
mean_wind, mean_solar = float(base_ren["w"]), float(base_ren["s"])
print(f"renewables baseline (ts <= {test_start}, n={base_ren['n']}): wind {mean_wind:,.0f} MW, solar {mean_solar:,.0f} MW")

# COMMAND ----------

# MAGIC %md ## 3 · Contributions per hour → top 3

# COMMAND ----------


def contributions(sv_row, x_row, features):
    """dict driver -> (feature_value, shap_mw) with cyclic encodings grouped."""
    s = dict(zip(features, sv_row))
    out = {}
    for g, (members, vcol) in GROUPS.items():
        out[g] = (float(x_row[vcol]), float(sum(s.pop(m) for m in members if m in s)))
    for f, v in s.items():
        out[f] = (float(x_row[f]) if pd.notna(x_row[f]) else None, float(v))
    return out


created_at = datetime.now(timezone.utc).replace(tzinfo=None)
rows, recon_err, all_contrib = [], [], []
for i, r in fc.iterrows():
    if r["strain_source"] == SRC_ALT:
        c = contributions(sv_D[i], X_D.iloc[i], FEATURES_D)
        for pseudo, col in ERCOT_PSEUDO.items():
            mean = mean_wind if col == "wind_fcst_mw" else mean_solar
            c[pseudo] = (float(r[col]), -(float(r[col]) - mean))
        base = ev_D - mean_wind - mean_solar
        src_of = lambda d: "ercot_forecast" if d in ERCOT_PSEUDO else "model_d_shap"
        model_name, model_version = NAME_D, ver_D
    else:
        c = contributions(sv_A[i], X_A.iloc[i], FEATURES_A)
        base = ev_A
        src_of = lambda d: "model_a_shap"
        model_name, model_version = NAME_A, ver_A
    recon_err.append(abs(base + sum(v for _, v in c.values()) - float(r["net_load_used"])))
    all_contrib.append({d: v for d, (_, v) in c.items()})
    top = sorted(c.items(), key=lambda kv: -abs(kv[1][1]))[:TOP_K]
    for rank, (d, (val, mw)) in enumerate(top, start=1):
        rows.append({
            "run_ts": run_ts, "target_ts": r["target_ts"], "horizon_h": int(r["horizon_h"]), "rank": rank,
            "feature": d, "feature_label": LABELS.get(d), "feature_value": val, "shap_mw": mw,
            "direction": "raises" if mw > 0 else "lowers", "driver_source": src_of(d),
            "strain_source": r["strain_source"], "model_name": model_name, "model_version": model_version,
            "base_mw": float(base), "net_load_used": float(r["net_load_used"]), "created_at": created_at,
        })

drv = pd.DataFrame(rows)
contrib_df = pd.DataFrame(all_contrib).fillna(0.0)
print(f"reconstruction |base + Σ contributions − net_load_used|: max {max(recon_err):.3f} MW")
print(drv[["target_ts", "rank", "feature_label", "feature_value", "shap_mw", "direction"]]
      .assign(shap_mw=lambda d: d["shap_mw"].round(0), feature_value=lambda d: pd.to_numeric(d["feature_value"]).round(1))
      .head(24).to_string())
display(drv)

# COMMAND ----------

# MAGIC %md ## 4 · Write: delete this `run_ts` batch, then append

# COMMAND ----------

SCHEMA = """run_ts TIMESTAMP, target_ts TIMESTAMP, horizon_h INT, `rank` INT, feature STRING, feature_label STRING,
  feature_value DOUBLE, shap_mw DOUBLE, direction STRING, driver_source STRING, strain_source STRING,
  model_name STRING, model_version STRING, base_mw DOUBLE, net_load_used DOUBLE, created_at TIMESTAMP"""
COLS = ["run_ts", "target_ts", "horizon_h", "rank", "feature", "feature_label", "feature_value", "shap_mw",
        "direction", "driver_source", "strain_source", "model_name", "model_version", "base_mw", "net_load_used",
        "created_at"]
spark.sql(f"CREATE TABLE IF NOT EXISTS {TABLE} ({SCHEMA}) USING DELTA "
          f"COMMENT 'GridWise top-3 SHAP drivers per forecast hour, one batch per run_ts; written by notebooks/06_explain'")


def py(v):
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.generic):
        v = v.item()
    return None if (isinstance(v, float) and np.isnan(v)) else v


sdf = spark.createDataFrame([tuple(py(v) for v in r) for r in drv[COLS].itertuples(index=False, name=None)],
                            SCHEMA.replace("\n", " "))
spark.sql(f"DELETE FROM {TABLE} WHERE run_ts = TIMESTAMP '{run_ts_sql}'")
sdf.write.mode("append").saveAsTable(TABLE)

# COMMAND ----------

# MAGIC %md ## 5 · SHAP summary plot (displayed, and logged to an MLflow run in the `gridwise` experiment)

# COMMAND ----------

png_dir = tempfile.mkdtemp()
png_paths, plot_errors = [], []

# (a) What moves the 48 forecast hours: mean |contribution| per driver, including ERCOT terms.
try:
    imp = contrib_df.abs().mean().sort_values().tail(15)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh([LABELS.get(k, k) for k in imp.index], imp.values / 1000.0, color="#3b6ea5")
    ax.set_xlabel("mean |contribution| to net load used, GW")
    ax.set_title(f"Forecast drivers, run {run_ts:%Y-%m-%d %H:%MZ} (48 h)")
    p = os.path.join(png_dir, "forecast_drivers_bar.png")
    fig.savefig(p, dpi=120, bbox_inches="tight")
    display(fig)
    plt.close(fig)
    png_paths.append(p)
except Exception as e:
    plot_errors.append(f"bar: {str(e)[:200]}")

# (b) SHAP beeswarm of the demand model on the 48 forecast rows (readable labels).
try:
    if shap is None:
        raise RuntimeError("shap not importable")
    shap.summary_plot(sv_D, X_D.rename(columns=lambda c: LABELS.get(c, c)), show=False, max_display=15)
    fig = plt.gcf()
    fig.suptitle(f"Model D (demand P50 v{ver_D}) SHAP, forecast rows of run {run_ts:%Y-%m-%d %H:%MZ}", y=1.02)
    p = os.path.join(png_dir, "shap_summary_demand.png")
    fig.savefig(p, dpi=120, bbox_inches="tight")
    display(fig)
    plt.close(fig)
    png_paths.append(p)
except Exception as e:
    plot_errors.append(f"beeswarm: {str(e)[:200]}")

mlflow_run_id, mlflow_error = None, None
try:
    current_user = spark.sql("select current_user()").first()[0]
    try:
        mlflow.set_experiment(f"/Users/{current_user}/gridwise")
    except Exception:
        mlflow.set_experiment(f"/Users/{current_user}/gridwise/gridwise_experiment")
    with mlflow.start_run(run_name=f"explain_{run_ts:%Y%m%dT%H}") as mr:
        mlflow.log_params({"run_ts": str(run_ts), "model_d_version": ver_D, "model_a_version": ver_A,
                           "shap_method": shap_method[:250], "renewables_baseline_end": str(test_start)})
        mlflow.log_metrics({"additivity_max_err_mw_d": additivity_D, "reconstruction_max_err_mw": max(recon_err),
                            "base_mw_alt": ev_D - mean_wind - mean_solar})
        for p in png_paths:
            mlflow.log_artifact(p, artifact_path="plots")
        csv = os.path.join(png_dir, "forecast_drivers.csv")
        drv.to_csv(csv, index=False)
        mlflow.log_artifact(csv)
        mlflow_run_id = mr.info.run_id
except Exception as e:
    mlflow_error = str(e)[:300]
    print("MLflow logging failed (plots still displayed):", mlflow_error)

# COMMAND ----------

# MAGIC %md ## 6 · Validation (read back from the table)

# COMMAND ----------

back = spark.sql(f"SELECT * FROM {TABLE} WHERE run_ts = TIMESTAMP '{run_ts_sql}'").toPandas()
back["target_ts"] = pd.to_datetime(back["target_ts"])
per_ts = back.groupby("target_ts")
ranks_ok = per_ts["rank"].apply(lambda s: sorted(s.tolist()) == [1, 2, 3]).all()
order_ok = (back.sort_values(["target_ts", "rank"]).assign(a=lambda d: d["shap_mw"].abs())
            .groupby("target_ts")["a"].apply(lambda s: s.is_monotonic_decreasing).all())
expected_src = np.where(back["strain_source"] == SRC_ALT, NAME_D, NAME_A)
n_recon_bad = int((np.array(recon_err) > 1.0).sum())


def chk(value, ok):
    return {"value": value if not isinstance(value, float) else round(value, 4), "pass": bool(ok)}


checks = {
    "rows_144": chk(len(back), len(back) == 48 * TOP_K),
    "distinct_target_ts_48": chk(int(back["target_ts"].nunique()), back["target_ts"].nunique() == 48),
    "target_ts_match_forecasts": chk("set equal", set(back["target_ts"]) == set(fc["target_ts"])),
    "ranks_1_2_3_per_hour": chk("1,2,3", ranks_ok),
    "ranked_by_abs_shap": chk("|r1|>=|r2|>=|r3|", order_ok),
    "labels_non_null": chk(int(back["feature_label"].isna().sum()),
                           back["feature_label"].notna().all() and (back["feature_label"].str.len() > 0).all()),
    "no_null_feature_shap": chk(int(back[["feature", "shap_mw"]].isna().sum().sum()),
                                back[["feature", "shap_mw"]].notna().all().all()),
    "direction_matches_sign": chk("raises<=>shap>0", ((back["direction"] == "raises") == (back["shap_mw"] > 0)).all()
                                  and back["direction"].isin(["raises", "lowers"]).all()),
    "model_matches_strain_source": chk(back["model_name"].value_counts().to_dict(),
                                       (back["model_name"].values == expected_src).all()),
    "shap_additivity_model": chk(max(additivity_D, additivity_A), max(additivity_D, additivity_A) < 1.0),
    "reconstructs_net_load_used": chk({"max_err_mw": round(max(recon_err), 3), "hours_over_1mw": n_recon_bad},
                                      n_recon_bad <= 2),
    "shap_matches_native_treeshap": chk(max(d for d in [diff_native_D, diff_native_A, 0.0] if d is not None),
                                        all(d is None or d < 1.0 for d in [diff_native_D, diff_native_A])),
    "summary_png_saved": chk(len(png_paths), len(png_paths) >= 1),
    "single_batch_per_run_ts": chk(int(spark.sql(f"SELECT count(*) c FROM {TABLE} WHERE run_ts = TIMESTAMP "
                                                 f"'{run_ts_sql}'").first()["c"]), True),
}
checks["single_batch_per_run_ts"]["pass"] = checks["single_batch_per_run_ts"]["value"] == 48 * TOP_K
failed = [k for k, v in checks.items() if not v["pass"]]

top1 = back[back["rank"] == 1]
first = back[back["target_ts"] == back["target_ts"].min()].sort_values("rank")
summary = {
    **checks,
    "all_pass": not failed,
    "failed": failed,
    "run_ts": str(run_ts),
    "table": TABLE,
    "shap_method": shap_method,
    "models": {"demand": ver_D, "net_load": ver_A},
    "base_mw_alt": round(ev_D - mean_wind - mean_solar, 0),
    "renewables_baseline": {"wind_mw": round(mean_wind, 0), "solar_mw": round(mean_solar, 0), "end": str(test_start)},
    "top1_feature_counts": top1["feature"].value_counts().to_dict(),
    "all_rank_feature_counts": back["feature"].value_counts().to_dict(),
    "first_hour": [{k: (round(float(x[k]), 1) if isinstance(x[k], (float, np.floating)) else str(x[k]))
                    for k in ["target_ts", "rank", "feature_label", "feature_value", "shap_mw", "direction"]}
                   for _, x in first.iterrows()],
    "mlflow_run_id": mlflow_run_id,
    "mlflow_error": mlflow_error,
    "plot_errors": plot_errors,
}
print(json.dumps(summary, indent=1, default=str))
assert not failed, f"failed checks: {failed}"

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary, default=str))
