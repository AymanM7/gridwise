# Phase 2/3 Data Contract (binding)

Owner: PM / tech lead. Status: **v1.1, binding** (v1.1 amended 2026-11-07 by PM review round 2: solar band 40 GW, ML criteria for Model A, new Model D). Changes go through the PM, not by editing a downstream notebook.
Catalog: `grid` (widget `catalog`). All timestamps are `TIMESTAMP` in UTC; `spark.sql.session.timeZone = UTC`.

| Notebook | Owner | Writes (Delta, `CREATE OR REPLACE` / overwrite) |
|---|---|---|
| `notebooks/02_silver.py` | Silver data engineer | `silver.weather_hourly`, `silver.grid_hourly`, `silver.dq_checks` |
| `notebooks/03_gold.py` | Gold analytics engineer | `gold.features`, `gold.strain_hourly`, `gold.strain_reference`, `gold.spike_events`, `gold.dq_checks` |
| `notebooks/04_train.py` | ML engineer | MLflow runs, `grid.ml.net_load`, `grid.ml.spike`, `gold.model_metrics` |

Nobody edits another owner's notebook. Each notebook ends with `dbutils.notebook.exit(json.dumps(summary))`, where `summary` holds the acceptance check results below (`{"check_name": {"value": ..., "pass": true/false}}` plus `"all_pass"`).

---

## 0. Bronze findings (measured 2026-11-07, these change the plan)

1. **EIA 2023 is null in typed columns.** `eia_2023.parquet` (8,760 rows) has the values in `_rescued_data` because of an int/double schema mismatch. Silver **must** recover them:
   `coalesce(demand_mw, cast(get_json_object(_rescued_data,'$.demand_mw') as double))`, and the same for `wind_mw`, `solar_mw`, `demand_forecast_mw`. Apply this rescue pattern to every numeric Bronze column in every table; it is a no-op where nothing was rescued.
2. **The EIA hour convention is confirmed.** On 2026-11-06/07, EIA `demand_mw` matches ERCOT hourly load within 0.1% on the same `interval_start_utc`, so no shift is needed. EIA wind and solar match ERCOT `gen_mw` to within 1 MW.
3. **Price gap:** no `ercot_prices` rows for 2026-11-01 05:00Z to 2026-11-06 05:00Z (121 h, between the yearly archive and the live files). **Weather gap:** `weather_hist` ends 2026-11-01 23:00Z and `weather_forecast` starts 2026-11-04 00:00Z (48 h). **EIA wind/solar gap:** 2025-12-05 06:00Z to 2025-12-06 05:00Z (24 h). These are ingestion (Phase 1) backfill items. Silver does not fabricate data for them; see the gap rules below.
4. `ercot_load` mixes hourly rows (older part) with 5-min rows (recent part). Partial hours exist, for example 2 of 12 rows at the edges.
5. Net load in 2024–2026 actually reaches about **7 GW** (spring solar plus wind; 1st percentile about 11–13 GW). The plausibility band below is widened to match.
6. Hourly spike rate (avg RT price > $100): 2023 3.9%, 2024 1.8%, 2025 2.5%, 2026 2.4%.

---

## 1. Silver

### 1.1 `silver.weather_hourly`: 1 row per `ts_utc`

| column | type | notes |
|---|---|---|
| `ts_utc` | timestamp | hour start |
| `temp_f_{hou,dfw,aus,sat}` | double | per city, `temperature_2m` |
| `rh_{hou,dfw,aus,sat}` | double | % |
| `temp_f` | double | population-weighted mean (weights hou 7.5, dfw 8.1, aus 2.5, sat 2.7, normalised over the cities present) |
| `rh_pct`, `apparent_temp_f`, `wind_mph`, `cloud_pct`, `ghi_wm2` | double | population-weighted from `relative_humidity_2m`, `apparent_temperature`, `wind_speed_10m`, `cloud_cover`, `shortwave_radiation` |
| `heat_index_f` | double | NWS Rothfusz formula on the weighted `temp_f`/`rh_pct` (Steadman simple formula when HI < 80 °F); equals `temp_f` when `temp_f` < 80 |
| `wx_source` | string | `archive` / `forecast` / `interp` / null |

Precedence per (city, hour): **archive wins**. Forecast fills only hours with no archive row. Among forecast files, the latest `_fetched_at_utc` wins. A gap of 6 h or less per city is linearly interpolated (`wx_source='interp'`). A longer gap stays null.

