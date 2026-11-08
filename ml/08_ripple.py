# Databricks notebook source
# MAGIC %md
# MAGIC # 08 · Ripple (Phase 4.3, "What if Texas shifted?")
# MAGIC For the **latest `run_ts` in `grid.gold.forecasts`**, precomputes a grid of load-shifting scenarios and writes
# MAGIC
# MAGIC * `grid.gold.shift_scenarios`: one summary row per scenario per `run_ts` (210 rows), and
# MAGIC * `grid.gold.shift_scenario_curves`: 48 hourly rows per scenario (10,080 rows), the before/after curve.
# MAGIC
# MAGIC Re-running for the same `run_ts` deletes that batch from both tables first, so the notebook is idempotent.
# MAGIC
# MAGIC **Grid:** participation `pct` ∈ {1, 2, 5, 10, 15, 20, 25} % × `kwh` per home ∈ {1, 2, 3, 5, 8} ×
# MAGIC `from_window` ∈ {16-20, 17-21} × `to_window` ∈ {22-02, 00-04, 10-14} (local America/Chicago hours,
# MAGIC `a-b` = hours `a, a+1, ..., b-1`, wrapping past midnight; every window is 4 h).
# MAGIC
# MAGIC **Shift rule.** `RIPPLE_RESIDENTIAL_METERS = 9,000,000` homes (a fixed constant, not read from env: roughly
# MAGIC ERCOT's residential meter count). Energy moved per day = `pct/100 × homes × kwh / 1000` MWh, spread evenly, so
# MAGIC `shift_mw = energy_mwh / window_len_h` is **removed** from every hour of the from-window and **added** to every
# MAGIC hour of the to-window (energy is conserved). This is applied to every local day whose from-window lies
# MAGIC inside the 48 h horizon (normally 2 evenings). **Tonight's partial window:** when the run happens after the
# MAGIC from-window has already started (e.g. `run_ts` 22Z = 4 PM CST, horizon starts 5 PM), the *remaining* hours of
# MAGIC tonight's window are still shifted at the same `shift_mw` per hour, so that evening moves
# MAGIC `shift_mw x remaining_hours` MWh (homes keep shifting at the same rate; the hours already past are gone).
# MAGIC Without this the 48 h peak (often tonight's 6 PM) could never be reduced on afternoon runs. Only a window cut
# MAGIC off at the *start* of the horizon is used partially; to-windows and windows cut off at the end must be complete.
# MAGIC
# MAGIC **Day pairing.** From-window instances are taken in time order; each is paired with the **unused** occurrence of
# MAGIC the to-window whose start is nearest in time and which lies fully inside the horizon (ties go to the later one;
# MAGIC a to-window instance never receives two days of load). In practice: `22-02` → the same evening (D 22:00 →
# MAGIC D+1 02:00); `00-04` → the night that follows (D+1 00:00-04:00); `10-14` → usually the next late morning (D+1),
# MAGIC because today's morning is already past when the horizon starts mid-afternoon. An instance with no in-horizon
# MAGIC partner is skipped (`n_shift_days` records how many evenings were shifted, a partial evening counts as 1;
# MAGIC `energy_shifted_mwh` is the actual total moved).
# MAGIC
# MAGIC **Checks.** Hard invariants (fail the task): energy conservation, 48 rows per scenario, the unshifted re-score
# MAGIC equals `gold.forecasts`, plus row counts / unique keys / value ranges / the peakers formula. The first three are
# MAGIC asserted **before** writing, so bad data never lands. Checks that depend on the time of day or the weather
# MAGIC (every scenario shifts, peak monotonic in `pct`, from-window max falls, demo scenario reduces the peak) are
# MAGIC **warnings**: reported under `warnings` / `warned` in the exit JSON, never counted in `all_pass`.
# MAGIC
# MAGIC **Re-scoring (same as `05_predict`).** After the shift, `net_load_after = net_load_used + delta`. Model B
# MAGIC (`grid.ml.spike`, the exact version recorded in `gold.forecasts.model_b_version`) is re-run on the 48
# MAGIC `gold.features` forecast rows with its `net_load_p50` input = `net_load_after` (05 feeds `net_load_used` there).
# MAGIC `strain_index` = percentile of `net_load_after` in `gold.strain_reference` for the local month, `+15` (cap 100)
# MAGIC when `spike_prob > 0.5`; `level`: green < 60 ≤ yellow ≤ 85 < red. The "before" side is the stored forecast, and
# MAGIC the notebook checks that re-scoring the unshifted curve reproduces it exactly.
# MAGIC
# MAGIC **Summary metrics.** `peak_mw_*` = max net load over the 48 h; `peak_reduction_mw = peak_mw_before −
# MAGIC peak_mw_after` (signed: negative means the shifted load created a new, higher peak); `rebound = true` when the
# MAGIC 48 h peak after shifting sits inside the to-window (the moved load became the peak);
# MAGIC `peakers_avoided = max(0, peak_reduction_mw) / 200` (≈ one 200 MW gas peaker unit; a display heuristic, not a
# MAGIC dispatch model).

