# 🤖 ml/: Machine Learning

Databricks notebooks that train, register, run and explain the forecasting models. Everything is tracked in **MLflow** and registered in **Unity Catalog** with an `@champion` alias.

| Notebook | Output | What it does |
|---|---|---|
| `04_train` | `grid.ml.net_load`, `grid.ml.spike`, demand model, `gold.model_metrics` | Time-based split, seasonal-naive baseline, LightGBM models; `@champion` moves only on improvement |
| `05_predict` | `gold.forecasts` | Next 48 hours: net load P10/P50/P90, demand, spike probability, strain index + level, `strain_source` |
| `06_explain` | `gold.forecast_drivers` | Top-3 SHAP drivers per forecast hour (powers "Why Red?") |
| `07_report_card` | `gold.report_card` | Grades forecasts against actuals: live rows and a 91-day backtest |
| `08_ripple` | `gold.shift_scenarios`, `gold.shift_scenario_curves` | "What if Texas shifted?" grid: 210 scenarios, each re-scored with Model B (powers `/api/simulate`) |
| `09_advice` | `gold.daily_advice` | Daily plan + "Why Red?" sentences: Gemini when the secret exists, rule-based otherwise (powers `/api/advice`) |

## Models

| Model | Predicts | Test result |
|---|---|---|
| **A: net load** | demand − wind − solar, next 1–48 h, P10/P50/P90 | MAPE 11.8% (baseline 18.6%), band coverage 80.7% |
| **D: demand** | total demand, next 1–48 h | MAPE 3.45% (baseline 6.5%) |
| **B: spike** | P(real-time price > $100/MWh) | recall 0.81, PR-AUC 0.21 (base rate 2.4%) |

**Strain source:** live strain uses *demand (Model D) − ERCOT's wind & solar forecasts*, with Model A as the fallback when ERCOT forecasts are missing. Each forecast row records which one it used.

**No-leakage rule ("lag-48 floor"):** features only use history at least 48 hours old, plus calendar data and weather at the target hour, so every feature exists at forecast time.

## Ripple (`08_ripple`)

For the latest forecast batch it precomputes **7 participation levels (1–25 %) × 5 kWh per home (1–8) × 2 from-windows
(`16-20`, `17-21`) × 3 to-windows (`22-02`, `00-04`, `10-14`)** = 210 scenarios. Windows are local Chicago hours,
`a-b` = hours a … b−1, wrapping past midnight (all 4 h).

- **Load moved:** `RIPPLE_RESIDENTIAL_METERS = 9,000,000` homes (fixed constant). Energy per evening =
  `pct × homes × kwh / 1000` MWh, i.e. `shift_mw = energy / 4 h` taken off every from-window hour and added to every
  to-window hour (energy conserved). Applied to every evening inside the 48 h (normally 2).
- **Tonight's partial window:** if the run comes after the from-window has started (e.g. `run_ts` 22Z = 4 PM CST,
  horizon from 5 PM), the remaining hours of tonight's window are still shifted at the same `shift_mw`, so that
  evening moves `shift_mw × remaining hours`. Without this, afternoon runs could never cut the 48 h peak (often tonight
  6 PM). Only a window cut off at the horizon start is used partially. `n_shift_days` counts a partial evening as 1;
  `energy_shifted_mwh` is the energy actually moved.
- **Day pairing:** each evening is paired with the nearest *unused* in-horizon to-window: `22-02` = same night,
  `00-04` = the night after, `10-14` = usually the next late morning.
- **Re-scored, not scaled:** Model B (the exact version used by `05_predict`) is re-run with `net_load_p50` = the
  shifted net load, then strain = month percentile + 15 if spike > 0.5, as in 05. A built-in check re-scores the
  unshifted curve and must reproduce `gold.forecasts` exactly.
- **Outputs:** per scenario `red_hours_before/after`, `peak_mw_before/after`, `peak_reduction_mw` (signed),
  `max_spike_before/after`, `peakers_avoided = max(0, peak_reduction_mw) / 200` (one ≈200 MW gas peaker; a display
  heuristic), and `rebound` (the new 48 h peak sits in the to-window, so the moved load became the peak). Curves table:
  48 rows per scenario with `before_mw/after_mw`, strain, level and spike before/after.
- **Checks (hard, fail the task):** energy conserved, 48 rows per scenario, unshifted re-score equals
  `gold.forecasts` (these three are asserted in memory *before* writing), plus 210 / 10,080 rows, unique keys, value
  ranges and the peakers formula.
- **Warnings (exit JSON `warnings` / `warned`, never in `all_pass`):** every scenario shifts, peak never rises with
  more participation unless it is a rebound, from-window maximum strictly falls, demo scenario (5 %, 3 kWh,
  16-20 → 22-02) cuts the peak. These depend on the time of day and the weather.

## Advice (`09_advice`)

- **Rules always run first:** avoid windows = runs of red hours or spike prob ≥ 30 %; best windows = calmest 3 h
  blocks with no avoid hour (plus the best overnight block for EVs and the best daytime block for laundry).
  `best_hours` / `avoid_hours` always come from these rules, so the highlighted hours match the models.
- **Why Red?:** one sentence per red hour from its top-3 drivers in `gold.forecast_drivers`; the templates turn
  "ERCOT solar raises net load" at night into "the sun is down", and low wind into "wind is only X GW".
- **Gemini:** `gemini-2.5-flash` over REST (`x-goog-api-key` header, JSON response schema) writes the headline,
  tips and red-hour sentences from compact JSON (48 h, rule windows, driver facts). Its output is validated (icons
  from a fixed emoji set, lengths, red-hour keys); a missing secret, failed call or bad shape falls back to the rule
  plan (`generated_by = 'rules'`), and red hours it skipped get the rule sentence.
- **Key:** `dbutils.secrets.get('gridwise', 'gemini_api_key')`. Create the scope once with
  `python -m tools.setup_secrets` (run by a human). Until then the notebook writes the rule plan.
- **Checks:** shape invariants (one row, JSON shape, icons, hours are forecast hours, best/avoid disjoint, no red
  hour in best, a sentence for every red hour, date = tomorrow) fail the task. `best_hours_nonempty`,
  `tips_at_least_2` and `gemini_used` are warnings only, so a rules-only day still keeps the Job green.
- Gemini output is scrubbed of control characters (it sometimes returns the en dash in labels as a backspace).
- `why_red_json` keys are UTC `YYYY-MM-DDTHH:MM:SSZ`; `best_hours_json` / `avoid_hours_json` are local ISO times
  with offset.

## Run

```powershell
python -m tools.deploy --run 04_train        # retrain (weekly / manual)
python -m tools.deploy --run 05_predict 06_explain 08_ripple 09_advice 07_report_card   # hourly chain
python -m tools.setup_secrets                 # once, by a human: secret scope 'gridwise' from .env
```
