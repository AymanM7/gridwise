# 🤖 ml/: Machine Learning

Databricks notebooks that train, register, run and explain the forecasting models. Everything is tracked in **MLflow** and registered in **Unity Catalog** with an `@champion` alias.

| Notebook | Output | What it does |
|---|---|---|
| `04_train` | `grid.ml.net_load`, `grid.ml.spike`, demand model, `gold.model_metrics` | Time-based split, seasonal-naive baseline, LightGBM models; `@champion` moves only on improvement |
| `05_predict` | `gold.forecasts` | Next 48 hours: net load P10/P50/P90, demand, spike probability, strain index + level, `strain_source` |
| `06_explain` | `gold.forecast_drivers` | Top-3 SHAP drivers per forecast hour (powers "Why Red?") |
| `07_report_card` | `gold.report_card` | Grades forecasts against actuals: live rows and a 91-day backtest |

## Models

| Model | Predicts | Test result |
|---|---|---|
| **A: net load** | demand − wind − solar, next 1–48 h, P10/P50/P90 | MAPE 11.8% (baseline 18.6%), band coverage 80.7% |
| **D: demand** | total demand, next 1–48 h | MAPE 3.45% (baseline 6.5%) |
| **B: spike** | P(real-time price > $100/MWh) | recall 0.81, PR-AUC 0.21 (base rate 2.4%) |

**Strain source:** live strain uses *demand (Model D) − ERCOT's wind & solar forecasts*, with Model A as the fallback when ERCOT forecasts are missing. Each forecast row records which one it used.

**No-leakage rule ("lag-48 floor"):** features only use history at least 48 hours old, plus calendar data and weather at the target hour, so every feature exists at forecast time.

## Run

```powershell
python -m tools.deploy --run 04_train        # retrain (weekly / manual)
python -m tools.deploy --run 05_predict 06_explain 07_report_card   # hourly chain
```