# COMMAND ----------

# MAGIC %pip install -q lightgbm==4.5.0 shap==0.46.0 "mlflow>=2.21.3"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import itertools
import json
import os

os.environ["MLFLOW_USE_DATABRICKS_SDK_MODEL_ARTIFACTS_REPO_FOR_UC"] = "true"   # same UC artifact route as 04/05
from datetime import datetime, timezone

import mlflow
import numpy as np
import pandas as pd

dbutils.widgets.text("catalog", "grid")
catalog = dbutils.widgets.get("catalog")
spark.conf.set("spark.sql.session.timeZone", "UTC")
mlflow.set_registry_uri("databricks-uc")

NAME_B = f"{catalog}.ml.spike"
FCST = f"{catalog}.gold.forecasts"
T_SUM = f"{catalog}.gold.shift_scenarios"
T_CURVE = f"{catalog}.gold.shift_scenario_curves"
TZ = "America/Chicago"

RIPPLE_RESIDENTIAL_METERS = 9_000_000     # homes; fixed constant (not env), ~ERCOT residential meters
PEAKER_MW = 200.0                         # one gas peaker unit, for "peakers_avoided"
PCTS = [1, 2, 5, 10, 15, 20, 25]
KWHS = [1, 2, 3, 5, 8]
FROM_WINDOWS = ["16-20", "17-21"]
TO_WINDOWS = ["22-02", "00-04", "10-14"]
SPIKE_BOOST_PROB, SPIKE_BOOST = 0.5, 15.0
GREEN_MAX, YELLOW_MAX = 60.0, 85.0

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

# COMMAND ----------

# MAGIC %md ## 1 · Latest forecast batch + matching feature rows

# COMMAND ----------

run_ts = pd.Timestamp(spark.sql(f"SELECT max(run_ts) m FROM {FCST}").first()["m"])
run_ts_sql = run_ts.strftime("%Y-%m-%d %H:%M:%S")
fc = (spark.sql(f"SELECT * FROM {FCST} WHERE run_ts = TIMESTAMP '{run_ts_sql}'").toPandas()
      .sort_values("target_ts").reset_index(drop=True))
fc["target_ts"] = pd.to_datetime(fc["target_ts"])
assert len(fc) == 48, f"forecast batch {run_ts} has {len(fc)} rows"
ver_B = str(fc["model_b_version"].iloc[0])

feat = (spark.table(f"{catalog}.gold.features").where("is_forecast_row")
        .select("ts_utc", "anchor_ts", *[c for c in FEATURES_B if c != "net_load_p50"]).toPandas())
feat["ts_utc"] = pd.to_datetime(feat["ts_utc"])
feat_anchor = pd.Timestamp(feat["anchor_ts"].iloc[0])
assert feat_anchor == run_ts, (f"gold.features anchor_ts {feat_anchor} != latest forecasts run_ts {run_ts}; "
                               "run 05_predict first")
feat = fc[["target_ts"]].merge(feat, left_on="target_ts", right_on="ts_utc", how="left")
assert feat["ts_utc"].notna().all(), "feature rows missing for some forecast hours"

local = fc["target_ts"].dt.tz_localize("UTC").dt.tz_convert(TZ)
fc["local_time"] = local.map(lambda t: t.isoformat())
fc["local_hour"] = local.dt.hour.values
print(f"run_ts {run_ts} | Model B v{ver_B} | horizon {local.iloc[0]} .. {local.iloc[-1]}")

# COMMAND ----------

# MAGIC %md ## 2 · Model B, strain reference, scoring helpers

# COMMAND ----------