### 1.2 `silver.grid_hourly`: 1 row per UTC hour, no duplicate `ts_utc`

Range: `2023-01-01 00:00Z` → `anchor_ts + 48h`, contiguous (every hour present, with nulls where data is missing).
`anchor_ts` = the latest hour where demand, wind and solar are all non-null (the last complete actual hour). Rows after it are **forecast rows**.

| column | type | source / rule |
|---|---|---|
| `ts_utc` | timestamp | PK, hour start |
| `ts_local` | timestamp | `from_utc_timestamp(ts_utc,'America/Chicago')` (wall clock, for calendar features) |
| `utc_offset` | string | `-05:00` / `-06:00` (from ERCOT `interval_start_local` where present, otherwise derived) |
| `demand_mw` | double | ERCOT live hourly avg if the hour is **complete** (covered minutes ≥ 55, computed as Σ(`interval_end`−`interval_start`)), otherwise EIA |
| `wind_mw` | double | ERCOT `gen_mw` (latest `publish_time_utc` with non-null `gen_mw`), otherwise EIA |
| `solar_mw` | double | same as wind |
| `net_load_mw` | double | `demand_mw − wind_mw − solar_mw`; null if any input is null |
| `price_usd_mwh` | double | avg of 15-min HB_HUBAVG RT prices in the hour; null unless all 4 intervals are present |
| `price_max_usd_mwh` | double | max 15-min price in the hour |
| `demand_forecast_mw` | double | EIA `demand_forecast_mw` (ERCOT day-ahead load forecast; benchmark only, see §2.3) |
| `wind_forecast_mw`, `solar_forecast_mw` | double | ERCOT STWPF/STPPF `forecast_mw` from the **latest** publish covering the hour (null before ~2026-11-05, since live data only) |
| `wind_forecast_p80_mw`, `solar_forecast_p80_mw`, `wind_hsl_mw`, `solar_hsl_mw` | double | same rule |
| all `silver.weather_hourly` columns | | left join on `ts_utc` |
| `src_demand`, `src_wind`, `src_solar` | string | `ercot` / `eia` / null |
| `is_forecast_row` | boolean | `ts_utc > anchor_ts` |
| `anchor_ts` | timestamp | constant column (same value on every row) |
| `_built_at` | timestamp | |

General rules:
- **Dedupe first.** Within any Bronze table, rows with the same key (`interval_start_utc`, plus `city`/`location`) are deduped by keeping the latest `_fetched_at_utc` (then the latest `_ingested_at`).
- **ERCOT live > EIA** for overlapping hours. EIA is the history backbone.
- The current partial hour is never treated as actual (the completeness rule handles this).
- **Grid gaps are not interpolated.** Missing price and actual hours stay null. Gold and the ML engineer drop null-target rows.
- Forecast rows: actual columns (`demand/wind/solar/net_load/price`) are null. Weather (forecast), ERCOT wind/solar forecasts and calendar data are filled.

**DST demonstration (required, displayed):** a `display()` cell showing the 2023-11-05, 2024-11-03 and 2025-11-02 fall-back nights. For each, show `interval_start_local` 01:00 `-05:00` and 01:00 `-06:00` from `ercot_prices`, mapping to **two distinct** `ts_utc` (06:00Z and 07:00Z), each with its own hourly price in `grid_hourly`. Also show that the spring-forward days (2023-03-12, 2024-03-10, 2025-03-09) have 23 local hours, that no 02:00 local hour exists, and that UTC is contiguous. Write the result into `dq_checks` as `dst_fallback_distinct_utc = true`.

---

## 2. Gold

### 2.1 Leakage design for Model A (decided): **"lag-48 floor", a single direct model**

One model serves every horizon h = 1..48 from `anchor_ts`. A target hour `t` may use only:
- **Autoregressive features with lag ≥ 48 h** (`t−48` ≤ `anchor_ts` for every t ≤ anchor+48, so all are known at issuance), and rolling windows that **end at `t−48`**.
- **Known-ahead exogenous features at `t`**: calendar data and weather at `t`. Training uses archive weather and inference uses forecast weather, an accepted optimism that is documented.

Lags of 1 h and 24 h are in `gold.features` for analytics and the dashboard only (`diag_` prefix). **They are banned from Model A and Model B.** ERCOT wind/solar forecasts have no history, so they are not training features (inference display only). `demand_forecast_mw` is not available 48 h ahead, so it is excluded and used only as a benchmark.

