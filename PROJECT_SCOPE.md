# GridWise: Texas Grid Stress Forecaster

> **One-liner:** GridWise forecasts when Texas's power grid will be stressed and tells you exactly when to run your dryer, charge your EV, or crank the AC, so you save money and help keep the lights on.

**Event:** TAMUhack 26
**Tracks:** Databricks (main), Gemini, Tiger Data, Vultr, GoDaddy Registry
**Related docs:** [TECH_STACK.md](TECH_STACK.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [.env.example](.env.example)

---

## 1. Topic

An AI-powered platform that forecasts ERCOT grid strain and electricity price spikes 24–48 hours ahead, then tells Texans when to shift their energy use to save money and help prevent outages.

## 2. Problem

- Texas runs on an isolated grid (ERCOT) that gets dangerously tight on hot summer evenings and extreme winter days.
- Wholesale prices can spike 50–100x within hours when supply runs short.
- Regular people have no simple way to know when the grid will be strained or what to do about it.

## 3. Solution

Databricks pipeline → forecast models → plain-English advice from Gemini → a live dashboard showing tomorrow's red, yellow and green hours, plus the best times to run appliances.

## 4. Target Users

| Segment | Why they care |
|---|---|
| **Primary:** Texans on time-of-use, "free nights" or variable-rate plans, and EV owners | Shifting usage saves them money directly |
| **Secondary:** Anyone who wants to help prevent grid emergencies | Collective load-shifting lowers peak strain |

---

## 5. Scope

### In scope

- Historical grid data (2023 → now): hourly demand, wind and solar from EIA-930, plus ERCOT real-time prices (gridstatus)
- Live ERCOT data every hour via gridstatus: load, prices, and wind/solar actuals with 7-day forecasts
- Hourly weather for Houston, DFW, Austin and San Antonio
- Medallion pipeline in Databricks (Bronze / Silver / Gold), scheduled hourly
- **Model A:** net load forecast for the next 24–48 hours
- **Model B:** price spike probability per hour
- Strain index (0–100) with green / yellow / red levels
- Gemini-generated daily advice and a simple Q&A chat
- Genie space for natural-language questions about grid history
- Dashboard: strain timeline, spike risk, best-hours card, advice panel, history charts
- Served through Tiger Data, hosted on Vultr, live on a GoDaddy domain
- **Novel feature 1:** Ripple, a what-if load-shift simulator (see §6)
- **Novel feature 2:** "Why Red?" explainable alerts and a forecast report card (see §6)

### Out of scope (deliberate)

- Per-household bill calculations or retail plan comparisons
- Zone-level or nodal forecasts (we forecast system-wide ERCOT)
- Smart-home integrations or automatic appliance control
- User accounts, SMS or push alerts
- Solana rewards (stretch only)

---

## 6. Novel Features

### Novel Feature 1: Ripple, the "What If Texas Shifted?" Simulator

**The question it answers:** *"If 5% of Texas households moved their dryer and EV charging from 6pm to 10pm tomorrow, would the red zone go away?"*

Most grid apps tell one person what to do. Ripple shows what happens when **many people act together**. It turns individual advice into a measurable collective result.

**How it works**

1. The user sets three sliders: **participation %** (1–25%), **kWh shifted per household** (1–10 kWh), and **from/to windows** (e.g. 4–8pm → 10pm–2am).
2. Shifted load = participation × ~9M residential meters (configurable) × kWh, spread across the windows.
3. That load is subtracted from forecast net load in the peak window and added back off-peak.
4. The modified net-load curve goes back through **Model B** and the **strain index**, so the result comes from the real models, not a made-up multiplier.
5. The output shows the before/after curves, the peak MW reduction, the drop in spike probability (e.g. 70% → 38%), the change in red hours, and a relatable comparison ("≈ 4 gas peaker plants not needed").

**Databricks angle:** a batch job precomputes a scenario grid (participation × kWh × window) into `gold.shift_scenarios` each run, so the slider responds instantly. Custom values can call a small Model Serving endpoint.

**Why judges care:** it uses both models in a closed loop, it's interactive in the demo, and it reframes the product from "saves you money" to "a coordinated demand-response tool."

---

### Novel Feature 2: "Why Red?" Explainable Alerts + Forecast Report Card

**The question it answers:** *"Why is 6pm tomorrow red, and should I trust this forecast?"*

Forecasts are only useful if people trust them. Most dashboards show a red bar and nothing else. GridWise explains each alert and keeps a public record of how accurate it has been.

**How it works**

1. **Drivers:** SHAP values from the LightGBM net-load model give the top 3 drivers for every forecast hour, e.g. *DFW at 104°F (+2.1 GW)*, *wind dropping to 3 GW (+1.4 GW)*, *solar ramping down at sunset (+3.0 GW)*. These are stored in `gold.forecast_drivers`.
2. **Narration:** `ai_query()` with Gemini turns the drivers into one plain sentence: *"6pm is red because a DFW heat wave is pushing AC demand up just as solar fades and the wind dies down."*
3. **Confidence bands:** quantile LightGBM (P10 / P50 / P90) draws a shaded uncertainty band on the timeline. Wide bands get flagged as low confidence.
4. **Report card:** every day, yesterday's forecast is scored against actuals (MAPE, spike hits and misses) and shown on the dashboard: *"Yesterday: 3.2% error, caught 2 of 2 spike hours."*

**Databricks angle:** SHAP and quantile models are logged in MLflow, drivers go to Gold, Gemini runs in-pipeline via AI Gateway, and the report card is a scheduled evaluation task in the same Job.

**Why judges care:** explainable ML, honest uncertainty, and continuous evaluation in production are signs of mature ML engineering that hackathon projects rarely show.

---

## 7. Phases

Full step-by-step checklist (1.1 → 6.4): **[PHASES.md](PHASES.md)**. Everything runs on free tiers, including Databricks **Free Edition**.

| Phase | Time | Work | Checkpoint |
|---|---|---|---|
| **1. Setup & Ingestion → Bronze** | 2 hr | Free accounts and keys; UC catalog, schemas and volumes; connectivity check; worker backfills 2023 → now (EIA-930, ERCOT price archive, Open-Meteo) and pulls live ERCOT data; Auto Loader → Bronze | Bronze tables are queryable |
| **2. Silver & Gold** | 2 hr | Hourly UTC, DST check, dedupe, history + live merge, weather join; net load, strain index, spike flag, feature table | One clean Gold feature table, one row per hour |
| **3. Machine Learning** | 2.5 hr | Baseline; Model A (P10/P50/P90); Model B; MLflow + UC registry; SHAP; batch inference; report card | Tomorrow's forecast plus a MAPE to cite |
| **4. AI Layer & Automation** | 1.5 hr | Gemini advice + "Why Red?"; Ripple scenarios; Genie space; Databricks Job; hourly GitHub Actions trigger | Pipeline runs end to end on its own |
| **5. Serving & Dashboard** | 4 hr (start during Phase 3) | Tiger Data + continuous aggregates; FastAPI; dashboard with Ripple, Why Red?, report card, chat; deploy on Vultr + GoDaddy | Live on the GoDaddy domain |
| **6. Ship** | 1.5 hr | Architecture image, 2–3 min demo video, Devpost write-up, final checks | Submitted |

### Cut order if behind

1. Solana (stretch)
2. Model B (Ripple then shows MW reduction and strain only)
3. Ripple custom inputs (keep precomputed scenarios)
4. Chat box
5. Vultr (host on Vercel instead)
6. Tiger Data (query Databricks SQL directly)

**Never cut:** the pipeline, Model A, Gemini advice, the dashboard, "Why Red?" drivers.

---

## 8. Success Criteria

- [ ] The pipeline runs end to end on a schedule with no manual steps
- [ ] Net load forecast MAPE under ~5% on a held-out test period
- [ ] The spike model catches most real spike hours on the test set (report recall and precision)
- [ ] P10–P90 band covers ~80% of actuals on the test set (calibration)
- [ ] The dashboard shows tomorrow's forecast with clear, actionable advice
- [ ] Every red hour has a "Why Red?" explanation
- [ ] Ripple shows a model-backed before/after for at least one scenario
- [ ] Genie answers 5 demo questions correctly

## 9. Demo Script (2–3 min)

1. **Hook:** "Feb 2021, Winter Storm Uri: 4.5M Texas homes lost power. The grid still gets tight every summer."
2. **Forecast:** "Here's tomorrow. 6pm is a red zone with a 70% spike risk."
3. **Why Red?:** hover the bar to see the drivers and Gemini's one-line explanation, plus the confidence band.
4. **Advice:** "Here's what Gemini tells you to do: pre-cool before 4pm, run the dryer after 10pm."
5. **Ripple:** drag participation to 5% and watch the red zone turn yellow and spike risk drop to 38%.
6. **Trust:** show the report card: "Yesterday we were within 3.2%."
7. **Genie:** "What was the most strained hour of summer 2025?" answered live.
8. **Architecture:** a 10-second flash of the diagram showing Databricks at the center.

## 10. Genie Demo Questions

1. What was the most strained hour of summer 2025?
2. How does wind output change on peak-demand days?
3. How many hours had real-time prices above $100/MWh last August?
4. What's the average net load at 6pm in July vs. January?
5. Which weekday has the highest average strain index?