model_B = mlflow.pyfunc.load_model(f"models:/{NAME_B}/{ver_B}")
ref = spark.table(f"{catalog}.gold.strain_reference").toPandas()
ref_by_month = {int(m): g.sort_values("pct") for m, g in ref.groupby("month")}


def percentile_in_month(value, month):          # identical to 05_predict
    g = ref_by_month[int(month)]
    xp = np.maximum.accumulate(g["net_load_mw"].to_numpy(float))
    return float(np.interp(value, xp, g["pct"].to_numpy(float), left=0.0, right=100.0))


def strain_and_level(net_load, spike, months):
    base = np.array([percentile_in_month(v, m) for v, m in zip(net_load, months)])
    s = np.where(spike > SPIKE_BOOST_PROB, np.minimum(100.0, base + SPIKE_BOOST), base)
    lvl = np.select([s < GREEN_MAX, s <= YELLOW_MAX], ["green", "yellow"], "red")
    return s, lvl


X_base = feat[[c for c in FEATURES_B if c != "net_load_p50"]].astype("float64").reset_index(drop=True)
months = fc["local_month"].astype(int).values

# Baseline reproduction check: re-scoring the unshifted curve must give the stored forecast.
sp0 = model_B.predict(X_base.assign(net_load_p50=fc["net_load_used"].astype(float).values)[FEATURES_B]
                      )["spike_prob"].astype(float).values
s0, l0 = strain_and_level(fc["net_load_used"].astype(float).values, sp0, months)
repro_spike_err = float(np.max(np.abs(sp0 - fc["spike_prob"].astype(float).values)))
repro_strain_err = float(np.max(np.abs(s0 - fc["strain_index"].astype(float).values)))
repro_level_ok = bool((l0 == fc["level"].values).all())
print(f"baseline reproduction: spike err {repro_spike_err:.2e}, strain err {repro_strain_err:.2e}, "
      f"levels equal {repro_level_ok}")

# COMMAND ----------

# MAGIC %md ## 3 · Window instances and day pairing

# COMMAND ----------

ts_index = {t: i for i, t in enumerate(local)}            # tz-aware local hour -> row


def window_hours(w):
    a, b = (int(x) for x in w.split("-"))
    n = (b - a) % 24
    return a, n


def instances(w, allow_head_partial=False):
    """In-horizon occurrences of window w: list of (start_local, [row indices]).
    allow_head_partial: also return a window that started before the horizon (tonight's window when the run is
    mid-window), keeping only its remaining hours. Windows cut off at the end of the horizon are never returned."""
    a, n = window_hours(w)
    h0 = local.iloc[0]
    out = []
    for d in sorted({t.date() for t in local} | {(h0 - pd.Timedelta(days=1)).date()}):
        start = pd.Timestamp(d).tz_localize(TZ) + pd.Timedelta(hours=a)
        hrs = [start + pd.Timedelta(hours=k) for k in range(n)]
        if all(h in ts_index for h in hrs):
            out.append((start, [ts_index[h] for h in hrs]))
        elif allow_head_partial and start < h0:
            rest = [h for h in hrs if h >= h0]
            if rest and all(h in ts_index for h in rest):
                out.append((start, [ts_index[h] for h in rest]))
    return out


PAIRS = {}   # (from, to) -> list of (from_rows, to_rows, from_start, to_start)
for fw, tw in itertools.product(FROM_WINDOWS, TO_WINDOWS):
    pairs = []
    tos = instances(tw)
    used = set()
    for f_start, f_rows in instances(fw, allow_head_partial=True):            # chronological; each to-instance is used at most once
        cands = [(abs((t_start - f_start).total_seconds()), -t_start.value, t_start, t_rows)
                 for t_start, t_rows in tos if t_start not in used and not set(t_rows) & set(f_rows)]
        if cands:
            _, _, t_start, t_rows = min(cands)
            used.add(t_start)
            pairs.append((f_rows, t_rows, f_start, t_start))
    PAIRS[(fw, tw)] = pairs
    print(f"{fw} -> {tw}: " + "; ".join(f"{a:%a %H:%M} ({len(fr)} h) -> {b:%a %H:%M}" for fr, _, a, b in pairs))

# COMMAND ----------

# MAGIC %md ## 4 · Build every scenario curve and re-score Model B in one batch

# COMMAND ----------

