# GridWise: End-to-End User Pipeline

How a person uses **gridwise.tech** from the moment they open it to the moment they act on it, and what the system does behind the scenes at each step.

> Related: [CUSTOMERS.md](CUSTOMERS.md) (who the users are) · [ARCHITECTURE.md](ARCHITECTURE.md) (system design) · [PHASES.md](PHASES.md) (build plan)
> The dashboard is built in **Phase 5**. This document describes the intended experience.

---

## The journey at a glance

```text
 ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
 │ 1. OPEN  │──►│ 2. SCAN  │──►│ 3. WHY?  │──►│ 4. PLAN  │──►│ 5. ASK   │──►│ 6. ACT   │──►│ 7. CHECK │
 │ the site │   │ tomorrow │   │ red hour │   │ Gemini   │   │ the chat │   │ shift    │   │ report   │
 │          │   │ timeline │   │ explained│   │ advice   │   │          │   │ usage    │   │ card     │
 └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
                                                    │
                                                    ▼
                                            ┌──────────────┐
                                            │ 🌊 RIPPLE     │  optional: "what if
                                            │ simulator    │  everyone shifted?"
                                            └──────────────┘
```

**Time for a typical visit: about 1 minute.** No account, no login, no install.

---

## What runs before the user arrives (every hour)

The user never sees this part. It's why the page is ready instantly with fresh data.

```text
  :07  Worker fetches ERCOT, EIA and Open-Meteo data ──► uploads to Databricks
  :10  Databricks Job:  Bronze → Silver → Gold
  :15  Model A (net load, P10/P50/P90) + Model B (spike risk) → gold.forecasts
  :17  SHAP "Why Red?" drivers · Ripple scenarios · Gemini daily advice
  :20  Sync to Tiger Data (fast database the website reads from)
       ──► the website now shows the new forecast
```

---

## Step 1: Open the site

**The user:** types `gridwise.tech` on a phone or laptop.

**What they see:** the dashboard loads in about a second, with a header showing **tomorrow's date** and an overall verdict, e.g.
> **Tomorrow: 🔴 Tight evening.** Strain peaks 5–8 pm · 70% spike risk at 6 pm

**Behind the scenes:**
```text
Browser ──► GoDaddy DNS ──► Vultr server (Caddy, HTTPS) ──► Next.js page
Next.js ──► FastAPI  GET /forecast?hours=48 , GET /advice ──► Tiger Data (ms) ──► JSON
```

---

## Step 2: Scan tomorrow's strain timeline

**The user:** looks at the 48 colored bars, one per hour.

```text
 🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟡🟡🔴🔴🔴🟡🟢🟢🟢🟢
 12a          6a            12p        4p   6p   8p          12a
 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ shaded band = how sure we are (P10–P90)
```

| Color | Strain index | What it means |
|---|---|---|
| 🟢 Green | under 60 | Normal: use power freely |
| 🟡 Yellow | 60–85 | Elevated: shift big loads if easy |
| 🔴 Red | over 85 | Tight grid, higher spike risk: avoid big loads |

Next to it, the **spike risk chart** shows the chance each hour that wholesale prices jump above $100/MWh.

**Behind the scenes:** each bar is Model A's net-load forecast converted to a 0–100 strain index, with a boost when Model B's spike probability is over 50%.

---

## Step 3: Ask "Why is this hour red?"

**The user:** taps or hovers over the 6 pm red bar.

**What they see:**
> **Why Red? 6 pm**
> 1. 🌡️ DFW at 104°F → +2.1 GW of AC demand
> 2. ☀️ Solar fading at sunset → +3.0 GW gap
> 3. 🌬️ Wind dropping to 3 GW → +1.4 GW
>
> *"6 pm is red because a DFW heat wave is pushing AC demand up just as solar fades and the wind dies down."*
> Confidence: **high** (narrow band)

**Behind the scenes:** `GET /forecast/drivers?ts=…` returns the top-3 SHAP drivers from `gold.forecast_drivers`, and Gemini wrote the sentence earlier inside the pipeline.

---

## Step 4: Read the daily plan (Gemini advice)

**The user:** reads the advice panel.

> **🤖 Your plan for tomorrow**
> - ❄️ **Pre-cool** to 72° before 3 pm, then let it drift to 76° until 8 pm
> - 👕 Run **laundry and the dishwasher after 9 pm**
> - 🚗 **Charge the EV between 1 and 5 am** (cheapest, spike risk < 5%)
> - 🏊 Run the **pool pump 10 am–2 pm**, when solar is plentiful

Below it, the **Best Hours card** lists the greenest, cheapest windows at a glance.

**Behind the scenes:** `GET /advice` reads `gold.daily_advice`, which Gemini generated from the forecast table during the hourly Databricks run.

---

## Step 5: Ask a personal question (chat)

