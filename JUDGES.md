# 🎤 GridWise: Judge Walkthrough

A script for presenting GridWise to judges: what to say for each part of the dashboard, which numbers to quote, and how to answer the hard questions.
Companion docs: [DASHBOARD.md](DASHBOARD.md) (architecture + user guide) · [ARCHITECTURE.md](ARCHITECTURE.md) · [PIPELINE.md](PIPELINE.md)

---

## ⏱️ The 30-second pitch

> "Texas runs its own power grid. When it gets tight, like Winter Storm Uri or a summer evening when solar fades, prices can jump 50 to 100 times and the grid gets fragile. ERCOT publishes tons of data, but nobody can read it.
>
> **GridWise forecasts when the Texas grid will be stressed and when prices will spike, 48 hours ahead, and tells you in plain English when to run your dryer, charge your EV or pre-cool your house.**
>
> It's a full lakehouse on **Databricks** with three ML models, explained hour-by-hour with SHAP, advice written by **Gemini**, served from **Tiger Data**, and a simulator that shows what happens if thousands of Texans shift a little."

---

## 🗺️ Demo order (2–3 minutes)

| # | Section | Time | One-line takeaway |
|---|---|---|---|
| 1 | Hero / verdict | 15 s | "Tomorrow at a glance" |
| 2 | 48-hour strain timeline | 25 s | "Every hour, colored by strain, with honest uncertainty" |
| 3 | Why this color? | 25 s | "Every red hour explains itself" *(novel)* |
| 4 | Best hours + Your plan | 20 s | "Turns a forecast into actions" |
| 5 | Spike risk | 10 s | "When your bill could jump" |
| 6 | Ask GridWise (chat) | 20 s | "Ask in plain English; answers light up the timeline" |
| 7 | Ripple | 30 s | "Small shifts × many homes = gas plants avoided" *(novel)* |
| 8 | Report card + history | 15 s | "We grade ourselves every day" |
| 9 | Behind the scenes | 20 s | Databricks Job → Tiger → FastAPI, plus Genie |

**Before the demo:** run `python -m tools.dev`, open http://localhost:3000, scroll to the top. Backup: `python -m tools.dev --fixtures` runs on bundled real data with no internet.

---

## 1. 🚦 Hero: the verdict

**Point at:** the verdict line, the strain ring, the green/yellow/red hour chips, the "Live" pill.

**Say:**
> "This is the whole answer in five seconds. Tomorrow has 18 red hours, strain peaks at 6 pm, and there's a 71% chance of a price spike at 5 pm. The ring is the peak strain on a 0–100 scale, and the Live pill shows how fresh the data is."

**If asked "what's strain?":**
> "We forecast **net load**: demand minus wind minus solar. That's what gas plants have to cover, and it drives stress and prices better than raw demand. Strain is the percentile of that net load compared with the same month over the last three years, bumped up if a price spike is likely. Green is under 60, yellow 60–85, red over 85."

---

## 2. 📊 48-hour strain timeline

**Point at:** the bars, the grey band, the dotted caps, then **tap a red hour**.

**Say:**
> "Each bar is one hour. Height is forecast net load, color is strain. The grey band is our P10 to P90 range: we're honest about uncertainty, and hours where we're unsure get a dotted cap. Tap any hour and it explains itself."

**Tech behind it:** **Model A**, LightGBM quantile regression for P10/P50/P90, 1–48 hours ahead.
- **Quote:** test MAPE **11.8%** vs **18.6%** for the naive baseline; **80.7%** of actuals land inside the band (target 80%).

---

## 3. ❓ Why this color? *(Novel feature #1)*

**Point at:** the three driver rows with ± GW bars, the sentence, the confidence meter.

**Say:**
> "Most forecasts are black boxes. Ours explains every hour. Saturday 5 pm is red because wind drops to 4.8 GW, which adds 8.2 GW of net load, and solar is fading, which adds another 5.9. Red bars push strain up, green bars ease it. Then there's a plain-English sentence and a confidence meter."

**Tech behind it:** **SHAP** values computed on Databricks for every forecast hour, translated into plain language. The sentence is written by **Gemini**, with a rule-based fallback.

---

## 4. ✅ Best hours + 🤖 Your plan

**Point at:** the best/avoid windows, then the plan items and the Gemini/Rules badge.

**Say:**
> "A forecast is only useful if it changes what you do. Best hours shows the calmest windows; Avoid shows the risky ones with their spike odds. Your plan turns that into three to five concrete actions: pre-cool before 4 pm, run laundry 10 am to 1 pm, charge the EV 1 to 4 am."

