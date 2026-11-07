# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Train (Phase 3.1–3.4)
# MAGIC Trains the two GridWise models on `grid.gold.features` and registers them in Unity Catalog.
# MAGIC
# MAGIC | model | what | registry |
# MAGIC |---|---|---|
# MAGIC | **A** | LightGBM quantile net-load forecast, 1–48 h ahead, outputs `net_load_p10/p50/p90` | `grid.ml.net_load` |
# MAGIC | **B** | LightGBM spike classifier (`is_unbalance=True`), outputs `spike_prob` | `grid.ml.spike` |
# MAGIC
# MAGIC **Leakage design (contract §2.1):** one direct model for every horizon. Features are calendar and weather at the
# MAGIC target hour plus autoregressive lags ≥ 48 h and rolling windows ending at t−48. No `diag_*` lags, no ERCOT
# MAGIC wind/solar forecasts, no `demand_forecast_mw`. Training uses archive weather and inference uses forecast weather
# MAGIC (documented optimism).
# MAGIC
# MAGIC **Split (UTC, contract §3):** train `< 2025-07-01` · validate `2025-07-01 … 2025-09-30` · test `> anchor_ts − 92 days`.
# MAGIC Early stopping and threshold selection use validation only. The final model is refit on everything before the
# MAGIC test window using `best_iteration` from validation, then scored once on test.

# COMMAND ----------

# MAGIC %pip install -q lightgbm==4.5.0 shap==0.46.0 "mlflow>=2.21.3"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import json
import os

# Free Edition serverless denies direct S3 PutObject into UC model storage (explicit deny on the STS role).
# Route UC model-version uploads through Databricks presigned URLs instead (mlflow >= 2.21).
os.environ["MLFLOW_USE_DATABRICKS_SDK_MODEL_ARTIFACTS_REPO_FOR_UC"] = "true"
import tempfile
from datetime import datetime, timezone

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
from mlflow.models import infer_signature
from mlflow.tracking import MlflowClient
from sklearn.metrics import (average_precision_score, f1_score, precision_recall_curve,
                             precision_score, recall_score, roc_auc_score)

dbutils.widgets.text("catalog", "grid")
catalog = dbutils.widgets.get("catalog")
spark.conf.set("spark.sql.session.timeZone", "UTC")

SEED = 42
TRAIN_END = pd.Timestamp("2025-07-01")   # train: ts_utc < TRAIN_END
VAL_END = pd.Timestamp("2025-10-01")     # val:   TRAIN_END <= ts_utc < VAL_END
TEST_DAYS = 92                           # test:  ts_utc > anchor_ts - 92 days
SPIKE_USD = 100.0
NAME_A = f"{catalog}.ml.net_load"
NAME_B = f"{catalog}.ml.spike"

# Contract §3: calendar + weather-at-t + AR lags >= 48h + AR rolling _l48. No price columns in A.
FEATURES_A = [
    # calendar (local)
    "hour", "dow", "month", "doy", "is_weekend", "is_holiday",
    "hour_sin", "hour_cos", "doy_sin", "doy_cos",
    # weather at t (known ahead)
    "temp_f", "heat_index_f", "rh_pct", "wind_mph", "cloud_pct", "ghi_wm2",
    "temp_f_hou", "temp_f_dfw", "temp_f_aus", "temp_f_sat",
    "cdd", "hdd", "temp_f_roll24_mean",
    # AR lags >= 48h
    "nl_lag_48h", "nl_lag_72h", "nl_lag_168h", "nl_lag_336h",
    "demand_lag_48h", "demand_lag_168h", "wind_lag_48h", "wind_lag_168h",
    "solar_lag_48h", "solar_lag_168h",
    # AR rolling windows ending at t-48
    "nl_roll24_mean_l48", "nl_roll168_mean_l48", "nl_roll168_max_l48",
]
PRICE_FEATURES = ["price_lag_48h", "price_lag_168h", "price_roll168_mean_l48",
                  "price_roll168_max_l48", "spike_count_168_l48"]