nl0 = fc["net_load_used"].astype(float).values
scen = []          # (pct, kwh, fw, tw, delta[48], shift_mw, n_days)
for pct, kwh, fw, tw in itertools.product(PCTS, KWHS, FROM_WINDOWS, TO_WINDOWS):
    energy_mwh = pct / 100.0 * RIPPLE_RESIDENTIAL_METERS * kwh / 1000.0     # per full evening
    shift_mw = energy_mwh / window_hours(fw)[1]                               # MW per from-window hour
    delta = np.zeros(48)
    moved = 0.0
    for f_rows, t_rows, _, _ in PAIRS[(fw, tw)]:
        e = shift_mw * len(f_rows)              # a partial (already started) evening moves only its remaining hours
        delta[f_rows] -= shift_mw
        delta[t_rows] += e / len(t_rows)
        moved += e
    scen.append((pct, kwh, fw, tw, delta, shift_mw, moved, len(PAIRS[(fw, tw)])))

# Hard invariants, checked in memory BEFORE anything is written.
energy_err_mem = float(max(abs(s[4].sum()) for s in scen))
assert energy_err_mem < 1e-6, f"energy not conserved: {energy_err_mem}"
assert all(len(s[4]) == 48 for s in scen), "scenario curve is not 48 hours"
assert repro_spike_err < 1e-6 and repro_strain_err < 1e-6 and repro_level_ok, (
    f"unshifted re-score != gold.forecasts (spike {repro_spike_err}, strain {repro_strain_err}, "
    f"levels {repro_level_ok})")

X_all = pd.concat([X_base.assign(net_load_p50=nl0 + s[4]) for s in scen], ignore_index=True)[FEATURES_B]
sp_all = model_B.predict(X_all)["spike_prob"].astype(float).values.reshape(len(scen), 48)
print(f"scored {len(scen)} scenarios x 48 h = {len(X_all)} rows")

created = datetime.now(timezone.utc).replace(tzinfo=None)
spike0 = fc["spike_prob"].astype(float).values
strain0 = fc["strain_index"].astype(float).values
level0 = fc["level"].values
peak0 = float(nl0.max())
sum_rows, curve_rows = [], []
for k, (pct, kwh, fw, tw, delta, shift_mw, moved_mwh, n_days) in enumerate(scen):
    nl1 = nl0 + delta
    sp1 = sp_all[k]
    s1, l1 = strain_and_level(nl1, sp1, months)
    peak1 = float(nl1.max())
    i_peak1 = int(np.argmax(nl1))
    to_rows = {r for _, t_rows, _, _ in PAIRS[(fw, tw)] for r in t_rows}
    red = int((l1 == "red").sum())
    red0 = int((level0 == "red").sum())
    reduction = peak0 - peak1
    sum_rows.append(dict(
        run_ts=run_ts.to_pydatetime(), pct=int(pct), kwh=float(kwh), from_window=fw, to_window=tw,
        homes=int(RIPPLE_RESIDENTIAL_METERS), energy_shifted_mwh=float(moved_mwh),
        shift_mw_per_hour=float(shift_mw), n_shift_days=int(n_days),
        red_hours_before=red0, red_hours_after=red,
        peak_mw_before=peak0, peak_mw_after=peak1, peak_reduction_mw=float(reduction),
        peak_ts_before=fc["target_ts"].iloc[int(np.argmax(nl0))].to_pydatetime(),
        peak_ts_after=fc["target_ts"].iloc[i_peak1].to_pydatetime(),
        max_spike_before=float(spike0.max()), max_spike_after=float(sp1.max()),
        max_strain_before=float(strain0.max()), max_strain_after=float(s1.max()),
        peakers_avoided=float(max(0.0, reduction) / PEAKER_MW),
        rebound=bool(i_peak1 in to_rows),
        model_b_version=ver_B, created_at=created,
    ))
    for i in range(48):
        curve_rows.append(dict(
            run_ts=run_ts.to_pydatetime(), pct=int(pct), kwh=float(kwh), from_window=fw, to_window=tw,
            target_ts=fc["target_ts"].iloc[i].to_pydatetime(), local_time=fc["local_time"].iloc[i],
            horizon_h=int(fc["horizon_h"].iloc[i]), shift_mw=float(delta[i]),
            before_mw=float(nl0[i]), after_mw=float(nl1[i]),
            strain_before=float(strain0[i]), strain_after=float(s1[i]),
            level_before=str(level0[i]), level_after=str(l1[i]),
            spike_before=float(spike0[i]), spike_after=float(sp1[i]), created_at=created,
        ))