### 2.2 `gold.features`: 1 row per `ts_utc` (same range and grain as Silver, including the 48 forecast rows)

| group | columns (all double unless noted) |
|---|---|
| keys | `ts_utc` (timestamp), `ts_local`, `is_forecast_row` (bool), `anchor_ts` |
| targets | `y_net_load_mw` (= `net_load_mw`), `y_price_usd_mwh`, `y_is_spike` (int 0/1, `price > 100`; null when price is null) |
| calendar (local) | `hour` (int 0–23), `dow` (int 1=Mon..7), `month` (int), `doy` (int), `is_weekend` (int), `is_holiday` (int, `holidays.US()` on the local date), `hour_sin`, `hour_cos`, `doy_sin`, `doy_cos` |
| weather at t | `temp_f`, `heat_index_f`, `rh_pct`, `wind_mph`, `cloud_pct`, `ghi_wm2`, `temp_f_{hou,dfw,aus,sat}`, `cdd` = max(temp_f−65,0), `hdd` = max(65−temp_f,0), `temp_f_roll24_mean` (window t−23..t, weather is known-ahead) |
| AR lags ≥ 48 h | `nl_lag_48h`, `nl_lag_72h`, `nl_lag_168h`, `nl_lag_336h`, `demand_lag_48h`, `demand_lag_168h`, `wind_lag_48h`, `wind_lag_168h`, `solar_lag_48h`, `solar_lag_168h`, `price_lag_48h`, `price_lag_168h` |
| AR rolling (end at t−48) | `nl_roll24_mean_l48`, `nl_roll168_mean_l48`, `nl_roll168_max_l48`, `price_roll168_mean_l48`, `price_roll168_max_l48`, `spike_count_168_l48` |
| diagnostics (banned for models) | `diag_nl_lag_1h`, `diag_nl_lag_24h` |
| live ERCOT (banned for training) | `wind_forecast_mw`, `solar_forecast_mw` |

Compute lags by **time** (self-join on `ts_utc − INTERVAL n HOURS`), not by row offset, so gaps cannot shift lags. Rolling windows ignore nulls and require ≥ 50% non-null, otherwise null.

### 2.3 `gold.strain_hourly` and `gold.strain_reference`

- `gold.strain_reference(month int, pct int 0..100, net_load_mw double)`: the percentile breakpoints of actual `net_load_mw` per local calendar month, over all actual history (the simpler variant of "trailing 2 years"; the history is under 4 years anyway). Phase 3 uses this table to map forecast P50 values to a strain value.
- `gold.strain_hourly(ts_utc, net_load_mw, strain_index double 0–100, level string, is_forecast_row)`: actual rows only. `strain_index = 100 * percent_rank()` of `net_load_mw` within the same local month. `level`: `green` < 60, `yellow` 60–85, `red` > 85. Phase 2 has **no spike boost** here. Phase 3 adds the boost in `gold.forecasts`: `strain = min(100, strain + 15)` when `spike_prob > 0.5`.

### 2.4 `gold.spike_events`

`(ts_utc, price_usd_mwh, price_max_usd_mwh, is_spike int)`: **every** hour with a non-null price; `is_spike = price_usd_mwh > 100`. Dashboards filter `is_spike = 1`.

---

## 3. Phase 3 interface (`notebooks/04_train.py`, ML engineer)