**Tech behind it:** a Databricks notebook (`ml/09_advice.py`) sends the forecast to **Gemini**, which writes the plan; if Gemini is unavailable a rules engine writes it, and the badge shows which one did.

---

## 5. 💸 Spike risk

**Point at:** the curve crossing the 50% line.

**Say:**
> "This is the chance each hour that real-time wholesale prices go over $100 a megawatt-hour. If you're on a variable-rate or 'free nights' plan, this is when your bill hurts."

**Tech behind it:** **Model B**, a LightGBM classifier.
- **Quote:** catches **81%** of spike hours (recall 0.81). Spikes happen only about **2.4%** of the time, so it's a hard, imbalanced problem: our PR-AUC of 0.21 is about **9× better than chance**.

---

## 6. 💬 Ask GridWise

**Do:** tap *"I need 40 kWh in my car by 7 am. When should I charge?"*

**Say:**
> "You can just ask. The question goes to Gemini along with our live 48-hour forecast, and the hours it recommends light up on the timeline."

**Tech behind it:** `POST /api/chat`. FastAPI sends the question plus the forecast and plan to **Gemini 2.5 Flash** and gets back an answer and a list of hours. If Gemini fails, a rules engine answers, so the demo never breaks.

---

## 7. 🌊 Ripple: what if Texas shifted? *(Novel feature #2)*

**Do:** drag *Homes participating* from 5% up to 15–25%; switch *To* between solar hours and overnight.

**Say:**
> "This is the part we're proudest of. One household shifting its dryer doesn't matter. But if 15% of Texas homes moved 5 kWh out of the 5–9 pm peak into the solar hours, the 48-hour peak drops by **1.7 gigawatts**, about **17 gas peaker plants** that wouldn't need to fire. Every number is re-scored by our real models, not a guess."

**Tech behind it:** a Databricks notebook (`ml/08_ripple.py`) precomputes **210 scenarios** (participation × kWh × from-window × to-window) on about 9 million Texas homes, re-scores spike risk with Model B, and conserves energy exactly. The sliders snap to the nearest scenario, so results are instant.

**Honest caveat if asked:** the spike model barely reacts to these shifts, so Ripple leads with the **peak cut** and **peakers avoided** rather than spike risk.

---

## 8. 📋 Report card + 📈 Last 30 days

**Point at:** the error tiles, the "inside band" meter, the 7-day table, the 30-day chart.

**Say:**
> "We grade ourselves every day. Yesterday's net-load error, whether we caught the price spikes, and how often reality landed inside our band against an 80% target. The 30-day chart shows daily peaks and real-time prices, so you can see what a normal week looks like."

**Tech behind it:**
- **Report card:** a Databricks notebook (`ml/07_report_card.py`) compares our published forecasts with ERCOT actuals. Older days are backtests.
- **History:** a **Tiger Data continuous aggregate** (`actuals_daily`) over hourly actuals.

---

## 9. ⚙️ Behind the scenes (sponsor tracks)

**Say:**
> "Every number you just saw was made on Databricks, and the page never touches Databricks directly. It reads precomputed results from Tiger, so it loads in under half a second and costs zero compute per view."

```text
ERCOT · EIA-930 · Open-Meteo
        │  ingestion worker → Unity Catalog Volume
        ▼
DATABRICKS: Auto Loader → Bronze → Silver → Gold → Models A/B/D (MLflow) → SHAP → Ripple → Gemini advice
        │  one Databricks Job, 9 tasks: "gridwise-hourly"
        ▼
TIGER DATA (TimescaleDB hypertables + continuous aggregate)
        ▼
FASTAPI (8 endpoints, Gemini chat)  →  NEXT.JS DASHBOARD
```

### Track talking points

