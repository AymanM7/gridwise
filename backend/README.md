# 🔌 backend/: API (FastAPI)

> **Status:** planned for **Phase 5.3**. Not built yet.

A small FastAPI service that reads from Tiger Data and serves the dashboard. It runs on **Vultr** behind Caddy (HTTPS).

**Planned endpoints**

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | status |
| GET | `/forecast?hours=48` | hourly forecast: P10/P50/P90, spike probability, strain, level |
| GET | `/forecast/drivers?ts=` | top-3 "Why Red?" drivers + Gemini sentence |
| GET | `/advice` | tomorrow's Gemini plan, best/avoid hours |
| GET | `/history?range=30d&agg=daily` | actuals from continuous aggregates |
| GET | `/simulate?pct=5&kwh=3&from=16-20&to=22-02` | Ripple before/after |
| GET | `/report-card?days=7` | forecast accuracy |
| POST | `/chat` | Gemini answer grounded in the live forecast |

**Needs** in `.env`: `TIGER_DATABASE_URL`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `CORS_ORIGINS`.