- Input: `grid.gold.features WHERE NOT is_forecast_row AND y_net_load_mw IS NOT NULL` (Model B: `y_is_spike IS NOT NULL`).
- **Feature list** (constant `FEATURES_A` in the notebook): calendar + weather-at-t + AR lags ≥ 48 h + AR rolling `_l48` groups from §2.2. No `diag_*`, no `wind/solar_forecast_mw`, no `demand_forecast_mw`, no `price_*` (prices are for Model B only).
- `FEATURES_B = FEATURES_A + price_lag_48h, price_lag_168h, price_roll168_mean_l48, price_roll168_max_l48, spike_count_168_l48, net_load_p50`. Here `net_load_p50` is Model A's P50 prediction (in-sample on train; this optimism is documented).
- **Split (UTC):** train `ts_utc < 2025-07-01`; validate `2025-07-01 ≤ ts_utc < 2025-10-01`; test = `ts_utc > anchor_ts − 92 days`. Early stopping and threshold selection use validation only. The **final champion fit** uses all rows before the test window (train + val + the gap months) with `best_iteration` from validation, then is scored once on test.
- Baseline: seasonal-naive `nl_lag_168h`. Benchmark: ERCOT `demand_forecast_mw` MAPE on demand (about 2.1% historically), shown for context.
- **Model A:** LightGBM, 3 boosters (`objective='quantile'`, α = 0.1 / 0.5 / 0.9; P50 may use `regression_l1`). They are wrapped in **one** `mlflow.pyfunc` model whose output columns are `net_load_p10, net_load_p50, net_load_p90`. Enforce monotonic order after prediction (sort the three).
- **Model B:** `LGBMClassifier(is_unbalance=True)`, output `spike_prob`. Choose the decision threshold on validation to maximise F1, subject to recall ≥ 0.6, and log it.
- MLflow: `mlflow.set_experiment(f"/Users/{current_user}/gridwise")` (with `current_user = spark.sql("select current_user()").first()[0]`), `mlflow.set_registry_uri("databricks-uc")`. Register `grid.ml.net_load` and `grid.ml.spike` **with a signature** (`infer_signature(X_val, preds)`) and an `input_example`. Set alias `champion` only if the new model beats the current champion on validation (MAPE for A, PR-AUC for B), or if no champion exists yet.
- **Metrics to log.** A: `val_mape`, `test_mape`, `test_wmape`, `test_rmse`, `test_mae`, `test_p10_p90_coverage`, `baseline_test_mape`, `test_mape_by_month` (artifact). B: `val_pr_auc`, `test_pr_auc`, `test_roc_auc`, `test_recall`, `test_precision`, `threshold`, `test_base_rate`. Artifacts: feature importance and SHAP summary PNG. Also write one row per run to `gold.model_metrics(run_id, model, metric, value, split, logged_at)`.
- Inference (3.6) reads `gold.features WHERE is_forecast_row` (48 rows), and every feature is already populated by contract.

---

## 4. Acceptance criteria (SQL-testable; each notebook asserts these and reports them in its exit JSON)

### Silver (`02_silver`)
| check | rule |
|---|---|
| unique grain | `count(*) = count(distinct ts_utc)` in `grid_hourly` and `weather_hourly` |
| continuity | `count(*) = timestampdiff(HOUR, min(ts_utc), max(ts_utc)) + 1` (no missing rows) |
| coverage | `min(ts_utc) = '2023-01-01 00:00Z'`; `max(ts_utc) = anchor_ts + 48h`; `anchor_ts ≥ now − 6h` |
| forecast rows | exactly 48 rows with `is_forecast_row`; their `temp_f` is non-null in ≥ 95% of rows |
| EIA rescue | 2023 `demand_mw` null rate < 1% |
| null rates (actual rows) | `demand_mw`, `net_load_mw` < 1%; `price_usd_mwh` < 1% (gap 2026-11-01..06 allowed); `temp_f` < 2% |
| plausibility | `demand_mw` within 30–95 GW; `net_load_mw` within 3–80 GW; `wind_mw` within 0–40 GW; `solar_mw` within 0–40 GW (v1.1: raised from 35 GW, observed max 34,982 MW) (assert 0 rows outside, display min/max) |
| price sanity | price within −250..5,100 $/MWh (system cap 5,000) |
| DST | `dst_fallback_distinct_utc = true` for all 3 years; spring-forward days have 23 local hours |
| src mix | the last 24 actual hours have `src_demand = 'ercot'` |
| DQ table | `silver.dq_checks(check, value, pass)` with missing hours per month per column (displayed) |

### Gold (`03_gold`)
| check | rule |
|---|---|
| grain | `gold.features` row count equals `silver.grid_hourly` row count; unique `ts_utc` |
| leakage guard | for a sample row `t`: `nl_lag_48h = net_load_mw` at `t−48h` (exact join check); `nl_roll24_mean_l48` uses only rows ≤ t−48 |
| forecast rows | the 48 forecast rows have non-null `nl_lag_48h` (≥ 46/48 rows) and non-null calendar data |
| feature nulls | each `FEATURES_A` column < 3% null on actual rows from 2023-01-15 onward |
| strain | `strain_index` within [0,100]; per month, ≈ 15% red (±3 pp), ≈ 25% yellow (±3 pp) |
| spikes | overall `avg(is_spike)` within 1–6%; yearly rates match §0.6 ±0.3 pp |
| holidays | `is_holiday` = 1 on 2024-07-04 and 2025-12-25 |