FEATURES_B = FEATURES_A + PRICE_FEATURES + ["net_load_p50"]

BANNED = {"diag_nl_lag_1h", "diag_nl_lag_24h", "wind_forecast_mw", "solar_forecast_mw", "demand_forecast_mw"}
assert not BANNED & set(FEATURES_B), "banned feature in model inputs"

# COMMAND ----------

# MAGIC %md ## 1 · Load features and split

# COMMAND ----------

feat_sdf = spark.table(f"{catalog}.gold.features")
missing = sorted(set(FEATURES_A + PRICE_FEATURES + ["ts_utc", "y_net_load_mw", "y_is_spike", "y_price_usd_mwh",
                                                     "is_forecast_row", "anchor_ts"]) - set(feat_sdf.columns))
assert not missing, f"gold.features is missing contract columns: {missing}"

pdf = feat_sdf.toPandas()
pdf["ts_utc"] = pd.to_datetime(pdf["ts_utc"])
anchor_ts = pd.to_datetime(pdf["anchor_ts"].iloc[0])
TEST_START = anchor_ts - pd.Timedelta(days=TEST_DAYS)   # test: ts_utc > TEST_START

hist = pdf[~pdf["is_forecast_row"].astype(bool)].sort_values("ts_utc").reset_index(drop=True)
fcst = pdf[pdf["is_forecast_row"].astype(bool)].sort_values("ts_utc").reset_index(drop=True)


