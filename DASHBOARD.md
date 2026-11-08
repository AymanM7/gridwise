# 🖥️ GridWise Dashboard: Architecture & User Guide

This document explains **how the dashboard is built** (Part 1) and **how a person should use it** (Part 2).
For the full data pipeline see [ARCHITECTURE.md](ARCHITECTURE.md); for the end-to-end journey see [PIPELINE.md](PIPELINE.md).

---

# Part 1: Architecture

## 1.1 The big picture

```text
 ┌──────────────────────── OFFLINE: runs on a schedule, never on a page view ────────────────────────┐
 │                                                                                                    │
 │  ERCOT (gridstatus) ─┐                                                                             │
 │  EIA-930 API ────────┼─► ingestion/ ─► Databricks: Bronze → Silver → Gold → ML                     │
 │  Open-Meteo ─────────┘                 (Model A net load · Model B spikes · SHAP · Ripple · Gemini)│
 │                                                       │                                            │
 │                                         python -m db.sync  (or the API's auto-refresh)             │
 └───────────────────────────────────────────────────────┼────────────────────────────────────────────┘
                                                         ▼
 ┌────────────────────────── ONLINE: what a page view actually touches ───────────────────────────────┐
 │                                                                                                    │
 │   Tiger Data (PostgreSQL + TimescaleDB)  ◄── SQL ──  FastAPI  :8000  ── JSON /api/* ──►  Next.js :3000│
 │   forecasts · drivers · advice · scenarios           backend/app/                         frontend/ │
 │   report_card · actuals · actuals_daily                  │                                          │
 │                                                          └── POST /api/chat ──► Gemini (live)       │
 └────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Key design choice: precompute everything expensive.** Forecasts, SHAP explanations, the 210 Ripple scenarios and the daily advice are all computed in Databricks ahead of time. The API only *reads* finished rows from Tiger, so:

- every endpoint answers in **< 0.5 s**
- page views cost **zero Databricks compute** (important on Free Edition's daily quota)
- the only live AI call is **chat** (Gemini), and it has a rule-based fallback

## 1.2 Layers

| Layer | Tech | Location | Job |
|---|---|---|---|
| **Frontend** | Next.js 15 (App Router, TypeScript), Tailwind v4, Recharts, TanStack Query, `motion`, `lucide-react`, Geist font | `frontend/` | Single-page dashboard, mobile-first, dark theme |
| **API** | FastAPI + psycopg | `backend/app/` | 8 read-only JSON endpoints + Gemini chat + background Tiger refresh |
| **Serving DB** | Tiger Data (PostgreSQL 18 + TimescaleDB 2.31) | schema in `db/schema.sql`, loader `db/sync.py` | Hypertables for forecasts/actuals; `actuals_daily` continuous aggregate |
| **Source of truth** | Databricks Unity Catalog `grid.gold.*` | `pipeline/`, `ml/` | Where every number is produced |
| **AI** | Gemini `gemini-2.5-flash` (REST) | `backend/app/gemini.py`, `ml/09_advice.py` | Chat answers; daily plan + "Why red?" sentences |

## 1.3 API endpoints

All under `http://localhost:8000/api` (interactive docs: **`/api/docs`**).

| Endpoint | Reads (Tiger table) | Used by |
|---|---|---|
| `GET /health` | `forecasts` (latest `run_ts`) | Hero "Live" pill, freshness, stale banner |
| `GET /forecast?hours=48` | `forecasts` | Hero, strain timeline, spike chart, best hours |
| `GET /forecast/drivers?ts=…` | `forecast_drivers` | "Why this color?" panel |
| `GET /advice` | `daily_advice` | "Your plan" |
| `GET /simulate?pct=&kwh=&from=&to=` | `shift_scenarios`, `shift_scenario_curves` | Ripple |
| `GET /report-card?days=7` | `report_card` | Report card |
| `GET /history?days=30` | `actuals_daily` (continuous aggregate) | Last 30 days |
| `POST /chat` `{question}` | `forecasts` + `daily_advice` → **Gemini** | Ask GridWise |

**Background refresh** (`backend/app/refresh.py`): every 5 minutes the API asks the Databricks **Jobs API** whether a new `gridwise-hourly` run finished (no compute). If so, it re-runs `db.sync` in a subprocess. A Postgres advisory lock keeps multiple API workers from syncing at once.

## 1.4 Frontend structure