### ML (`04_train`)
| check | rule |
|---|---|
| Model A (v1.1, amended) | `test_mape` ≥ 30% relatively better than `baseline_test_mape`; `test_wmape` ≤ 10%; P10–P90 coverage (CQR-calibrated on val) within 70–90%. The original `< 5%` MAPE target is not reachable for net load at a 48 h lag floor and is reported as a contract deviation. |
| Model D (v1.1, new) | `grid.ml.demand`: 3-quantile LightGBM on `FEATURES_A` + demand lags/rolls ≥ 48 h (computed from Silver by timestamp); `test_mape < 5%` (this is the headline < 5% number). Display-only net load = `demand_p50 − wind_forecast_mw − solar_forecast_mw` on forecast rows, never a model input. |
| Model B | `test_pr_auc` > 3× base rate; recall and precision reported at the chosen threshold |
| registry | `grid.ml.net_load@champion`, `grid.ml.spike@champion` and `grid.ml.demand@champion` resolve; `mlflow.pyfunc.load_model("models:/grid.ml.net_load@champion").predict(features_of_48_forecast_rows)` returns 48×3 with no nulls |

---

## 5. Hand-off order

`02_silver` → `03_gold` → `04_train`. The Gold engineer can write SQL against the Silver schema above before Silver lands. The ML engineer can build on a provisional `gold.features` and must not rename columns. Compute budget (Free Edition): **at most 2 full runs per notebook per iteration**. Test SQL on the warehouse (`worker.sql`) before spending a notebook run.


---

## 6. Status (Nov 7, after round 2: approved)

**Result:** Phase 2 (Silver, Gold) and Phase 3.1–3.4 (training, registry) pass every check. `all_pass = true` in `02_silver`, `03_gold` and `04_train`.

**Deviations from v1.0**
- Model A's test MAPE is 11.79 %, against the original target of < 5 %. Under the amended v1.1 criteria it passes: 36 % better than the 18.55 % baseline, wMAPE 9.85 %, coverage 80.7 %. The < 5 % headline is now Model D (demand), at 3.45 %.
- The solar plausibility band was raised from 0–35 GW to 0–40 GW, because the observed max is 34,982 MW.
- Model B leaves out ERCOT's wind and solar forecasts, because they exist only for recent days. It uses Model A's P50 instead.
- Feature lags start at 48 h. The 1 h and 24 h lags exist only as `diag_*` columns and are banned from the models.

**Open items**
1. *(Silver / Phase 1)* 24 h of EIA wind and solar are missing (2025-12-05 06Z to 12-06 05Z), so net load is null for those hours (3.2 % of Dec 2025, within the 5 % tolerance). Backfilling needs ERCOT Public API credentials from apiexplorer.ercot.com. 4 single solar hours in 2024 are also missing, within tolerance.
2. *(ML / 3.6)* Model A's P50 disagrees with the display net load on the forecast rows (26.6 GW vs 38.3 GW at 2026-11-07 21Z). Model A's MAPE is also 16.7–17.2 % in Oct and Nov. Both should go into `gold.forecasts`. Strain should use the display net load when ERCOT forecasts exist, recorded in a `strain_source` column.
3. *(ML / Phase 4)* Model D's demand features are built inside `04_train` only. Move them into a shared helper so inference can score Model D.
4. *(Gold)* Fix the notes: the price-gap fill count is 121 of 121, not 120 of 121 (the 1 was an off-by-one). Optionally add a `price_gap_2026_11_null_hours = 0` check.