summ = pd.DataFrame(sum_rows)
curves = pd.DataFrame(curve_rows)
display(summ[(summ.from_window == "16-20") & (summ.to_window == "22-02") & (summ.kwh == 3)])

# COMMAND ----------

# MAGIC %md ## 5 · Write (delete this `run_ts`, then append)

# COMMAND ----------

SUM_SCHEMA = """run_ts TIMESTAMP, pct INT, kwh DOUBLE, from_window STRING, to_window STRING, homes BIGINT,
  energy_shifted_mwh DOUBLE, shift_mw_per_hour DOUBLE, n_shift_days INT, red_hours_before INT, red_hours_after INT,
  peak_mw_before DOUBLE, peak_mw_after DOUBLE, peak_reduction_mw DOUBLE, peak_ts_before TIMESTAMP,
  peak_ts_after TIMESTAMP, max_spike_before DOUBLE, max_spike_after DOUBLE, max_strain_before DOUBLE,
  max_strain_after DOUBLE, peakers_avoided DOUBLE, rebound BOOLEAN, model_b_version STRING, created_at TIMESTAMP"""
CURVE_SCHEMA = """run_ts TIMESTAMP, pct INT, kwh DOUBLE, from_window STRING, to_window STRING, target_ts TIMESTAMP,
  local_time STRING, horizon_h INT, shift_mw DOUBLE, before_mw DOUBLE, after_mw DOUBLE, strain_before DOUBLE,
  strain_after DOUBLE, level_before STRING, level_after STRING, spike_before DOUBLE, spike_after DOUBLE,
  created_at TIMESTAMP"""
spark.sql(f"CREATE TABLE IF NOT EXISTS {T_SUM} ({SUM_SCHEMA}) USING DELTA COMMENT 'GridWise Ripple scenario "
          f"summaries (pct x kwh x from x to), one batch per run_ts; written by ml/08_ripple'")
spark.sql(f"CREATE TABLE IF NOT EXISTS {T_CURVE} ({CURVE_SCHEMA}) USING DELTA COMMENT 'GridWise Ripple "
          f"before/after 48 h curves per scenario, one batch per run_ts; written by ml/08_ripple'")


def py(v):
    """numpy/pandas scalars -> plain Python for createDataFrame; NaN -> NULL (same as 05_predict)."""
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.generic):
        v = v.item()
    return None if (isinstance(v, float) and np.isnan(v)) else v


def write(df, table, schema):
    cols = [c.strip().split()[0] for c in schema.replace("\n", " ").split(",")]
    sdf = spark.createDataFrame([tuple(py(v) for v in r) for r in df[cols].itertuples(index=False, name=None)],
                                schema.replace("\n", " "))
    spark.sql(f"DELETE FROM {table} WHERE run_ts = TIMESTAMP '{run_ts_sql}'")
    sdf.select(*spark.table(table).columns).write.mode("append").saveAsTable(table)


write(summ, T_SUM, SUM_SCHEMA)
write(curves, T_CURVE, CURVE_SCHEMA)

# COMMAND ----------

# MAGIC %md ## 6 · Validation (read back)

# COMMAND ----------

bs = spark.sql(f"SELECT * FROM {T_SUM} WHERE run_ts = TIMESTAMP '{run_ts_sql}'").toPandas()
bc = spark.sql(f"SELECT * FROM {T_CURVE} WHERE run_ts = TIMESTAMP '{run_ts_sql}'").toPandas()
n_scen = len(PCTS) * len(KWHS) * len(FROM_WINDOWS) * len(TO_WINDOWS)
KEY = ["pct", "kwh", "from_window", "to_window"]

# Monotonic sanity: for fixed (kwh, from, to), more participation -> peak never higher, *unless* the new peak sits in
# the to-window (rebound: the shifted load itself became the peak, so more shifting raises it).
# The from-window max must strictly fall.
mono_bad, rebound_groups = [], 0
for (kwh, fw, tw), g in bs.sort_values("pct").groupby(["kwh", "from_window", "to_window"]):
    pk = g["peak_mw_after"].to_numpy()
    reb = g["rebound"].to_numpy()
    rebound_groups += int(reb.any())
    for j in range(1, len(pk)):
        if pk[j] > pk[j - 1] + 1e-6 and not reb[j]:
            mono_bad.append(f"{kwh}/{fw}/{tw}/pct{g['pct'].iloc[j]}")