| Track | What to say | Show |
|---|---|---|
| **Databricks** | "A full medallion lakehouse: Auto Loader into Bronze; Silver is hourly UTC and daylight-saving safe; Gold has features and the strain index. Three LightGBM models are tracked in MLflow and served from Unity Catalog by their `@champion` alias. SHAP, Ripple and advice all run as one 9-task Databricks Job. And **Genie** lets anyone ask the grid's history in plain English." | The Databricks Job graph; ask Genie *"What was the most strained hour of summer 2025?"* |
| **Gemini** | "Gemini does two jobs: inside the pipeline it writes the daily plan and the 'Why red?' sentences, and live in the app it answers questions grounded in our forecast. It returns which hours to highlight, so the answer is visual, not just text." | Chat → highlighted hours |
| **Tiger Data** | "Tiger is our serving layer. Forecasts and actuals live in TimescaleDB hypertables, and the 30-day history is a continuous aggregate. The API reads only from Tiger, so the dashboard is fast and doesn't burn Databricks compute." | `/api/docs` → `/api/history` |
| **Vultr** | "The API and dashboard run in Docker Compose on a Vultr VM behind Caddy for HTTPS." | *(only once deployed: Phase 5.8)* |
| **GoDaddy** | "Served at our GoDaddy domain." | *(only once deployed: Phase 5.8)* |

> ⚠️ Only claim Vultr/GoDaddy once they are actually deployed. Until then, say "it's containerized and deploy-ready for Vultr."

---

## 🔢 Numbers to remember

| Metric | Value |
|---|---|
| Net-load forecast error (Model A, test MAPE) | **11.8%** (baseline 18.6%) |
| Actuals inside P10–P90 band | **80.7%** (target 80%) |
| Demand forecast error (Model D) | **3.45%** MAPE |
| Spike hours caught (Model B recall) | **81%** |
| Spike base rate | ~2.4% of hours |
| History loaded | Jan 2023 → today (~34k hours of EIA data, 134k price rows, 134k weather rows) |
| Ripple scenarios | **210**, about 9 M homes |
| Ripple headline | 15% of homes × 5 kWh → **−1.7 GW**, about **17 peakers** |
| API latency | < 0.5 s per endpoint |
| Databricks Job | 9 tasks, one command |

---

## 🧠 Likely judge questions

**"Why net load instead of demand?"**
> Gas plants cover demand minus wind and solar. A hot, windy day can be easy, and a mild evening with no wind and fading solar can be tight. Net load is what actually drives stress and price spikes.

**"How do you know it's accurate?"**
> We hold out a test period: 11.8% MAPE vs 18.6% for a naive baseline, and our uncertainty band captures 80.7% of reality, right on its 80% target. The report card re-grades us every day against what ERCOT actually measured.

**"How is this different from ERCOT's own dashboard?"**
> ERCOT shows raw supply and demand for operators. We forecast strain and price spikes for regular people, explain *why* each hour is red, tell you *what to do*, and show the collective impact with Ripple.

**"What about daylight saving time?"**
> ERCOT reports in Central time, so every November 1 am happens twice and every March 2 am doesn't exist. We keep the original offset, convert everything to UTC before aggregating, and the Silver notebook includes a check that proves it.

**"Why precompute Ripple instead of running the model live?"**
> Speed and cost. 210 scenarios cover the slider space, each re-scored by the real models in Databricks, so the page responds instantly and uses no compute per drag.

**"What happens if Gemini or the API goes down?"**
> Everything has a fallback. If Gemini fails, a rules engine writes the plan and answers chat, and the badge says so. If the API is down, the page loads a bundled snapshot of real data with an "outdated" notice.

**"Who would pay for this?"**
> Retail electricity providers and EV-fleet or smart-home companies who want to shift load off peaks, plus demand-response programs. See [CUSTOMERS.md](CUSTOMERS.md).

**"What would you do next?"**
> Push notifications before red evenings, smart-thermostat and EV-charger integrations that act automatically, and a ZIP-code-level view.

**"What was hardest?"**
> Databricks Free Edition restricts outbound internet, so we built an ingestion worker that uploads into a Unity Catalog Volume and lets Auto Loader take over. And ERCOT only keeps a few days of wind and solar, so we used EIA-930 for three years of history.

---

## ✅ Pre-demo checklist

- [ ] `python -m tools.dev` → http://localhost:3000 loads, the Live pill is green
- [ ] Forecast is fresh (< 2 h). If not: `python -m ingestion.cli ingest --trigger-job`, then `python -m db.sync`
- [ ] Gemini has quota: the plan badge says **Gemini**, not Rules
- [ ] Ripple sliders respond; chat highlights hours on the timeline
- [ ] Databricks open in a tab: the Job run graph + Genie space ready
- [ ] `/api/docs` open in a tab
- [ ] Backup ready: `python -m tools.dev --fixtures` (works offline)
- [ ] Browser zoom ~90%, other tabs and notifications closed

---

*GridWise is an independent student project (TAMUhack 26), not affiliated with ERCOT. Forecasts are estimates, not official grid conditions.*
