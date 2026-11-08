# 🖥️ GridWise Dashboard V3: Complete Architecture

The full architecture of the GridWise dashboard, from raw ERCOT data to the pixels on screen.

> **How to read the diagrams.** Every diagram is a plain-text **system-design box diagram**, so it looks identical in VS Code, on GitHub and in a terminal. Under each one, a collapsible **Mermaid version** renders as an interactive diagram on GitHub.
> Polished image for slides and Devpost: [`docs/architecture.png`](docs/architecture.png).
> Regenerate the box diagrams: `python docs/diagrams/gen_dashboard_v3.py docs/diagrams/DASHBOARD_V3.template.md DASHBOARD_V3.md`

![GridWise system architecture](docs/architecture.png)

Related: [DASHBOARD_V2.md](DASHBOARD_V2.md) (per-section guide) · [JUDGES.md](JUDGES.md) (demo script) · [ARCHITECTURE.md](ARCHITECTURE.md) (pipeline box diagrams)

---

## Contents

1. [System overview](#1-system-overview)
2. [Data pipeline (Databricks)](#2-data-pipeline-databricks)
3. [Serving layer (Tiger Data + FastAPI)](#3-serving-layer-tiger-data--fastapi)
4. [Tiger Data schema](#4-tiger-data-schema)
5. [API endpoints → dashboard sections](#5-api-endpoints--dashboard-sections)
6. [Frontend architecture](#6-frontend-architecture)
7. [Request flows](#7-request-flows)
8. [Freshness: how new data reaches the page](#8-freshness-how-new-data-reaches-the-page)
9. [Resilience and fallbacks](#9-resilience-and-fallbacks)
10. [Visual layer: shaders and motion](#10-visual-layer-shaders-and-motion)
11. [Deployment topologies](#11-deployment-topologies)
12. [Security model](#12-security-model)
13. [Tech stack summary](#13-tech-stack-summary)

---

## 1. System overview

Three zones: **sources** feed **Databricks** (which computes everything ahead of time), results are copied to **Tiger Data**, and the **API + dashboard** only read from Tiger. Gemini is the one live external call.

```text
┌────────────────────────────┐     ┌────────────────────────────┐     ┌────────────────────────────┐
│     ERCOT (gridstatus)     │     │        EIA-930 API         │     │         OPEN-METEO         │
│ load · prices · wind/solar │     │    hourly history 2023+    │     │  weather · 4 Texas cities  │
└──────────────┬─────────────┘     └──────────────┬─────────────┘     └──────────────┬─────────────┘
               │                                  │                                  │
               └──────────────────────────────────┼──────────────────────────────────┘
                                                  │
                                                  ▼
                         ┌────────────────────────────────────────────────┐
                         │  INGESTION WORKER  ·  python -m ingestion.cli  │
                         │  fetch -> parquet -> upload into a UC Volume   │
                         └────────────────────────┬───────────────────────┘
                                                  │ files.upload
                                                  ▼
╔══════════════════════════════════════════════════════════════════════════════════════════════════╗
║                 DATABRICKS FREE EDITION   ·   one Job: gridwise-hourly (9 tasks)                 ║
║                                                                                                  ║
║  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ║
║  │     UC VOLUME      │─►│       BRONZE       │─►│       SILVER       │─►│        GOLD        │  ║
║  │  landing/ parquet  │  │    Auto Loader     │  │ hourly · DST-safe  │  │ features · strain  │  ║
║  └────────────────────┘  └────────────────────┘  └────────────────────┘  └──────────┬─────────┘  ║
║                                                                                     │            ║
║                                                                                     ▼            ║
║  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐  ║
║  │   GEMINI ADVICE    │  │       RIPPLE       │  │        SHAP        │  │  MODELS A · B · D  │  ║
║  │    daily plan +    │◄─│    210 what-if     │◄─│   top-3 drivers    │◄─│ LightGBM · MLflow  │  ║
║  │ Why-red (rules fb) │  │     scenarios      │  │ per forecast hour  │  │    UC @champion    │  ║
║  └──────────┬─────────┘  └──────────┬─────────┘  └──────────┬─────────┘  └──────────┬─────────┘  ║
║             │                       │                       │                       │            ║
║             └───────────────────────┴───────────┬───────────┴───────────────────────┘            ║
║                                                 ▼                                                ║
║              ┌────────────────────────────────────────────────────────────────────┐              ║
║              │                        GOLD SERVING TABLES                         │              ║
║              │            forecasts · forecast_drivers · daily_advice             │              ║
║              │          shift_scenarios · report_card · strain_reference          │              ║
║              └──────────────────────────────────┬─────────────────────────────────┘              ║
║                                                 │                                                ║
╚═════════════════════════════════════════════════╪════════════════════════════════════════════════╝
                                                  │ db.sync  (SQL warehouse -> upsert)
                                                  ▼
                         ┌────────────────────────────────────────────────┐
                         │    TIGER DATA  ·  PostgreSQL + TimescaleDB     │
                         │       hypertables · continuous aggregate       │
                         └────────────────────────┬───────────────────────┘
                                                  │ SQL (ms)
                                                  ▼
                         ┌────────────────────────────────────────────────┐      ┌─────────────────┐
                         │       FASTAPI  ·  8 endpoints  ·  :8000        │╌╌╌╌╌►│      GEMINI     │
                         │          chat limits · auto-sync loop          │      │    2.5 Flash    │
                         └────────────────────────┬───────────────────────┘      │    live chat    │
                                                  │ JSON /api/*                  └─────────────────┘
                                                  ▼
                         ┌────────────────────────────────────────────────┐
                         │          NEXT.JS DASHBOARD  ·  :3000           │
                         │       shaders · timeline · Ripple · chat       │
                         └────────────────────────┬───────────────────────┘
                                                  ▼
                                      ┌──────────────────────┐
                                      │         USER         │
                                      └──────────────────────┘
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
flowchart LR
    subgraph SRC["🌐 Data sources"]
        ERCOT["ERCOT<br/>(gridstatus)"]
        EIA["EIA-930 API"]
        OM["Open-Meteo<br/>weather"]
    end

    subgraph ING["📥 Ingestion worker"]
        CLI["ingestion.cli<br/>fetch → parquet"]
    end

    subgraph DBX["🧱 Databricks (Free Edition)"]
        VOL[("UC Volume<br/>landing/")]
        MED["Bronze → Silver → Gold"]
        ML["Models A · B · D<br/>MLflow + UC"]
        AI["SHAP · Ripple ·<br/>Gemini advice"]
        GOLD[("Gold tables")]
    end

    subgraph SERVE["⚡ Serving"]
        TIGER[("Tiger Data<br/>TimescaleDB")]
        API["FastAPI<br/>8 endpoints"]
    end

    subgraph UI["🖥️ Client"]
        WEB["Next.js dashboard"]
        USER(("User"))
    end

    GEM["✨ Gemini 2.5 Flash"]

    ERCOT & EIA & OM --> CLI --> VOL --> MED --> ML --> AI --> GOLD
    GOLD -- "db.sync" --> TIGER
    TIGER -- "SQL" --> API
    API -- "JSON /api/*" --> WEB --> USER
    API -. "chat only" .-> GEM
    AI -. "daily plan" .-> GEM
```

</details>

**Design principle:** *precompute everything expensive.* A page view never runs a model and never touches Databricks, so it loads in < 0.5 s and costs **zero** lakehouse compute.

---

## 2. Data pipeline (Databricks)

One Databricks Job, `gridwise-hourly`, chains 9 notebook tasks. Each task writes Gold tables that the dashboard later reads.

```text
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│      01_bronze      │   │      02_silver      │   │       03_gold       │   │      05_predict     │
│     Auto Loader     │──►│  hourly · DST-safe  │──►│  features · strain  │──►│   Models A · D · B  │─┐
│    → bronze.* (7)   │   │      → silver.*     │   │  → strain_reference │   │     → forecasts     │ │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘   └─────────────────────┘ │
                                                                                                      │
                                                                                                      │
                                                                                                      │
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐ │
│    genie_comments   │   │      09_advice      │   │      08_ripple      │   │      06_explain     │ │
│      table docs     │◄──│    Gemini / rules   │◄──│    210 scenarios    │◄──│      SHAP top-3     │◄┘
│    → Genie space    │   │    → daily_advice   │   │  → shift_scenarios  │   │  → forecast_drivers │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘   └──────────┬──────────┘
                                     ▲                                                   │
                                     │                                                   ▼
                                     │                                        ┌─────────────────────┐
                                     │  report_card + ripple both feed advice │    07_report_card   │
                                     └────────────────────────────────────────│  forecast vs actual │
                                                                              │    → report_card    │
                                                                              └─────────────────────┘
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
flowchart TB
    T1["01_bronze<br/>Auto Loader"] --> T2["02_silver<br/>hourly UTC · DST-safe · joined"]
    T2 --> T3["03_gold<br/>features · strain_reference · spikes"]
    T3 --> T4["05_predict<br/>Model A net load P10/P50/P90<br/>Model D demand · Model B spike"]
    T4 --> T5["06_explain<br/>SHAP top drivers"]
    T5 --> T6["08_ripple<br/>210 shift scenarios"]
    T5 --> T7["07_report_card<br/>forecast vs actual"]
    T6 --> T8["09_advice<br/>Gemini plan + Why-red<br/>(rules fallback)"]
    T8 --> T9["genie_comments<br/>table docs for Genie"]

    T4 -.-> G1[("gold.forecasts")]
    T5 -.-> G2[("gold.forecast_drivers")]
    T6 -.-> G3[("gold.shift_scenarios<br/>+ _curves")]
    T7 -.-> G4[("gold.report_card")]
    T8 -.-> G5[("gold.daily_advice")]
    T3 -.-> G6[("gold.strain_reference")]

    classDef gold fill:#3b2f0b,stroke:#fbbf24,color:#fde68a
    class G1,G2,G3,G4,G5,G6 gold
```

</details>

| Model | What it predicts | Test result |
|---|---|---|
| **A** `grid.ml.net_load` | Net load (demand − wind − solar), P10/P50/P90, 1–48 h | MAPE **11.8%** vs 18.6% baseline · band coverage **80.7%** |
| **D** `grid.ml.demand` | Demand, anchored on the last 6 actual hours | MAPE **3.45%** |
| **B** `grid.ml.spike` | P(real-time price > $100/MWh) | Recall **0.81** · ROC-AUC **0.93** |

**Strain index (0–100)** = percentile of forecast net load within the same month historically (`strain_reference`), +15 if spike risk > 50%. 🟢 < 60 · 🟡 60–85 · 🔴 > 85.

---

## 3. Serving layer (Tiger Data + FastAPI)

```text
╔════════════════════════════╗      ┌────────────────────────┐      ╔══════════════════════════════╗
║         DATABRICKS         ║      │       db/sync.py       │      ║          TIGER DATA          ║
║        Gold tables         ║─────►│  read Gold -> upsert   │─────►║  Postgres 18 + TimescaleDB   ║
║       SQL warehouse        ║      │        ~20-35 s        │      ║   hypertables: forecasts,    ║
║          Jobs API          ║      └────────────────────────┘      ║           actuals            ║
╚════════════════════════════╝                                      ║     cagg: actuals_daily      ║
                                                                    ║       + 6 plain tables       ║
                                                                    ╚══════════════════════════════╝
                                                       SQL reads                    ▲
                                                 ┌──────────────────────────────────┘
                                                 │
╔════════════════════════════════════════════════╪═════════════════════════════════════════════════╗
║  FASTAPI  ·  backend/app  ·  uvicorn :8000     │                                                 ║
║                                                │                                                 ║
║ ┌────────────────┐ ┌────────────────┐ ┌────────┴───────┐ ┌────────────────┐ ┌────────────────┐   ║
║ │    main.py     │ │    core.py     │ │     db.py      │ │   gemini.py    │ │   refresh.py   │   ║
║ │    8 routes    │►│   summaries    │►│  psycopg pool  │ │ grounded chat  │ │ poll Jobs API  │   ║
║ │  chat limits   │ │  Ripple snap   │ │   lazy open    │ │ cache + errors │ │ -> run db.sync │   ║
║ └────────┬───────┘ └────────────────┘ └────────────────┘ └────────┬───────┘ └────────────────┘   ║
║          │                                                        │                              ║
║          │  limits: ≤500 chars · 10/min per IP · Gemini cap       │                              ║
║          │  refresh.py: Jobs API poll (5 min) -> db.sync          │                              ║
╚══════════╪════════════════════════════════════════════════════════╪══════════════════════════════╝
           ▼ JSON                                                   ▼
┌─────────────────────┐                                   ┌───────────────────┐
│  NEXT.JS DASHBOARD  │                                   │  GEMINI 2.5 FLASH │
└─────────────────────┘                                   └───────────────────┘
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
flowchart LR
    subgraph DBX["Databricks"]
        GOLD[("Gold tables")]
        WH["SQL warehouse"]
        JOBS["Jobs API"]
    end

    subgraph SYNC["db/sync.py"]
        S["read Gold → upsert Tiger<br/>~20–35 s"]
    end

    subgraph TIGER["Tiger Data · PostgreSQL 18 + TimescaleDB 2.31"]
        HT[("Hypertables<br/>forecasts · actuals")]
        TB[("Tables<br/>drivers · advice · scenarios<br/>report_card · strain_reference")]
        CA[("Continuous aggregate<br/>actuals_daily")]
    end

    subgraph API["FastAPI · backend/app"]
        MAIN["main.py<br/>routes + chat limits"]
        CORE["core.py<br/>summaries · windows · Ripple snap"]
        DB["db.py<br/>connection pool"]
        GEM["gemini.py"]
        REF["refresh.py<br/>auto-sync loop"]
    end

    GOLD --> WH --> S --> HT & TB
    HT --> CA
    MAIN --> CORE --> DB --> HT & TB & CA
    MAIN --> GEM
    REF -- "every 5 min: new run?" --> JOBS
    REF -- "yes → run" --> S
```

</details>

| Module | Responsibility |
|---|---|
| `main.py` | 8 routes, CORS, chat limits (≤ 500 chars, 10/min per IP, global Gemini cap) |
| `core.py` | Latest run lookup, hour summaries, best/avoid windows, Ripple nearest-scenario snapping, rules answers |
| `db.py` | psycopg 3 connection pool (lazy open; serverless-friendly) |
| `gemini.py` | Grounded chat prompt → `{answer, highlight_hours}`, cache, error handling |
| `refresh.py` | Background loop: Jobs API poll → `db.sync` subprocess, advisory lock |

---

## 4. Tiger Data schema

```text
┌────────────────────────────┐     ╔════════════════════════════╗     ┌────────────────────────────┐
│      forecast_drivers      │     ║  forecasts  [HYPERTABLE]   ║     │        daily_advice        │
├────────────────────────────┤ N:1 ├────────────────────────────┤ 1:1 ├────────────────────────────┤
│ run_ts · target_ts         │◄───►║ run_ts · target_ts (PK)    ║◄───►│ run_ts · date_local        │
│ rank (1-3) · feature       │     ║ net_load p10/p50/p90       ║     │ headline · tips (json)     │
│ contribution_mw            │     ║ demand_p50 · spike_prob    ║     │ why_red (json)             │
└────────────────────────────┘     ║ strain_index · level       ║     │ generated_by               │
                                   ║ low_confidence             ║     └────────────────────────────┘
                                   ╚════┬═══════════════════════╝
                 re-scored per run      │
               ┌────────────────────────┘
               ▼
┌────────────────────────────┐     ┌────────────────────────────┐     ┌────────────────────────────┐
│      shift_scenarios       │     │   shift_scenario_curves    │     │        report_card         │
├────────────────────────────┤1:48 ├────────────────────────────┤     ├────────────────────────────┤
│ run_ts · pct · kwh         │────►│ scenario key · target_ts   │     │ date · basis               │
│ from / to window           │     │ before_mw · after_mw       │     │ mape · demand_mape         │
│ peak_reduction_mw          │     │ spike_before / after       │     │ spike_recall               │
└────────────────────────────┘     └────────────────────────────┘     │ band_coverage              │
                                                                      └────────────────────────────┘


╔════════════════════════════╗     ╔════════════════════════════╗     ┌────────────────────────────┐
║   actuals  [HYPERTABLE]    ║     ║   actuals_daily  [CAGG]    ║     │      strain_reference      │
├────────────────────────────┤roll ├────────────────────────────┤     ├────────────────────────────┤
║ ts (PK) · demand_mw        ║────►║ day · peak_net_load        ║     │ month · percentile         │
║ net_load_mw                ║     ║ max_price · max_strain     ║     │ net_load_mw                │
║ price_hubavg               ║     ║ auto-refreshed rollup      ║     │ -> strain colors           │
╚════════════════════════════╝     ╚════════════════════════════╝     └────────────────────────────┘
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
erDiagram
    FORECASTS ||--o{ FORECAST_DRIVERS : "explained by (run_ts, target_ts)"
    FORECASTS ||--o| DAILY_ADVICE : "summarised by run_ts"
    FORECASTS ||--o{ SHIFT_SCENARIOS : "re-scored per run_ts"
    SHIFT_SCENARIOS ||--|{ SHIFT_SCENARIO_CURVES : "48-hour curve"
    ACTUALS ||--o{ ACTUALS_DAILY : "rolled up (continuous aggregate)"
    STRAIN_REFERENCE ||--o{ FORECASTS : "percentile thresholds"

    FORECASTS {
        timestamptz run_ts PK
        timestamptz target_ts PK
        float net_load_p10_p50_p90
        float demand_p50
        float spike_prob
        float strain_index
        text level
        bool low_confidence
    }
    FORECAST_DRIVERS {
        timestamptz run_ts
        timestamptz target_ts
        int rank
        text feature
        float contribution_mw
    }
    DAILY_ADVICE {
        timestamptz run_ts
        date date_local
        text headline
        jsonb tips
        jsonb why_red
        text generated_by
    }
    SHIFT_SCENARIOS {
        timestamptz run_ts
        float participation_pct
        float kwh_per_home
        text from_window
        text to_window
        float peak_reduction_mw
    }
    SHIFT_SCENARIO_CURVES {
        timestamptz target_ts
        float before_mw
        float after_mw
        float spike_before
        float spike_after
    }
    REPORT_CARD {
        date date
        float mape
        float spike_recall
        float band_coverage
        text basis
    }
    STRAIN_REFERENCE {
        int month
        float percentile
        float net_load_mw
    }
    ACTUALS {
        timestamptz ts PK
        float demand_mw
        float net_load_mw
        float price_hubavg
    }
    ACTUALS_DAILY {
        date day
        float peak_net_load_mw
        float max_price
        float max_strain
    }
```

</details>

| Table | Kind | Rows (Nov 7) |
|---|---|---|
| `forecasts` | **Hypertable** | 96 |
| `forecast_drivers` | Table | 288 |
| `daily_advice` | Table | 1 |
| `shift_scenarios` / `shift_scenario_curves` | Tables | 210 / 10,080 |
| `report_card` | Table | 92 |
| `strain_reference` | Table | 1,212 |
| `actuals` | **Hypertable** | 9,598 |
| `actuals_daily` | **Continuous aggregate** | 401 |

*(Column lists are simplified to the fields the dashboard uses; see `db/schema.sql` for the full DDL.)*

---

## 5. API endpoints → dashboard sections

```text
ENDPOINT  (FastAPI)                  TIGER SOURCE             DASHBOARD SECTION

┌────────────────────────────────┐   forecasts                ┌────────────────────────────────────┐
│        GET /api/health         │───────────────────────────►│          Hero · Live pill          │
└────────────────────────────────┘                            └────────────────────────────────────┘

┌────────────────────────────────┐   forecasts + strain_ref   ┌────────────────────────────────────┐
│   GET /api/forecast?hours=48   │───────────────────────────►│   Hero · Timeline · Best · Spike   │
└────────────────────────────────┘                            └────────────────────────────────────┘

┌────────────────────────────────┐   forecast_drivers         ┌────────────────────────────────────┐
│ GET /api/forecast/drivers?ts=  │───────────────────────────►│          Why this color?           │
└────────────────────────────────┘                            └────────────────────────────────────┘

┌────────────────────────────────┐   daily_advice             ┌────────────────────────────────────┐
│        GET /api/advice         │───────────────────────────►│    Your plan · Why-red sentence    │
└────────────────────────────────┘                            └────────────────────────────────────┘

┌────────────────────────────────┐   + Gemini (live)          ┌────────────────────────────────────┐
│         POST /api/chat         │───────────────────────────►│   Ask GridWise -> timeline glow    │
└────────────────────────────────┘                            └────────────────────────────────────┘

┌────────────────────────────────┐   shift_scenarios          ┌────────────────────────────────────┐
│       GET /api/simulate        │───────────────────────────►│          Ripple simulator          │
└────────────────────────────────┘                            └────────────────────────────────────┘

┌────────────────────────────────┐   report_card              ┌────────────────────────────────────┐
│  GET /api/report-card?days=7   │───────────────────────────►│            Report card             │
└────────────────────────────────┘                            └────────────────────────────────────┘

┌────────────────────────────────┐   actuals_daily (cagg)     ┌────────────────────────────────────┐
│    GET /api/history?days=30    │───────────────────────────►│            Last 30 days            │
└────────────────────────────────┘                            └────────────────────────────────────┘
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
flowchart LR
    subgraph EP["FastAPI /api"]
        H["GET /health"]
        F["GET /forecast?hours=48"]
        D["GET /forecast/drivers?ts="]
        A["GET /advice"]
        S["GET /simulate?pct&kwh&from&to"]
        R["GET /report-card?days=7"]
        HI["GET /history?days=30"]
        C["POST /chat"]
    end

    subgraph SEC["Dashboard sections"]
        HERO["🚦 Hero + Live pill"]
        TL["📊 48-h timeline"]
        WHY["❓ Why this color?"]
        BH["✅ Best hours"]
        PLAN["🤖 Your plan"]
        SP["💸 Spike risk"]
        ASK["💬 Ask GridWise"]
        RIP["🌊 Ripple"]
        RC["📋 Report card"]
        H30["📈 Last 30 days"]
    end

    H --> HERO
    F --> HERO & TL & BH & SP
    D --> WHY
    A --> PLAN & WHY
    C --> ASK
    S --> RIP
    R --> RC
    HI --> H30
    ASK -. "highlight_hours" .-> TL
    TL -. "selected hour" .-> WHY
    SP -. "click point" .-> WHY
```

</details>

| Endpoint | Tiger source | Typical latency |
|---|---|---|
| `GET /api/health` | `forecasts` (latest `run_ts`) | ~50 ms |
| `GET /api/forecast` | `forecasts` + `strain_reference` | ~110 ms |
| `GET /api/forecast/drivers` | `forecast_drivers` + `daily_advice.why_red` | ~190 ms |
| `GET /api/advice` | `daily_advice` | ~200 ms |
| `GET /api/simulate` | `shift_scenarios` + `_curves` | ~160 ms |
| `GET /api/report-card` | `report_card` | ~70 ms |
| `GET /api/history` | `actuals_daily` | ~60 ms |
| `POST /api/chat` | `forecasts` + `daily_advice` → **Gemini** | ~0.8–5 s |

---

## 6. Frontend architecture

### 6.1 Component tree

```text
                              ┌──────────────────────────────────────┐
                              │            app/layout.tsx            │
                              │       Geist fonts · dark theme       │
                              └───────────────────┬──────────────────┘
                                                  ▼
                              ┌──────────────────────────────────────┐
                              │          app/providers.tsx           │
                              │    TanStack Query · MotionConfig     │
                              └───────────────────┬──────────────────┘
                                                  ▼
                         ╔════════════════════════════════════════════════╗
                         ║                 Dashboard.tsx                  ║
                         ║     5 queries · selected hour · highlights     ║
                         ╚════════════════════════┬═══════════════════════╝
                                                  ▼
┌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┐
╎  renders  (src/components/)                                                                      ╎
╎                                                                                                  ╎
╎ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐   ╎
╎ │ Aurora shader  │ │     TopBar     │ │     Header     │ │ StrainTimeline │ │  WhyRedPanel   │   ╎
╎ │    page bg     │ │   sticky nav   │ │ verdict + ring │ │   48-h bars    │ │  SHAP drivers  │   ╎
╎ └────────────────┘ └────────────────┘ └────────────────┘ └────────────────┘ └────────────────┘   ╎
╎                                                                                                  ╎
╎ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐   ╎
╎ │ BestHoursCard  │ │  AdvicePanel   │ │   SpikeChart   │ │    ChatBox     │ │  RipplePanel   │   ╎
╎ │    windows     │ │   daily plan   │ │ P(price>$100)  │ │  Gemini chat   │ │ ripple shader  │   ╎
╎ └────────────────┘ └────────────────┘ └────────────────┘ └────────────────┘ └────────────────┘   ╎
╎                                                                                                  ╎
╎ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐                                         ╎
╎ │   ReportCard   │ │  HistoryChart  │ │     Footer     │                                         ╎
╎ │    accuracy    │ │  30-day peaks  │ │    credits     │                                         ╎
╎ └────────────────┘ └────────────────┘ └────────────────┘                                         ╎
╎                                                                                                  ╎
└╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┘

┌──────────────────────────────────────────────┐    ┌──────────────────────────────────────────────┐
│         SHARED: ui.tsx · motion.tsx          │    │       lib/: api.ts (fetch + fallbacks)       │
│         insights/ · shader/ (WebGL)          │    │      types · format · drivers · offline      │
└──────────────────────────────────────────────┘    └──────────────────────────────────────────────┘
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
flowchart TB
    L["app/layout.tsx<br/>Geist fonts · dark theme"] --> P["app/providers.tsx<br/>TanStack Query · MotionConfig"]
    P --> PG["app/page.tsx"] --> DSH["Dashboard.tsx<br/>queries + shared state"]

    DSH --> BG["shader/AuroraBackground"]
    DSH --> TOP["hero/TopBar<br/>sticky nav"]
    DSH --> HDR["Header<br/>verdict · StrainGauge · PowerLines shader"]
    DSH --> ST["StrainTimeline"]
    DSH --> WR["WhyRedPanel"]
    DSH --> BHC["BestHoursCard"]
    DSH --> AP["AdvicePanel"]
    DSH --> SC["SpikeChart"]
    DSH --> CB["ChatBox"]
    DSH --> RP["RipplePanel<br/>+ RippleField shader"]
    DSH --> RCD["ReportCard"]
    DSH --> HC["HistoryChart"]
    DSH --> FT["Footer"]

    subgraph SHARED["Shared building blocks"]
        UIK["ui.tsx<br/>Card · Badge · Stat · LevelPill"]
        MO["motion.tsx<br/>Reveal · Stagger · AnimatedNumber"]
        INS["insights/<br/>sliders · segmented · tiles"]
        SH["shader/<br/>ShaderCanvas · GLSL"]
    end

    subgraph LIB["lib/"]
        APIC["api.ts<br/>fetch + fallbacks"]
        TY["types.ts"]
        FMT["format.ts<br/>Central time · colors"]
        DRV["drivers.ts"]
        OFF["offlineChat.ts · simulate.ts"]
    end

    DSH --> APIC
```

</details>

### 6.2 State and data flow inside the page

```text
┌──────────────────────────┐        ┌──────────────────────────┐        ┌──────────────────────────┐
│   TanStack Query cache   │        │  Timeline / SpikeChart   │        │      selected hour       │
│   forecast · advice ·    │───────►│ tap · arrow keys · click │───────►│     Dashboard state      │
│     health · history     │        │    glows on highlight    │        │    pre-set: peak hour    │
└──────────────────────────┘        └──────────────────────────┘        └─────────────┬────────────┘
                                                  ▲                                   │
                                                  │                                   │
                                                  │                                   ▼
┌──────────────────────────┐        ┌─────────────┴────────────┐        ┌──────────────────────────┐
│         ChatBox          │        │     highlight hours      │        │     Why this color?      │
│      POST /api/chat      │───────►│     Dashboard state      │        │        own query:        │
│    -> highlight_hours    │        │     -> timeline glow     │        │     GET /drivers?ts=     │
└──────────────────────────┘        └──────────────────────────┘        └──────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│   RipplePanel · own query /api/simulate · 250 ms debounce    │
└──────────────────────────────────────────────────────────────┘

Query policy: 5-min stale · refetch every 10 min · report-card & history cached 1 h
Loading states use isPending (same on server and client → no hydration mismatch)
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
flowchart LR
    subgraph Q["TanStack Query cache"]
        QH["health"]
        QF["forecast"]
        QA["advice"]
        QR["report-card"]
        QHI["history"]
    end

    subgraph S["Dashboard state"]
        SEL["selected hour"]
        HL["highlight hours"]
    end

    QF --> TLc["Timeline"] & HEROc["Hero"] & SPc["Spike chart"] & BHc["Best hours"]
    TLc -- "tap / arrow keys" --> SEL
    SPc -- "click" --> SEL
    SEL --> WHYc["Why this color?<br/>(own query: drivers)"]
    CHATc["Chat"] -- "answer.highlight_hours" --> HL --> TLc
    RIPc["Ripple<br/>(own query: simulate,<br/>debounced 250 ms)"]
```

</details>

- **On first load**, the most-strained hour is pre-selected so "Why this color?" is never empty.
- **Query policy:** 5-min stale time, auto-refetch every 10 min; report card and history cache for 1 h.
- **Hydration-safe:** loading states use `isPending` (identical on server and client).

---

## 7. Request flows

### 7.1 Page load

```text
┌──────────────┐    ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│     User     │    │   Next.js    │      │   FastAPI    │      │  Tiger Data  │
└───────┬──────┘    └───────┬──────┘      └───────┬──────┘      └───────┬──────┘
        │                   │                     │                     │
        │ open :3000        │                     │                     │
        │──────────────────►│                     │                     │
        │                   │                     │                     │
        │ shell+skeletons   │                     │                     │
        │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                     │                     │
        │                   │                     │                     │
        │                   │ 5 GETs parallel     │                     │
        │                   │────────────────────►│                     │
        │                   │                     │                     │
        │                   │                     │ SQL                 │
        │                   │                     │────────────────────►│
        │                   │                     │                     │
        │                   │                     │ rows                │
        │                   │                     │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│
        │                   │                     │                     │
        │                   │ JSON                │                     │
        │                   │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                     │
        │                   │                     │                     │
        │ charts animate in │                     │                     │
        │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                     │                     │
        │                   │                     │                     │
        │                   │ GET drivers?ts=     │                     │
        │                   │────────────────────►│                     │
        │                   │                     │                     │
        │                   │ top-3 drivers       │                     │
        │                   │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                     │
        │                   │                     │                     │
        │ Why panel filled  │                     │                     │
        │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                     │                     │
        │                   │                     │                     │
        │                   │                     │                     │
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant W as Next.js page
    participant A as FastAPI
    participant T as Tiger Data

    U->>W: open localhost:3000
    W-->>U: HTML shell + skeletons + shaders start
    par parallel queries
        W->>A: GET /api/health
        W->>A: GET /api/forecast?hours=48
        W->>A: GET /api/advice
        W->>A: GET /api/report-card?days=7
        W->>A: GET /api/history?days=30
    end
    A->>T: SQL (latest run_ts, hours, advice, ...)
    T-->>A: rows
    A-->>W: JSON
    W-->>U: hero, timeline, plan, charts animate in
    W->>A: GET /api/forecast/drivers?ts=peak hour
    A-->>W: top-3 SHAP drivers
    W-->>U: "Why this color?" filled
```

</details>

### 7.2 Chat

```text
 ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐
 │    User    │    │  ChatBox   │    │  FastAPI   │    │ Tiger Data │    │   Gemini   │
 └──────┬─────┘    └──────┬─────┘    └──────┬─────┘    └──────┬─────┘    └──────┬─────┘
        │                 │                 │                 │                 │
        │ EV question     │                 │                 │                 │
        │────────────────►│                 │                 │                 │
        │                 │                 │                 │                 │
        │                 │ POST /chat      │                 │                 │
        │                 │────────────────►│                 │                 │
        │                 │                 │                 │                 │
        │                 │                 ├──┐              │                 │
        │                 │                 │  │ rate limits  │                 │
        │                 │                 │◄─┘              │                 │
        │                 │                 │                 │                 │
        │                 │                 │ 48h + plan      │                 │
        │                 │                 │────────────────►│                 │
        │                 │                 │                 │                 │
        │                 │                 │ rows            │                 │
        │                 │                 │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                 │
        │                 │                 │                 │                 │
        │                 │                 │ grounded prompt │                 │
        │                 │                 │──────────────────────────────────►│
        │                 │                 │                 │                 │
        │                 │                 │ answer+hours    │                 │
        │                 │                 │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│
        │                 │                 │                 │                 │
        │                 │ JSON            │                 │                 │
        │                 │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                 │                 │
        │                 │                 │                 │                 │
        │ bubble + glow   │                 │                 │                 │
        │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                 │                 │                 │
        │                 │                 │                 │                 │
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant W as ChatBox
    participant A as FastAPI /api/chat
    participant L as Rate limiter
    participant T as Tiger Data
    participant G as Gemini 2.5 Flash

    U->>W: "When should I charge my EV?"
    W->>A: POST {question}
    A->>L: ≤ 500 chars? ≤ 10/min for this IP?
    alt over limit
        L-->>W: 422 / 429
    else allowed
        A->>T: latest 48 h + daily plan
        T-->>A: rows
        alt Gemini available and under global cap
            A->>G: grounded prompt (forecast JSON + question)
            G-->>A: {answer, highlight_hours}
        else quota / error
            A->>A: rules engine answer
        end
        A-->>W: {answer, highlight_hours}
        W-->>U: bubble + hours glow on timeline
    end
```

</details>

### 7.3 Ripple simulator

```text
┌──────────────┐    ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│     User     │    │ RipplePanel  │      │   FastAPI    │      │  Tiger Data  │
└───────┬──────┘    └───────┬──────┘      └───────┬──────┘      └───────┬──────┘
        │                   │                     │                     │
        │ drag slider       │                     │                     │
        │──────────────────►│                     │                     │
        │                   │                     │                     │
        │                   ├──┐                  │                     │
        │                   │  │ debounce 250ms   │                     │
        │                   │◄─┘                  │                     │
        │                   │                     │                     │
        │                   │ GET /simulate       │                     │
        │                   │────────────────────►│                     │
        │                   │                     │                     │
        │                   │                     │ nearest of 210      │
        │                   │                     │────────────────────►│
        │                   │                     │                     │
        │                   │                     │ scenario+curve      │
        │                   │                     │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│
        │                   │                     │                     │
        │                   │ peak cut, curve     │                     │
        │                   │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                     │
        │                   │                     │                     │
        │ tween + morph     │                     │                     │
        │◄╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌│                     │                     │
        │                   │                     │                     │
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant R as RipplePanel
    participant A as FastAPI /api/simulate
    participant T as Tiger Data

    U->>R: drag "Homes participating" to 20%
    Note over R: debounce 250 ms · keep previous result on screen
    R->>A: GET /simulate?pct=20&kwh=5&from=17-21&to=10-14
    A->>T: nearest of 210 precomputed scenarios
    T-->>A: scenario stats + 48-h before/after curve
    A-->>R: peak cut · peakers avoided · curve
    R-->>U: numbers tween · after-curve morphs · rings speed up
```

</details>

---

## 8. Freshness: how new data reaches the page

```text
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Laptop / CI  │    │  Databricks  │    │  refresh.py  │    │  Tiger Data  │    │  Dashboard   │
└───────┬──────┘    └───────┬──────┘    └───────┬──────┘    └───────┬──────┘    └───────┬──────┘
        │                   │                   │                   │                   │
        │ ingest + trigger  │                   │                   │                   │
        │──────────────────►│                   │                   │                   │
        │                   │                   │                   │                   │
        │                   ├──┐                │                   │                   │
        │                   │  │ 9 tasks ~20m   │                   │                   │
        │                   │◄─┘                │                   │                   │
        │                   │                   │                   │                   │
        │                   │ new run? (5 min)  │                   │                   │
        │                   │◄──────────────────│                   │                   │
        │                   │                   │                   │                   │
        │                   │ yes: finished     │                   │                   │
        │                   │╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌►│                   │                   │
        │                   │                   │                   │                   │
        │                   │                   ├──┐                │                   │
        │                   │                   │  │ run db.sync    │                   │
        │                   │                   │◄─┘                │                   │
        │                   │                   │                   │                   │
        │                   │                   │ upsert Gold       │                   │
        │                   │                   │──────────────────►│                   │
        │                   │                   │                   │                   │
        │                   │                   │                   │ refetch (10 min)  │
        │                   │                   │                   │◄──────────────────│
        │                   │                   │                   │                   │
        │                   │                   │                   │ fresh data        │
        │                   │                   │                   │╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌►│
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
sequenceDiagram
    autonumber
    participant Dev as Laptop / GitHub Action
    participant V as UC Volume
    participant J as Databricks Job (9 tasks)
    participant R as API refresh loop
    participant S as db.sync
    participant T as Tiger Data
    participant W as Dashboard

    Dev->>V: ingestion.cli ingest --trigger-job (upload parquet)
    Dev->>J: trigger gridwise-hourly
    J->>J: bronze → … → advice (~15–20 min)
    loop every 5 min
        R->>J: newest finished run? (Jobs API, no compute)
    end
    R->>S: new run found → run sync
    S->>T: upsert Gold → Tiger (~20–35 s)
    loop every 10 min
        W->>T: refetch via API
    end
    Note over W: Live pill green · "Delayed" if forecast > 2 h old
```

</details>

| Trigger | What runs |
|---|---|
| `python -m tools.dev` | `db.sync` once at startup, then API + dashboard |
| API running | Jobs API poll every 5 min → auto `db.sync` |
| Forecast > 2 h old | API also checks Gold `max(run_ts)` via the SQL warehouse (≤ every 30 min) |
| Manual | `python -m db.sync` |

---

## 9. Resilience and fallbacks

```text
                              ┌──────────────────────────────────────┐
                              │          Dashboard request           │
                              └───────────────────┬──────────────────┘
                                                  │
                                                  ▼                            ┌───────────────────┐
                              ╔══════════════════════════════════════╗         │      SNAPSHOT     │
                              ║            API reachable?            ║── no ──►│ bundled real data │
                              ╚═══════════════════┬══════════════════╝         │    amber notice   │
                                                  │ yes                        └───────────────────┘
                                                  ▼
                              ╔══════════════════════════════════════╗         ┌───────────────────┐
                              ║         Forecast > 2 h old?          ║── yes ─►│    DELAYED pill   │
                              ╚═══════════════════┬══════════════════╝         │      + notice     │
                                                  │ no                         └───────────────────┘
                                                  ▼
                              ┌──────────────────────────────────────┐
                              │         LIVE  ·  green pill          │
                              └──────────────────────────────────────┘


┌────────────────────────┐        ╔════════════════════════╗        ┌──────────────────────────────┐
│  Chat / plan request   │───────►║ Gemini OK & under cap? ║─ yes ─►│ Gemini answer · Gemini badge │
└────────────────────────┘        ╚════════════┬═══════════╝        └──────────────────────────────┘
                                               │ no
                                               ▼
                                  ┌────────────────────────┐
                                  │      Rules engine      │
                                  │     'Rules' badge      │
                                  └────────────────────────┘


┌──────────────────────────────┐  ┌──────────────────────────────┐  ┌──────────────────────────────┐
│     npm run dev:fixtures     │  │    prefers-reduced-motion    │  │           no WebGL           │
│      demo, no API / DB       │  │    shaders: 1 still frame    │  │    plain dark background     │
└──────────────────────────────┘  └──────────────────────────────┘  └──────────────────────────────┘
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
flowchart TD
    REQ["Dashboard request"] --> UP{"API reachable?"}
    UP -- "yes" --> OK["Live data from Tiger"]
    UP -- "no / 5xx" --> SNAP["Bundled snapshot<br/>(real data, fixtures/*.json)<br/>+ amber 'may be outdated' notice"]
    OK --> AGE{"Forecast > 2 h old?"}
    AGE -- "yes" --> DEL["'Delayed' pill + notice"]
    AGE -- "no" --> LIVE["'Live' pill"]

    CHAT["Chat / plan"] --> GQ{"Gemini OK?"}
    GQ -- "yes" --> GEM["Gemini answer · 'Gemini' badge"]
    GQ -- "429 / error / cap" --> RULES["Rules engine · 'Rules' badge"]

    DEMO["npm run dev:fixtures"] --> FX["Full demo mode<br/>no API or DB needed"]

    MOT["prefers-reduced-motion"] --> STILL["Shaders render one still frame<br/>animations + count-ups skipped"]
    NOGL["No WebGL"] --> CSS["Plain dark background"]
```

</details>

---

## 10. Visual layer: shaders and motion

```text
┌────────────────────────────┐     ┌────────────────────────────┐     ┌────────────────────────────┐
│ AURORA  ·  page background │     │ POWER LINES  ·  hero card  │     │  RIPPLE RINGS  ·  Ripple   │
│ domain-warped energy field │     │  6 lines + current pulses  │     │     rings from 'homes'     │
│ tint = worst strain level  │     │     brighter when red      │     │  more homes = more rings   │
└────────────────────────────┘     └────────────────────────────┘     └────────────────────────────┘
               ▲                                  ▲                                  ▲
               │                                  │                                  │
               └──────────────────────────────────┼──────────────────────────────────┘
                                                  │
             ┌────────────────────────────────────┴───────────────────────────────────┐
             │       ShaderCanvas.tsx  ·  raw WebGL1  ·  1 full-screen triangle       │
             │  0.5-0.75x res · ≤45 fps · pause off-screen · still if reduced motion  │
             └────────────────────────────────────────────────────────────────────────┘

             ┌────────────────────────────────────────────────────────────────────────┐
             │        motion.tsx: Reveal · Stagger · AnimatedNumber · PulseDot        │
             │         glass cards: blur(18px) · gradient border · hover glow         │
             └────────────────────────────────────────────────────────────────────────┘
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
flowchart LR
    SC["ShaderCanvas.tsx<br/>raw WebGL1 · 1 full-screen triangle"] --> AUR["AURORA_FRAG<br/>page background"]
    SC --> PWR["POWERLINES_FRAG<br/>hero card"]
    SC --> RIP["RIPPLE_FRAG<br/>Ripple card"]

    TINT["peak strain level<br/>→ u_tint"] --> AUR & PWR
    PCT["homes participating<br/>→ u_amount"] --> RIP
    MOUSE["pointer → u_mouse"] --> AUR

    subgraph BUDGET["Performance guards"]
        B1["0.5–0.75× resolution"]
        B2["30–45 fps cap"]
        B3["pause off-screen / hidden tab"]
        B4["reduced-motion → still frame"]
    end
```

</details>

| Shader | Where | What it shows | Driven by |
|---|---|---|---|
| **Aurora** | Fixed page background | Domain-warped energy field + aurora band, pointer glow, film grain | Tomorrow's worst strain level (red / amber / green tint) |
| **Power lines** | Hero card | 6 glowing transmission lines with travelling current pulses | Strain color, intensity ↑ when red |
| **Ripple rings** | Ripple card | Water rings from multiple "homes" | Participation slider: more sources, faster, brighter |

**Motion** (`motion.tsx`, motion v12): `Reveal` (fade-up once), `Stagger`/`StaggerItem`, `AnimatedNumber` (count-up), `PulseDot` (live indicator). All respect reduced-motion.

**Surfaces:** frosted glass cards (`backdrop-filter: blur(18px)`), 1 px gradient border lit at the top edge, hover glow.

---

## 11. Deployment topologies

### 11.1 Local (current)

```text
                              ┌──────────────────────────────────────┐
                              │         python -m tools.dev          │
                              └───────────────────┬──────────────────┘
              ┌───────────────────────────────────┼───────────────────────────────────┐
              ▼                                   ▼                                   ▼
┌──────────────────────────┐        ┌──────────────────────────┐        ┌──────────────────────────┐
│    db.sync (startup)     │        │   uvicorn :8000  (API)   │◄───────│   next dev :3000  (UI)   │
└─────────────┬────────────┘        └───────┬───────────┬──────┘        └──────────────────────────┘
              │                             │           │        /api/*
              ▼                             │           │
┌──────────────────────────┐   SQL          │           │
│        TIGER DATA        │◄───────────────┘           │
└──────────────────────────┘                            │
                                                        ▼
                                    ┌──────────────────────────────────────────────────────────────┐
                                    │   GEMINI (live chat)  ·  DATABRICKS JOBS API (5-min poll)    │
                                    └──────────────────────────────────────────────────────────────┘
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
flowchart LR
    DEV["python -m tools.dev"] --> SY["db.sync"] --> TG[("Tiger Data")]
    DEV --> API["uvicorn :8000"]
    DEV --> NX["next dev :3000"]
    NX -- "localhost:8000/api" --> API --> TG
    API -.-> GM["Gemini"]
    API -.-> DBX["Databricks Jobs API"]
```

</details>

### 11.2 Single VM (ready: Vultr / any Docker host)

```text
                              ┌────────────────────────┐
                              │      User browser      │
                              └────────────┬───────────┘
                                           │ https://<your-domain>
                                           ▼
                              ┌────────────────────────┐
                              │      GoDaddy DNS       │
                              │   A record -> VM IP    │
                              └────────────┬───────────┘
                                           ▼
    ╔═════════════════ Vultr VM  (Ubuntu 24.04 + Docker Compose) ════════════════╗
    ║                                                                            ║
    ║                         ┌────────────────────────┐                         ║
    ║                         │    caddy :80 / :443    │                         ║
    ║                         │    auto-HTTPS proxy    │                         ║
    ║                         └────────────┬───────────┘                         ║
    ║                 ┌────────────────────┴────────────────────┐                ║
    ║                 │ /*                                      │ /api/*         ║
    ║                 ▼                                         ▼                ║
    ║    ┌────────────────────────┐                ┌────────────────────────┐    ║
    ║    │       web :3000        │                │       api :8000        │    ║
    ║    │   Next.js standalone   │                │   FastAPI x2 workers   │    ║
    ║    └────────────────────────┘                └────────────┬───────────┘    ║
    ║                                                           │                ║
    ║                                                           │                ║
    ║                                                           │                ║
    ╚═══════════════════════════════════════════════════════════╤════════════════╝
                                                                │
                                                ┌───────────────┴───────────────┐
                                                ▼ SQL                           ▼ chat
┌────────────────────────┐          ┌──────────────────────┐          ┌──────────────────┐
│     Databricks Job     │          │      Tiger Data      │          │    Gemini API    │
│       -> db.sync       │─────────►│  hypertables + cagg  │          │   chat answers   │
└────────────────────────┘          └──────────────────────┘          └──────────────────┘
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
flowchart LR
    U(("Browser")) --> DNS["GoDaddy DNS<br/>A record"] --> CAD
    subgraph VM["Vultr VM · docker compose"]
        CAD["Caddy :80/:443<br/>auto HTTPS"]
        WEBC["web<br/>Next.js standalone"]
        APIC["api<br/>FastAPI ×2 workers"]
        CAD -- "/*" --> WEBC
        CAD -- "/api/*" --> APIC
    end
    APIC --> TG[("Tiger Data")]
    APIC -.-> GM["Gemini"]
    APIC -.-> DBX["Databricks"]
```

</details>

`python -m tools.deploy_vultr --host <IP> [--domain example.tech]`. Locally verified end-to-end in Docker.

### 11.3 Serverless (ready: Vercel)

```text
                              ┌──────────────────────────────────────┐
                              │             User browser             │
                              └───────────────────┬──────────────────┘
                                                  │ https://<project>.vercel.app
                                                  ▼
                    ╔══════════════════════════════════════════════════════════╗
                    ║                VERCEL PROJECT: dashboard                 ║
                    ║         Next.js · rewrites /api/* -> API project         ║
                    ╚═════════════════════════════┬════════════════════════════╝
                                                  │ same-origin proxy (no CORS)
                                                  ▼
                    ╔══════════════════════════════════════════════════════════╗
                    ║                   VERCEL PROJECT: api                    ║
                    ║           api/index.py -> path shim -> FastAPI           ║
                    ╚═════════════════════════════┬════════════════════════════╝
                         ┌────────────────────────┴────────────────────────┐
                         │                                                 │
                         ▼                                                 ▼
          ┌────────────────────────────┐                    ┌────────────────────────────┐
          │         Tiger Data         │                    │       Gemini (chat)        │
          └────────────────────────────┘                    └────────────────────────────┘

Status: deployed + verified, then taken down on request. Redeploy ≈ 2 min.
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
flowchart LR
    U(("Browser")) --> FE["Vercel project: dashboard<br/>Next.js"]
    FE -- "rewrite /api/* (same origin)" --> BE["Vercel project: API<br/>api/index.py → FastAPI<br/>(path-restoring shim)"]
    BE --> TG[("Tiger Data")]
    BE -.-> GM["Gemini"]
```

</details>

Config is in the repo (`vercel.json`, `api/index.py`, `.vercelignore`, `tools/vercel_env.py`). It was deployed and verified, then **taken down on request**. Redeploying takes about 2 minutes. On serverless the auto-sync loop is off; run `db.sync` from a laptop.

---

## 12. Security model

```text
╔══════════════════════════════╗        ┌──────────────────────────┐      ┌────────────────────────┐
║     .env  ·  laptop only     ║        │    pre-commit scanner    │      │      GitHub repo       │
║         git-ignored          ║───────►│    + gitleaks Action     │─────►│      (no secrets)      │
║     never in images / JS     ║        │  blocks secret commits   │      └────────────────────────┘
╚═══════════════┬══════════════╝        └──────────────────────────┘
                │ runtime only (env_file / host env)
                │
                ▼
┌──────────────────────────────┐        ┌──────────────────────────┐      ┌────────────────────────┐
│         API process          │        │      Tiger · Gemini      │      │  VM: only 80/443 open  │
│      TIGER_DATABASE_URL      │───────►│        Databricks        │      │  containers non-root   │
│  GEMINI_API_KEY · DBX token  │        │    (server-side only)    │      └────────────────────────┘
└──────────────────────────────┘        └──────────────────────────┘
                ▲
                │ /api/* JSON
                │
┌───────────────┴──────────────┐        ┌──────────────────────────────┐
│           BROWSER            │        │       /api/chat guard        │
│       sees only JSON +       │───────►│ ≤ 500 chars · 10/min per IP  │
│   NEXT_PUBLIC_API_BASE_URL   │        │  global Gemini cap -> rules  │
└──────────────────────────────┘        └──────────────────────────────┘
```

<details>
<summary>Interactive Mermaid version (renders on GitHub)</summary>

```mermaid
flowchart TB
    ENV[".env (laptop only, git-ignored)"] --> PRE["pre-commit check_secrets.py<br/>+ gitleaks GitHub Action"]
    ENV -- "runtime only (env_file / Vercel env)" --> APIX["API process"]
    APIX --> TGX[("Tiger")] & GMX["Gemini"] & DBXX["Databricks"]
    BROWSER["Browser"] -- "never sees secrets<br/>only NEXT_PUBLIC_API_BASE_URL" --> APIX
    BROWSER --> LIM["/api/chat limits<br/>500 chars · 10/min/IP · global Gemini cap"]
```

</details>

- Secrets live only in `.env` (and the runtime environment); never in git, images, or client JS.
- `.dockerignore` / `.vercelignore` exclude every `.env*` file.
- Only ports 80/443 are public in the VM topology; containers run as non-root.
- The Databricks token is never sent to serverless hosts.

---

## 13. Tech stack summary

| Layer | Technology |
|---|---|
| Sources | ERCOT (gridstatus), EIA-930 API, Open-Meteo |
| Lakehouse | Databricks Free Edition: UC Volumes, Auto Loader, Delta, Jobs, SQL warehouse, Genie |
| ML | LightGBM, MLflow, Unity Catalog model registry, SHAP |
| AI | Gemini 2.5 Flash (plan, Why-red, chat) |
| Serving DB | Tiger Data: PostgreSQL 18 + TimescaleDB 2.31 (hypertables, continuous aggregate) |
| API | FastAPI, psycopg 3 + pool, uvicorn |
| Frontend | Next.js 15 (App Router, TS), Tailwind v4, Recharts, TanStack Query, motion v12, lucide, Geist |
| Graphics | Raw WebGL1 fragment shaders (aurora, power lines, ripple) |
| Deploy | `tools/dev.py` (local) · Docker + Caddy + Vultr · Vercel |
| Security | `.env` only, pre-commit scanner, gitleaks Action, chat rate limits |

**Run locally:** `python -m tools.dev` → dashboard http://localhost:3000 · API docs http://localhost:8000/api/docs
