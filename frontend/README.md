# 🖥️ frontend/: Dashboard (Next.js)

> **Status:** built (Phase 5.4–5.7). Single-page, mobile-first, dark theme.

The website users open at **gridwise.tech**. No login. It implements the user journey in [PIPELINE.md](../PIPELINE.md) and reads everything from the [backend API](../backend/README.md) (contract: `/api/*`).

**Stack:** Next.js 15 (App Router, TypeScript) · Tailwind v4 · Recharts · TanStack Query.

## What's on the page

| Section | Component | API call |
|---|---|---|
| Header: logo, tomorrow's date, verdict banner, data freshness, stale (>2 h) / API-down / demo banners | `Header.tsx` | `GET /api/health`, `GET /api/forecast?hours=48` |
| 🚦 48-hour strain timeline: tappable color strip + net-load bars with the P10–P90 band, ⚠ on low-confidence hours | `StrainTimeline.tsx` | `/api/forecast` |
| ❓ "Why red?" panel: top-3 SHAP drivers in plain language + Gemini sentence + confidence | `WhyRedPanel.tsx`, `lib/drivers.ts` | `GET /api/forecast/drivers?ts=` |
| 💸 Spike-risk chart (P(price > $100/MWh)) | `SpikeChart.tsx` | `/api/forecast` |
| 🕐 Best / avoid hours | `BestHoursCard.tsx` | `summary.best_windows / avoid_windows` |
| 🤖 Daily plan with a **Gemini** / **Rules** badge | `AdvicePanel.tsx` | `GET /api/advice` |
| 💬 Chat; returned `highlight_hours` light up on the timeline | `ChatBox.tsx` | `POST /api/chat` |
| 🌊 Ripple simulator: sliders + window selects → before/after chart; hero stats are **Peak cut (GW)** and **Gas peakers avoided** (max spike / red hours appear only when they change) | `RipplePanel.tsx` | `GET /api/simulate` |
| 📊 Report card + 📈 30-day history | `ReportCard.tsx`, `HistoryChart.tsx` | `GET /api/report-card?days=7`, `GET /api/history?days=30` |
| Footer: data credits + not-affiliated-with-ERCOT disclaimer | `Footer.tsx` | – |

Ripple controls step through the same grid that `ml/08_ripple.py` precomputes (pct 1/2/5/10/15/20/25, kWh 1/2/3/5/8, from 4–8 pm or 5–9 pm, to 10 am–2 pm, 10 pm–2 am or 12–4 am), so the live API returns an exact scenario. The demo default is **15 % of homes, 5 kWh, 5–9 pm → 10 am–2 pm**: about −1.7 GW and 17 peakers on the 2026-11-07 22Z run (−1.8 GW / 18 in fixtures mode). Re-check `DEFAULT_SIM` in `RipplePanel.tsx` after new 08_ripple runs.

Every section has loading skeletons, an empty state and an error state with Retry.

## Run

```bash
cd frontend
npm install
cp .env.example .env.local        # optional; defaults shown below
npm run dev                       # http://localhost:3000, talks to NEXT_PUBLIC_API_BASE_URL
npm run dev:fixtures              # no backend needed: uses fixtures/*.json
npm run build && npm run start    # production
npm run build:fixtures && npm run start   # production build in demo mode
```

| Env var (public, baked in at build time) | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | FastAPI base; the app calls `${base}/api/...` |
| `NEXT_PUBLIC_USE_FIXTURES` | unset | `1` = never call the API; use the bundled snapshot |

## Fixtures and fallbacks

`fixtures/*.json` hold **real** GridWise output exported from the Gold tables via the SQL warehouse (no notebook compute), shaped exactly like the API contract: `forecast.json`, `drivers.json` (3 hours: the reddest, the riskiest and the calmest), `advice.json` (the rule-based fallback plan), `report_card.json`, `history.json`, `health.json`, plus `strain_reference.json` for the offline Ripple estimate. To refresh them, run this from the repo root:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python frontend/scripts/export_fixtures.py
```

Behavior when the API isn't there:
- **Fixtures mode** (`NEXT_PUBLIC_USE_FIXTURES=1`): a blue "Demo mode" banner. Chat answers come from a rule-based engine (`lib/offlineChat.ts`), and Ripple uses a labelled offline estimate (`lib/simulate.ts`: 10 M homes, ~100 MW per peaker, strain recomputed against `strain_reference`, and a rough spike-odds response). The live API re-runs Model B instead.
- **API unreachable or 5xx in live mode:** the page falls back to the same snapshot and shows an amber "may be outdated" banner (PIPELINE.md, "API down"). A 4xx is shown as an error.
- **Stale forecast** (`forecast_age_minutes` > 120): amber banner with the timestamp.

## Notes
- All times are shown in `America/Chicago` using `Intl`, so the viewer's own timezone never changes them.
- Driver copy: the pipeline measures ERCOT wind and solar against their training means, so "ERCOT wind forecast raises" is shown as "Light wind: only 4.5 GW expected" (see `lib/drivers.ts`).
- `node_modules/`, `.next/` and `.env*` (except `.env.example`) are git-ignored.