```text
frontend/src/
├── app/
│   ├── layout.tsx         Geist fonts, page backdrop, dark theme
│   ├── providers.tsx      TanStack Query (5-min stale, 10-min auto-refetch) + MotionConfig (reduced motion)
│   ├── page.tsx           renders <Dashboard/>
│   └── globals.css        design tokens (colors, surfaces, shimmer, focus rings)
├── components/
│   ├── Dashboard.tsx      page layout, all data queries, selected-hour + chat-highlight state
│   ├── hero/              TopBar (sticky nav) · StrainGauge (ring) · Notice (banners)
│   ├── Header.tsx         hero: verdict, live pill, stat chips
│   ├── StrainTimeline.tsx hand-built 48-h chart + tappable color strip (keyboard listbox)
│   ├── WhyRedPanel.tsx    SHAP drivers, Gemini sentence, confidence meter
│   ├── SpikeChart.tsx     spike-probability area chart
│   ├── BestHoursCard.tsx  best / avoid windows
│   ├── AdvicePanel.tsx    daily plan + Gemini/Rules badge
│   ├── ChatBox.tsx        chat thread, typing indicator, highlight chip
│   ├── RipplePanel.tsx    sliders, scenario stats, before/after chart
│   ├── ReportCard.tsx     accuracy tiles + 7-day table
│   ├── HistoryChart.tsx   30-day peaks + max price
│   ├── insights/          shared tiles, chips, sliders, segmented controls
│   ├── motion.tsx         Reveal · Stagger · AnimatedNumber · PulseDot
│   ├── ui.tsx             Card, Badge, Stat, LevelPill, Empty, ErrorBox, Loading
│   └── Footer.tsx
└── lib/
    ├── api.ts             fetch wrapper; falls back to fixtures if the API is down
    ├── types.ts           API contract types
    ├── format.ts          Central-time formatting, level colors
    ├── drivers.ts         SHAP feature → plain-English copy
    ├── simulate.ts        offline Ripple estimate (demo mode)
    └── offlineChat.ts     offline rule-based chat (demo mode)
```

**State flow inside the page**

- `Dashboard.tsx` owns two pieces of shared state:
  - `selected` (an hour): set by clicking the timeline, spike chart or "tightest hour" stat → drives **Why this color?**
  - `highlight` (a list of hours): set by chat answers → lights those hours up on the **timeline**
- On first load the most-strained hour is pre-selected so "Why this color?" is never empty.
- Ripple requests are **debounced 250 ms** and keep the previous result on screen while the next loads (no flicker).

## 1.5 How the numbers are made

| On screen | Produced by | Method |
|---|---|---|
| Net load (bars) + P10–P90 band | `ml/05_predict.py`, **Model A** | LightGBM quantile models, 1–48 h ahead. Test MAPE 11.8% vs 18.6% naive baseline |
| Demand (used for strain) | **Model D** + a recent-hours anchor | LightGBM demand (MAPE 3.45%), minus ERCOT's own wind/solar forecasts |
| Strain index 0–100 | `ml/05_predict.py` | Percentile of net load vs. same month historically (`gold.strain_reference`), +15 if spike risk > 50%. Green < 60 · Yellow 60–85 · Red > 85 |
| Spike risk % | **Model B** | LightGBM classifier for real-time price > $100/MWh. Recall 0.81 |
| "Why" drivers (± GW) | `ml/06_explain.py` | SHAP values per hour, top 3 shown |
| Plan / "Why red?" sentence | `ml/09_advice.py` | Gemini; rule-based fallback |
| Ripple results | `ml/08_ripple.py` | 210 precomputed scenarios (7 participation × 5 kWh × 2 from × 3 to windows), each re-scored with Model B |
| Report card | `ml/07_report_card.py` | Published forecast vs. ERCOT actuals; older days are backtests |
| 30-day history | Tiger `actuals_daily` | Continuous aggregate over hourly ERCOT actuals |

## 1.6 Resilience

| Situation | What the user sees |
|---|---|
| API unreachable / 5xx | Page loads from the bundled real-data snapshot + amber "may be outdated" notice |
| Forecast > 2 h old | "Pipeline may be delayed" notice with the timestamp |
| Gemini quota / error | Plan shows **Rules** badge; chat answers from rules. Nothing breaks |
| `npm run dev:fixtures` | Full demo mode, no backend or database needed (blue "Demo" notice) |
| Reduced-motion setting | All animations and count-ups are skipped |

## 1.7 Current API status (checked 2026-11-07)

| Service | Status | Notes |
|---|---|---|
| FastAPI: all 8 endpoints | ✅ 200, 0.25–0.6 s each | |
| Next.js dashboard | ✅ 200 | |
| Tiger Data | ✅ | 96 forecast rows, latest run 2026-11-07 22:00 UTC |
| Databricks SQL warehouse | ✅ | Gold matches Tiger |
| Databricks Jobs API | ✅ | Last `gridwise-hourly` run: *success with failures*. Needs one fully green run |
| ERCOT (gridstatus) · EIA-930 · Open-Meteo | ✅ | Used by ingestion only |
| **Gemini** | ⚠️ **429 quota exceeded** | Chat + plan fall back to rules until the quota resets or a key with quota is used |
| Databricks secret scope `gridwise` | ❌ not created | Run `python -m tools.setup_secrets` so the pipeline can call Gemini |