**UPDATE 2026-11-07 (Phase 3 handoff, Analytics Engineering): open item 3 resolved, Model D features now in Gold**
- `gold.features` (built by `03_gold`) adds 6 columns: the target `y_demand_mw` (`silver.demand_mw`, NULL on the 48 forecast rows) and Model D's 5 extra features: `demand_lag_72h`, `demand_lag_336h`, `demand_roll24_mean_l48`, `demand_roll168_mean_l48`, `demand_roll168_max_l48`. They follow the lag-48 floor: exact time-based joins at t−72 h and t−336 h, and time-range windows over [t−71 h, t−48 h] and [t−215 h, t−48 h] that need ≥ 50 % non-null inputs. So `FEATURES_D = FEATURES_A + DEMAND_EXTRA` is read from Gold for every row.
- All 48 forecast rows carry all 5 features (48/48 each), so inference can score `grid.ml.demand@champion` straight from `gold.features`. On actual rows from 2023-01-15 onward, the null rate is 0 %.
- New `03_gold` checks, written to `gold.dq_checks` with `all_pass = true`: `forecast_rows_demand_features` (48/48 per feature, `y_demand_mw` NULL on forecast rows) and `leakage_demand_extra_sample` (498 sampled rows, including every forecast row, recomputed independently from Silver: 0 lag mismatches, max roll difference 3.6e-11 MW, no input after t−48 h). The `feature_null_pct_max` check now also covers these 5 columns.
- `04_train` no longer builds these features from Silver. It reads them and `y_demand_mw` from `gold.features`, and asserts that the columns exist. The Gold values match the old pandas build on all 33,813 rows: lags and max are exact, rolling means differ by ≤ 3e-11 MW, and no null pattern differs. **The feature values did not change, so Model D was not retrained.** `grid.ml.demand@champion` (test MAPE 3.45 %) is still valid. The `@champion` logic is unchanged for the next scheduled retrain.

**UPDATE 2026-11-08 (Phase 3.5–3.7 wrap-up, PM): deviations and decisions**
- **Strain source (resolves open item 2):** `gold.forecasts.net_load_used` = Model D `demand_p50` − ERCOT `wind_fcst_mw` − ERCOT `solar_fcst_mw` whenever ERCOT forecasts exist (`strain_source = 'demand_minus_ercot_renewables'`, 48/48 rows in run_ts 2026-11-07 20Z). Otherwise it falls back to Model A P50 (`'model_a'`). Model A's P10/P50/P90 stay in the table as columns. Rule enforced in `05_predict`: no green hour when the alternative net load is high (`no_green_when_alt_high`, 40 high hours, 0 green).
- **Band:** under the demand source, `band_low = demand_p10 − wind − solar` and `band_high = demand_p90 − wind_p80 − solar_p80` (point forecast if P80 is null), clamped to contain `net_load_used` (`band_source = 'model_d_plus_ercot_p80'`). Under Model A it is the CQR band (`'model_a_cqr'`). New columns: `demand_p10`, `demand_p90`, `wind_fcst_p80_mw`, `solar_fcst_p80_mw`, `band_source`, added with ALTER TABLE ADD COLUMNS.
- **Idempotency:** 05, 06 and 07 delete and re-append (or MERGE) by `run_ts` / `date`, so a rerun never duplicates a batch.
- **Drivers (3.5):** SHAP runs on the model behind `strain_source`. For the demand source, ERCOT wind and solar enter as additive drivers measured against their training means, so `base_mw + Σ shap_mw = net_load_used` exactly. Known UX issue: the top driver is low wind in 48/48 hours, and solar shows as "raises" at night. The UI maps these to plain copy.
- **Report card (3.7):** backtest rows score Model A P50 (`basis = 'model_a_p50'`) over the 04_train test window (91 days, MAPE 11.74 %, coverage 80.6 %, demand MAPE 3.44 %, recall 42/52). The displayed method can't be backtested until ERCOT forecast history builds up (Silver has it only since ~11-04). Live rows are graded on `net_load_used` once actuals arrive. The spike recall differs: 0.7917 in the champion run vs 0.8077 in `gold.model_metrics` and the report card. Still to explain, probably a different threshold or test window.
- **Open, blocks closing 3.6:** Model D demand on forecast rows appears ~4–6 GW low (h1 49.7 GW vs 53.1 GW observed at anchor and rising; the first 24 h are below both yesterday's and last week's same hour), because the lag-48 floor hides the last 47 h. Decision: anchor in `05_predict` by scoring `grid.ml.demand@champion` on the last 6 actual rows, `r` = recency-weighted mean residual, and add `r·exp(−h/24)` to `demand_p10/p50/p90`. Store it as `demand_anchor_adj_mw`. Check that |h1 demand − anchor actual| < max(5 %, 2.5 GW). Then recompute strain/level/band, and have 06 attribute the adjustment as a "Recent demand level" driver. In the same rerun, change `LOW_CONF_REL_WIDTH` from 0.20 (flags 48/48) to 0.50 (≈27 %). Then rerun 06 and 07.
- **Deferred to next retrain:** Model D's P90 is lopsided upward and sits at 52,616 MW in 8 overnight hours. Check the 04_train quantile calibration. The 04_train edit that reads features from Gold has not run yet.