from_max = (bc[bc["shift_mw"] < 0].groupby(KEY)["after_mw"].max().reset_index()
            .sort_values("pct").groupby(["kwh", "from_window", "to_window"])["after_mw"]
            .apply(lambda s: bool((np.diff(s.to_numpy()) < 0).all())))
energy_err = float(bc.groupby(KEY)["shift_mw"].sum().abs().max())
p5 = bs[(bs.pct == 5) & (bs.kwh == 3) & (bs.from_window == "16-20") & (bs.to_window == "22-02")].iloc[0]


def chk(value, ok):
    return {"value": value if not isinstance(value, float) else round(value, 4), "pass": bool(ok)}


# Hard invariants (count in all_pass; the task fails if any is false).
checks = {
    "summary_rows": chk(len(bs), len(bs) == n_scen),
    "summary_unique_keys": chk(int(bs[KEY].drop_duplicates().shape[0]), bs[KEY].drop_duplicates().shape[0] == n_scen),
    "curve_rows": chk(len(bc), len(bc) == n_scen * 48),
    "curve_48_per_scenario": chk("48", (bc.groupby(KEY).size() == 48).all()),
    "energy_conserved": chk(energy_err, energy_err < 1e-6),
    "baseline_reproduces_forecast": chk({"spike_err": repro_spike_err, "strain_err": repro_strain_err,
                                         "levels_equal": repro_level_ok},
                                        repro_spike_err < 1e-6 and repro_strain_err < 1e-6 and repro_level_ok),
    "spike_in_0_1": chk(float(bc["spike_after"].max()), bc["spike_after"].between(0, 1).all()),
    "strain_in_0_100": chk(float(bc["strain_after"].max()), bc["strain_after"].between(0, 100).all()),
    "levels_valid": chk(sorted(bc["level_after"].unique().tolist()),
                        bc["level_after"].isin(["green", "yellow", "red"]).all()),
    "peakers_formula": chk("max(0,red)/200", np.allclose(bs["peakers_avoided"],
                                                         bs["peak_reduction_mw"].clip(lower=0) / PEAKER_MW)),
}
# Time-of-day / weather dependent: reported in the exit JSON, never fail the task.
warnings = {
    "every_scenario_shifts": chk(int(bs["n_shift_days"].min()), bs["n_shift_days"].min() >= 1),
    "peak_monotonic_in_pct": chk({"violations": mono_bad[:10], "groups_with_rebound": rebound_groups},
                                 not mono_bad),
    "from_window_max_strictly_falls": chk(int(from_max.sum()), bool(from_max.all()) and len(from_max) == 30),
    "demo_scenario_helps": chk({"peak_reduction_mw": round(float(p5["peak_reduction_mw"])),
                                "n_shift_days": int(p5["n_shift_days"]),
                                "energy_shifted_mwh": round(float(p5["energy_shifted_mwh"])),
                                "max_spike": [round(float(p5["max_spike_before"]), 3),
                                              round(float(p5["max_spike_after"]), 3)],
                                "red_hours": [int(p5["red_hours_before"]), int(p5["red_hours_after"])]},
                               p5["peak_reduction_mw"] > 0),
}
warned = [k for k, v in warnings.items() if not v["pass"]]
failed = [k for k, v in checks.items() if not v["pass"]]
best = bs.sort_values("peak_reduction_mw", ascending=False).iloc[0]
summary = {
    **checks,
    "all_pass": not failed,
    "failed": failed,
    "warnings": warnings,
    "warned": warned,
    "run_ts": str(run_ts),
    "tables": [T_SUM, T_CURVE],
    "model_b_version": ver_B,
    "homes": RIPPLE_RESIDENTIAL_METERS,
    "pairing": {f"{fw}->{tw}": [f"{a.isoformat()} ({len(fr)} h) -> {b.isoformat()}" for fr, _, a, b in v]
                for (fw, tw), v in PAIRS.items()},
    "peak_before_mw": round(peak0),
    "best_scenario": {k: (round(float(best[k]), 1) if isinstance(best[k], (float, np.floating)) else str(best[k]))
                      for k in KEY + ["peak_reduction_mw", "red_hours_after", "max_spike_after", "peakers_avoided"]},
    "rebound_scenarios": int(bs["rebound"].sum()),
}
print(json.dumps(summary, indent=1, default=str))
assert not failed, f"failed hard checks: {failed}"   # warnings never fail the task

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary, default=str))