**The user:** types into the chat box:
> *"I need 40 kWh in my car by 7 am tomorrow. When should I charge?"*

**What they see:**
> *"Plug in after 11 pm and schedule charging for 1–5 am. That window is green all night with under 5% spike risk, so you'll get the lowest prices."*
> (Those hours light up on the timeline.)

**Behind the scenes:**
```text
Browser ──► FastAPI POST /chat {question}
FastAPI ──► Tiger Data: next 48 h forecast + advice
FastAPI ──► Gemini API: system prompt + forecast JSON + question
Gemini  ──► answer + suggested hours ──► Browser highlights them
```
The answer is **grounded in the live forecast**, not general knowledge.

---

## Step 6 (optional): Play with Ripple, "What if Texas shifted?"

**The user:** opens the Ripple panel and drags the sliders.

```text
  Homes participating:   [====|-----------]  5%
  kWh shifted per home:  [===|------------]  3 kWh
  From → to:             4–8 pm  →  10 pm–2 am

  Result:  Peak net load  −1.4 GW
           Spike risk     70% → 38%
           Red hours      3 → 1
           ≈ 4 gas peaker plants not needed
```
The timeline redraws with a before/after comparison.

**Behind the scenes:** `GET /simulate?pct=5&kwh=3&from=16-20&to=22-02` looks up a precomputed scenario in `gold.shift_scenarios`. Each scenario was produced by shifting load in Model A's curve and **re-running Model B**, so the numbers come from the real models.

**Why it matters:** it shows that small individual actions add up to a measurable effect on the grid.

---

## Step 7: Act on it

**The user:** sets the thermostat schedule, delays the laundry, and sets the EV charge timer. GridWise doesn't control devices; the user makes the change themselves (automation is on the roadmap).

---

## Step 8: Come back tomorrow (report card)

**The user:** opens the site the next morning.

> **📊 Report card: yesterday**
> Forecast error: **3.2%** · Spike hours caught: **2 of 2** · Actuals inside the confidence band: **84%**

They can also scroll to the **history charts** (last 30 days of peak strain and prices).

**Behind the scenes:** `GET /report-card` reads `gold.report_card`, which a daily Databricks task fills by comparing yesterday's forecast with what actually happened. History charts read Tiger Data's **continuous aggregates** (pre-computed daily rollups), so they load instantly.

**Why it matters:** users see whether the forecast has been right lately, which builds trust.

---

## A second path: analysts and judges (Genie)

```text
 Analyst ──► Databricks Genie space ──► "What was the most strained hour of summer 2025?"
         ◄── Genie writes SQL over Gold tables ◄── answer + chart
```
Example questions:
1. What was the most strained hour of summer 2025?
2. How does wind output change on peak-demand days?
3. How many hours had real-time prices above $100/MWh last August?
4. What's the average net load at 6 pm in July vs. January?
5. Which weekday has the highest average strain index?

---

## Full request map

| User action | Website call | Data source | Produced by |
|---|---|---|---|
| Open the site | `GET /forecast`, `GET /advice` | Tiger: `forecasts`, `daily_advice` | Model A + B, Gemini (hourly) |
| Hover a red hour | `GET /forecast/drivers?ts=` | Tiger: `forecast_drivers` | SHAP + Gemini (hourly) |
| Chat question | `POST /chat` | Tiger + **live Gemini call** | Gemini API (on demand) |
| Move the Ripple sliders | `GET /simulate?...` | Tiger: `shift_scenarios` | Ripple task + Model B (hourly) |
| Report card | `GET /report-card` | Tiger: `report_card` | Evaluation task (daily) |
| History charts | `GET /history?range=30d` | Tiger: continuous aggregates | Databricks sync (hourly) |
| Genie question | (inside Databricks) | Gold Delta tables | Genie (on demand) |

---

## What happens when something goes wrong

| Situation | What the user sees |
|---|---|
| Forecast is more than 2 hours old (pipeline delayed) | Banner: *"Forecast last updated 3 h ago"*, with the timestamp |
| Low-confidence hour (wide P10–P90 band) | ⚠️ icon: *"Uncertain: weather forecast is shifting"* |
| Gemini unavailable | Advice panel falls back to a rule-based plan built from the best/worst hours |
| Chat question unrelated to energy | Gemini politely steers back to grid and appliance questions |
| API down | Last cached forecast shown with a "may be outdated" notice |

---

## The core loop

```text
     ┌─────────────────────────────────────────────────────────────┐
     ▼                                                             │
  OPEN ──► SEE red hours ──► UNDERSTAND why ──► ACT (shift usage) ─┤
                                                                   │
  CHECK the report card next morning ──► trust grows ──► come back ┘
```

**Outcome for the user:** lower bills on time-of-use and variable plans, cheaper EV charging, and a real contribution to keeping the Texas grid stable.