def to_X(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """All model inputs are float64 (NaN = missing); the registered signatures expect doubles."""
    return df[cols].astype("float64")


def split_masks(df: pd.DataFrame):
    ts = df["ts_utc"]
    return {
        "train": ts < TRAIN_END,
        "val": (ts >= TRAIN_END) & (ts < VAL_END),
        "pretest": ts <= TEST_START,   # final refit = train + val + gap months
        "test": ts > TEST_START,
    }


dA = hist[hist["y_net_load_mw"].notna()].reset_index(drop=True)
mA = split_masks(dA)
split_sizes = {k: int(v.sum()) for k, v in mA.items()}
print("anchor_ts:", anchor_ts, "| test starts after:", TEST_START, "| Model A rows:", split_sizes)
assert VAL_END <= TEST_START, "validation window overlaps the test window"
assert min(split_sizes.values()) > 500, f"split too small: {split_sizes}"

# COMMAND ----------

# MAGIC %md ## 2 · Metrics and the seasonal-naive baseline (same hour last week)

# COMMAND ----------


def mape(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    ok = ~(np.isnan(y) | np.isnan(p)) & (np.abs(y) > 1e-6)
    return float(np.mean(np.abs(y[ok] - p[ok]) / np.abs(y[ok])) * 100)


def wmape(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    ok = ~(np.isnan(y) | np.isnan(p))
    return float(np.sum(np.abs(y[ok] - p[ok])) / np.sum(np.abs(y[ok])) * 100)


def rmse(y, p):
    return float(np.sqrt(np.mean((np.asarray(y, float) - np.asarray(p, float)) ** 2)))


test_A = dA[mA["test"]]
val_A = dA[mA["val"]]
baseline_test_mape = mape(test_A["y_net_load_mw"], test_A["nl_lag_168h"])
baseline_val_mape = mape(val_A["y_net_load_mw"], val_A["nl_lag_168h"])
print(f"Seasonal-naive (nl_lag_168h) MAPE  val {baseline_val_mape:.2f}%  test {baseline_test_mape:.2f}%")

# COMMAND ----------

# MAGIC %md ## 3 · Model A: LightGBM quantile P10 / P50 / P90

# COMMAND ----------

PARAMS_A = dict(n_estimators=3000, learning_rate=0.05, num_leaves=63, min_child_samples=40,
                subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                random_state=SEED, n_jobs=-1, verbose=-1)
QUANTILES = {"p10": 0.1, "p50": 0.5, "p90": 0.9}

X_tr, y_tr = to_X(dA[mA["train"]], FEATURES_A), dA.loc[mA["train"], "y_net_load_mw"]
X_va, y_va = to_X(val_A, FEATURES_A), val_A["y_net_load_mw"]
X_pt, y_pt = to_X(dA[mA["pretest"]], FEATURES_A), dA.loc[mA["pretest"], "y_net_load_mw"]
X_te, y_te = to_X(test_A, FEATURES_A), test_A["y_net_load_mw"]

best_iter_A, val_models_A, final_models_A = {}, {}, {}
for q, alpha in QUANTILES.items():
    m = lgb.LGBMRegressor(objective="quantile", alpha=alpha, **PARAMS_A)
    m.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], eval_metric="quantile",
          callbacks=[lgb.early_stopping(100, first_metric_only=True, verbose=False)])
    best_iter_A[q] = int(m.best_iteration_ or PARAMS_A["n_estimators"])
    val_models_A[q] = m
    # Final champion fit: all rows before the test window, fixed best_iteration from validation.
    final = lgb.LGBMRegressor(objective="quantile", alpha=alpha, **{**PARAMS_A, "n_estimators": best_iter_A[q]})
    final.fit(X_pt, y_pt)
    final_models_A[q] = final
print("best_iteration:", best_iter_A)


class NetLoadQuantileModel(mlflow.pyfunc.PythonModel):
    """Three LightGBM quantile boosters in one pyfunc. Output: net_load_p10, net_load_p50, net_load_p90 (sorted)."""

    def __init__(self, models: dict, features: list):
        self.models = models
        self.features = features

    def predict(self, context, model_input, params=None):
        X = pd.DataFrame(model_input)[self.features].astype("float64")
        raw = np.column_stack([self.models[q].predict(X) for q in ("p10", "p50", "p90")])
        raw.sort(axis=1)   # enforce P10 <= P50 <= P90
        return pd.DataFrame(raw, columns=["net_load_p10", "net_load_p50", "net_load_p90"], index=X.index)


wrap_val_A = NetLoadQuantileModel(val_models_A, FEATURES_A)
wrap_A = NetLoadQuantileModel(final_models_A, FEATURES_A)

pv = wrap_val_A.predict(None, X_va)
pt = wrap_A.predict(None, X_te)
metrics_A = {
    "val_mape": mape(y_va, pv["net_load_p50"]),
    "val_p10_p90_coverage": float(((y_va.values >= pv["net_load_p10"].values) &
                                   (y_va.values <= pv["net_load_p90"].values)).mean() * 100),
    "test_mape": mape(y_te, pt["net_load_p50"]),
    "test_wmape": wmape(y_te, pt["net_load_p50"]),
    "test_rmse": rmse(y_te, pt["net_load_p50"]),
    "test_mae": float(np.mean(np.abs(y_te.values - pt["net_load_p50"].values))),
    "test_p10_p90_coverage": float(((y_te.values >= pt["net_load_p10"].values) &
                                    (y_te.values <= pt["net_load_p90"].values)).mean() * 100),
    "baseline_val_mape": baseline_val_mape,
    "baseline_test_mape": baseline_test_mape,
}
# Context benchmark (contract §3): EIA/ERCOT day-ahead demand forecast MAPE on *demand* (not net load), over the
# test window. gold.features does not carry these columns, so read them from silver.grid_hourly. Context only.
try:
    bench = (spark.table(f"{catalog}.silver.grid_hourly")
             .where("NOT is_forecast_row AND demand_mw IS NOT NULL AND demand_forecast_mw IS NOT NULL")
             .where(f"ts_utc > TIMESTAMP '{TEST_START}'")
             .select("demand_mw", "demand_forecast_mw").toPandas())
    if len(bench):
        metrics_A["benchmark_demand_fcst_test_mape"] = mape(bench["demand_mw"], bench["demand_forecast_mw"])
except Exception as e:
    print("benchmark skipped:", str(e)[:200])

mape_by_month = (test_A.assign(ape=np.abs(y_te.values - pt["net_load_p50"].values) / np.abs(y_te.values) * 100,
                               month=test_A["ts_utc"].dt.strftime("%Y-%m"))
                 .groupby("month")["ape"].mean().round(3).to_dict())
print(json.dumps({k: round(v, 3) for k, v in metrics_A.items()}, indent=1))
print("test MAPE by month:", mape_by_month)

# COMMAND ----------

# MAGIC %md ## 4 · Model B: spike classifier (price > $100/MWh)

# COMMAND ----------

PARAMS_B = dict(n_estimators=2000, learning_rate=0.03, num_leaves=31, min_child_samples=30,
                subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                is_unbalance=True, metric="average_precision",
                random_state=SEED, n_jobs=-1, verbose=-1)

dB = hist[hist["y_is_spike"].notna()].reset_index(drop=True)
mB = split_masks(dB)
yB = dB["y_is_spike"].astype(int)

# net_load_p50 feature: from the train-only Model A for train/val (in-sample on train, documented optimism),
# from the final Model A for the pre-test refit (in-sample) and the test window (out-of-sample).
XB_A = to_X(dB, FEATURES_A)
dB["net_load_p50_valmodel"] = wrap_val_A.predict(None, XB_A)["net_load_p50"].values
dB["net_load_p50_final"] = wrap_A.predict(None, XB_A)["net_load_p50"].values


def xb(mask, src):
    return to_X(dB[mask].assign(net_load_p50=dB.loc[mask, src]), FEATURES_B)


XB_tr, yB_tr = xb(mB["train"], "net_load_p50_valmodel"), yB[mB["train"]]
XB_va, yB_va = xb(mB["val"], "net_load_p50_valmodel"), yB[mB["val"]]
XB_pt, yB_pt = xb(mB["pretest"], "net_load_p50_final"), yB[mB["pretest"]]
XB_te, yB_te = xb(mB["test"], "net_load_p50_final"), yB[mB["test"]]
print("Model B rows:", {k: int(v.sum()) for k, v in mB.items()},
      "| spikes train/val/test:", int(yB_tr.sum()), int(yB_va.sum()), int(yB_te.sum()))

clf_val = lgb.LGBMClassifier(**PARAMS_B)
clf_val.fit(XB_tr, yB_tr, eval_set=[(XB_va, yB_va)],
            callbacks=[lgb.early_stopping(100, first_metric_only=True, verbose=False)])
best_iter_B = int(clf_val.best_iteration_ or PARAMS_B["n_estimators"])
p_va = clf_val.predict_proba(XB_va)[:, 1]

# Threshold on validation only: maximise F1 subject to recall >= 0.6 (fall back to max F1).
prec, rec, thr = precision_recall_curve(yB_va, p_va)
prec, rec = prec[:-1], rec[:-1]
f1 = np.where(prec + rec > 0, 2 * prec * rec / np.maximum(prec + rec, 1e-12), 0)
ok = rec >= 0.6
threshold = float(thr[np.argmax(np.where(ok, f1, -1))] if ok.any() else thr[np.argmax(f1)])

clf = lgb.LGBMClassifier(**{**PARAMS_B, "n_estimators": best_iter_B})
clf.fit(XB_pt, yB_pt)
p_te = clf.predict_proba(XB_te)[:, 1]
yhat_te = (p_te >= threshold).astype(int)

two_classes = yB_te.nunique() == 2
metrics_B = {
    "val_pr_auc": float(average_precision_score(yB_va, p_va)),
    "val_recall": float(recall_score(yB_va, (p_va >= threshold).astype(int), zero_division=0)),
    "val_precision": float(precision_score(yB_va, (p_va >= threshold).astype(int), zero_division=0)),
    "test_pr_auc": float(average_precision_score(yB_te, p_te)) if two_classes else float("nan"),
    "test_roc_auc": float(roc_auc_score(yB_te, p_te)) if two_classes else float("nan"),
    "test_recall": float(recall_score(yB_te, yhat_te, zero_division=0)),
    "test_precision": float(precision_score(yB_te, yhat_te, zero_division=0)),
    "test_f1": float(f1_score(yB_te, yhat_te, zero_division=0)),
    "threshold": threshold,
    "test_base_rate": float(yB_te.mean()),
    "val_base_rate": float(yB_va.mean()),
    "test_n_spikes": float(yB_te.sum()),
}
print(json.dumps({k: round(v, 4) for k, v in metrics_B.items()}, indent=1))


class SpikeModel(mlflow.pyfunc.PythonModel):
    """LightGBM spike classifier. Input needs FEATURES_B (incl. net_load_p50 from grid.ml.net_load).
    Output: spike_prob, is_spike_pred (at the validation-chosen threshold)."""

    def __init__(self, model, features: list, threshold: float):
        self.model = model
        self.features = features
        self.threshold = threshold

    def predict(self, context, model_input, params=None):
        X = pd.DataFrame(model_input)[self.features].astype("float64")
        p = self.model.predict_proba(X)[:, 1]
        return pd.DataFrame({"spike_prob": p, "is_spike_pred": (p >= self.threshold).astype("float64")}, index=X.index)


wrap_B = SpikeModel(clf, FEATURES_B, threshold)

# COMMAND ----------

# MAGIC %md ## 5 · MLflow: log, register in Unity Catalog, move `@champion` only on improvement

# COMMAND ----------

current_user = spark.sql("select current_user()").first()[0]
mlflow.set_registry_uri("databricks-uc")
try:
    exp = mlflow.set_experiment(f"/Users/{current_user}/gridwise")
except Exception as e:
    # /Users/<me>/gridwise is also the workspace folder worker.deploy uploads notebooks into; if that path is a
    # folder, MLflow cannot create an experiment there, so nest the experiment inside it.
    print("experiment path fallback:", str(e)[:200])
    exp = mlflow.set_experiment(f"/Users/{current_user}/gridwise/gridwise_experiment")
client = MlflowClient()
PIP = [f"lightgbm=={lgb.__version__}", f"pandas=={pd.__version__}", f"numpy=={np.__version__}"]


def save_fig(fig, name):
    path = os.path.join(tempfile.mkdtemp(), name)
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    mlflow.log_artifact(path, artifact_path="plots")


def importance_plot(model, features, title, name):
    imp = pd.Series(model.booster_.feature_importance("gain"), index=features).sort_values().tail(20)
    fig, ax = plt.subplots(figsize=(7, 6))
    imp.plot.barh(ax=ax)
    ax.set_title(title)
    ax.set_xlabel("total gain")
    save_fig(fig, name)


def shap_plot(model, X, name):
    try:
        import shap
        Xs = X.sample(min(2000, len(X)), random_state=SEED)
        sv = shap.TreeExplainer(model).shap_values(Xs)
        if isinstance(sv, list):   # older shap returns [neg, pos] for binary classifiers
            sv = sv[-1]
        shap.summary_plot(sv, Xs, show=False, max_display=20)
        save_fig(plt.gcf(), name)
    except Exception as e:
        print(f"SHAP plot skipped ({name}): {e}")


def champion_metric(name, metric):
    try:
        mv = client.get_model_version_by_alias(name, "champion")
        return client.get_run(mv.run_id).data.metrics.get(metric), mv.version
    except Exception:
        return None, None


def register(model, name, X_ex, run_id):
    preds = model.predict(None, X_ex)
    info = mlflow.pyfunc.log_model(artifact_path="model", python_model=model, registered_model_name=name,
                                   signature=infer_signature(X_ex, preds), input_example=X_ex.head(5),
                                   pip_requirements=PIP)
    version = getattr(info, "registered_model_version", None)
    if version is None:
        version = max(int(v.version) for v in client.search_model_versions(f"name='{name}' and run_id='{run_id}'"))
    return str(version)


logged_at = datetime.now(timezone.utc).replace(tzinfo=None)
reg_errors = {}
print("mlflow", mlflow.__version__)
metric_rows = []

# --- Model A ---
with mlflow.start_run(run_name="model_a_net_load") as run_a:
    mlflow.log_params({**{k: v for k, v in PARAMS_A.items() if k != "n_jobs"},
                       **{f"best_iteration_{q}": i for q, i in best_iter_A.items()},
                       "train_end": str(TRAIN_END), "val_end": str(VAL_END), "test_start_excl": str(TEST_START),
                       "anchor_ts": str(anchor_ts), "n_features": len(FEATURES_A), **split_sizes})
    mlflow.log_dict({"features": FEATURES_A}, "features_a.json")
    mlflow.log_metrics(metrics_A)
    mlflow.log_dict(mape_by_month, "test_mape_by_month.json")
    importance_plot(final_models_A["p50"], FEATURES_A, "Model A (P50) feature importance", "feature_importance_a.png")
    shap_plot(final_models_A["p50"], X_te, "shap_summary_a.png")
    try:
        version_A = register(wrap_A, NAME_A, X_va, run_a.info.run_id)
    except Exception as e:
        version_A, reg_errors["a"] = None, str(e)[:400]
        print("Model A registration failed:", reg_errors["a"])
    run_id_A = run_a.info.run_id

champ_val_A, champ_ver_A = champion_metric(NAME_A, "val_mape")
beats_baseline_A = metrics_A["test_mape"] < metrics_A["baseline_test_mape"]
beats_champ_A = champ_val_A is None or metrics_A["val_mape"] < champ_val_A
promote_A = bool(version_A and beats_baseline_A and beats_champ_A)
if promote_A:
    client.set_registered_model_alias(NAME_A, "champion", version_A)
print(f"Model A v{version_A}: promote={promote_A} (beats baseline={beats_baseline_A}, "
      f"champion v{champ_ver_A} val_mape={champ_val_A})")

# --- Model B ---
with mlflow.start_run(run_name="model_b_spike") as run_b:
    mlflow.log_params({**{k: v for k, v in PARAMS_B.items() if k != "n_jobs"},
                       "best_iteration": best_iter_B, "spike_usd_mwh": SPIKE_USD,
                       "threshold_rule": "max F1 on val s.t. recall>=0.6",
                       "test_start_excl": str(TEST_START), "n_features": len(FEATURES_B)})
    mlflow.log_dict({"features": FEATURES_B}, "features_b.json")
    mlflow.log_metrics({k: v for k, v in metrics_B.items() if not np.isnan(v)})
    importance_plot(clf, FEATURES_B, "Model B (spike) feature importance", "feature_importance_b.png")
    shap_plot(clf, XB_te, "shap_summary_b.png")
    try:
        version_B = register(wrap_B, NAME_B, XB_va, run_b.info.run_id)
    except Exception as e:
        version_B, reg_errors["b"] = None, str(e)[:400]
        print("Model B registration failed:", reg_errors["b"])
    run_id_B = run_b.info.run_id

champ_val_B, champ_ver_B = champion_metric(NAME_B, "val_pr_auc")
skill_B = metrics_B["test_pr_auc"] > metrics_B["test_base_rate"]   # better than random on test
beats_champ_B = champ_val_B is None or metrics_B["val_pr_auc"] > champ_val_B
promote_B = bool(version_B and skill_B and beats_champ_B)
if promote_B:
    client.set_registered_model_alias(NAME_B, "champion", version_B)
print(f"Model B v{version_B}: promote={promote_B} (champion v{champ_ver_B} val_pr_auc={champ_val_B})")

# --- gold.model_metrics (one row per metric per run) ---
for run_id, model_name, mets in [(run_id_A, NAME_A, metrics_A), (run_id_B, NAME_B, metrics_B)]:
    for k, v in mets.items():
        split = k.split("_")[0] if k.split("_")[0] in ("val", "test") else ("test" if "test" in k else "val")
        if k == "threshold":
            split = "val"
        metric_rows.append((run_id, model_name, k, None if np.isnan(v) else float(v), split, logged_at))
spark.sql(f"""CREATE TABLE IF NOT EXISTS {catalog}.gold.model_metrics
              (run_id STRING, model STRING, metric STRING, value DOUBLE, split STRING, logged_at TIMESTAMP)""")
(spark.createDataFrame(metric_rows, "run_id string, model string, metric string, value double, split string, "
                                    "logged_at timestamp")
 .write.mode("append").saveAsTable(f"{catalog}.gold.model_metrics"))

# COMMAND ----------

# MAGIC %md ## 6 · Acceptance checks (contract §4, ML) and registry smoke test on the 48 forecast rows

# COMMAND ----------

reg_A_ok, reg_B_ok, reg_err = False, False, None
try:
    champ_A = mlflow.pyfunc.load_model(f"models:/{NAME_A}@champion")
    out_A = champ_A.predict(to_X(fcst, FEATURES_A))
    reg_A_ok = out_A.shape == (48, 3) and not out_A.isna().any().any()
    champ_B = mlflow.pyfunc.load_model(f"models:/{NAME_B}@champion")
    xb_f = to_X(fcst.assign(net_load_p50=out_A["net_load_p50"].values), FEATURES_B)
    out_B = champ_B.predict(xb_f)
    reg_B_ok = len(out_B) == 48 and out_B["spike_prob"].between(0, 1).all()
    display(pd.concat([fcst[["ts_utc"]], out_A.reset_index(drop=True), out_B.reset_index(drop=True)], axis=1))
except Exception as e:
    reg_err = str(e)[:300]
    print("registry check failed:", reg_err)


def chk(value, ok):
    return {"value": value if not isinstance(value, float) else round(value, 4), "pass": bool(ok)}


checks = {
    "a_test_mape_lt_5": chk(metrics_A["test_mape"], metrics_A["test_mape"] < 5),
    "a_test_mape_lt_baseline": chk(metrics_A["baseline_test_mape"], beats_baseline_A),
    "a_p10_p90_coverage_70_90": chk(metrics_A["test_p10_p90_coverage"], 70 <= metrics_A["test_p10_p90_coverage"] <= 90),
    "b_pr_auc_gt_3x_base_rate": chk(metrics_B["test_pr_auc"], metrics_B["test_pr_auc"] > 3 * metrics_B["test_base_rate"]),
    "registry_net_load_champion_48x3": chk(reg_err or "ok", reg_A_ok),
    "registry_spike_champion_48": chk(reg_err or "ok", reg_B_ok),
}
summary = {
    **checks,
    "all_pass": all(c["pass"] for c in checks.values()),
    "anchor_ts": str(anchor_ts),
    "splits": split_sizes,
    "model_a": {k: round(v, 4) for k, v in metrics_A.items()},
    "model_b": {k: (None if np.isnan(v) else round(v, 4)) for k, v in metrics_B.items()},
    "test_mape_by_month": mape_by_month,
    "registry": {"net_load": {"version": version_A, "promoted": promote_A},
                 "spike": {"version": version_B, "promoted": promote_B}},
    "experiment": exp.name,
    "mlflow_version": mlflow.__version__,
    "registration_errors": reg_errors,
    "runs": {"a": run_id_A, "b": run_id_B},
}
print(json.dumps(summary, indent=1, default=str))

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary, default=str))