## 1.8 Run it

```powershell
python -m tools.dev              # sync Tiger + start API :8000 + dashboard :3000, opens the browser
python -m tools.dev --no-sync    # faster start, skip the sync
python -m tools.dev --fixtures   # demo mode: dashboard only, bundled data
```

---

# Part 2: How to use it

GridWise answers one question: **"When should I use power tomorrow, and when should I hold off?"**
No login, no setup: open the page.

## Step 1: Read the verdict (5 seconds)

The **hero** at the top tells you the whole story:

- **Verdict line**: e.g. *"Tight grid ahead: 18 red hours."* The color tells you the worst level coming.
- **Strain ring**: the peak strain over the next 48 hours (0–100) and when it happens.
- **Chips**: how many green / yellow / red hours, the peak net load, and the highest spike risk.
- **"Live" pill**: shows how fresh the data is. If it says *Delayed* or *Demo*, the numbers may be older.

> **Green = normal · Yellow = elevated · Red = tight.** Red hours are when the grid is most stressed and prices are most likely to jump.

## Step 2: Scan the 48-hour timeline

- Each bar is one hour. **Height** = expected net load (demand the gas plants must cover); **color** = strain.
- The **grey band** shows how sure we are (P10–P90). A dotted cap means *uncertain hour*.
- **Tap any hour** (or use the arrow keys on the color strip) to explain it.
- The stats under the chart jump you to the **tightest** and **calmest** hours.

## Step 3: Ask "Why this color?"

The panel next to the timeline explains the selected hour:

- **Top 3 drivers**, e.g. *"Light wind: only 4.8 GW expected → +8.2 GW net load"*. Red bars push strain up, green bars ease it.
- A **plain-English sentence** about why the hour is red/yellow/green.
- A **confidence meter** (low / medium / high).

## Step 4: Follow your plan

- **Best hours**: the calmest windows to run laundry, the dishwasher, the pool pump or EV charging.
- **Avoid big loads**: the windows to hold off, with their spike risk.
- **Your plan**: 3–5 concrete actions for tomorrow (*pre-cool before 4 pm, charge the EV 1–4 am*). The badge says whether **Gemini** or the **rules engine** wrote it.

## Step 5: Check spike risk (if you're on a variable-rate plan)

The **Spike risk** chart shows the chance each hour that wholesale prices exceed **$100/MWh**. Above the 50% line is where variable-rate and "free nights" customers feel it. Click a point to explain that hour.

## Step 6: Ask your own question

Type into **Ask GridWise** or tap a suggestion:

- *"I need 40 kWh in my car by 7 am. When should I charge?"*
- *"When should I run the laundry?"*
- *"Why is tomorrow evening red?"*

Hours the answer recommends **light up on the timeline**. Tap **Clear** to remove them.

## Step 7: See your impact with Ripple

Ripple shows what happens if many Texans shift a little:

1. Drag **Homes participating** (1–25%) and **kWh shifted per home** (1–8 kWh).
2. Choose **Move usage from** (4–8 pm or 5–9 pm) and **To** (daytime solar hours, late night, or overnight).
3. Watch the **peak cut (GW)**, **gas peakers avoided**, spike risk and red hours update, and the after-shift curve reshape.

> Example: 15% of homes moving 5 kWh from 5–9 pm to 10 am–2 pm cuts the 48-hour peak by about **1.7 GW**, roughly **17 gas plants** that wouldn't need to start.

## Step 8: Decide whether to trust it

- **Report card**: how far off yesterday's forecast was, whether we caught the price spikes, and how often reality landed inside our band (target ≈ 80%). Error chips are graded *good / ok / poor*.
- **Last 30 days**: daily peak net load (colored by that day's strain) and the highest real-time price, so you can see what a "normal" week looks like.

## Quick recipes

| I want to… | Do this |
|---|---|
| Save money on a variable-rate plan | Use **Best hours**; avoid hours where spike risk > 50% |
| Charge my EV cheaply | Ask the chat with your kWh and deadline, or use the overnight best window |
| Stay comfortable on a red evening | Follow the plan's **pre-cool** tip before the red window starts |
| Understand a scary red hour | Tap it → read **Why this color?** |
| Show friends why shifting matters | Open **Ripple** and drag participation up |

## Fine print

GridWise is an independent student project (TAMUhack 26), **not affiliated with ERCOT**. Forecasts are estimates, not official grid conditions or emergency alerts. For official notices see [ercot.com](https://www.ercot.com).
