"""Box diagrams for DASHBOARD_V3.md (plain text: identical in VS Code, GitHub and terminals).

    python docs/diagrams/gen_dashboard_v3.py docs/diagrams/DASHBOARD_V3.template.md DASHBOARD_V3.md
    python docs/diagrams/gen_dashboard_v3.py --preview          # print every diagram
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boxlib import C, seq  # noqa: E402

V = {}


def down(c, x, y_from, y_to, label=None, dashed=False):
    """Arrow from a box's bottom border (y_from) to just above the next box's top border (y_to)."""
    c.put(x, y_from, '┬')
    if y_to - 1 > y_from + 1:
        c.vl(x, y_from + 1, y_to - 2, '╎' if dashed else '│')
    c.put(x, y_to - 1, '▼')
    if label:
        c.put(x + 2, y_from + 1, label)


def right(c, x_border, x_next, y, label=None, dashed=False):
    """Arrow from a box's right border (x_border) to the next box's left border (x_next)."""
    ch = '╌' if dashed else '─'
    c.put(x_border + 1, y, ch * (x_next - x_border - 2) + '►')
    if label:
        c.put(x_border + 2, y - 1, label)


def left(c, x_border, x_next, y):
    """Arrow pointing left: from box with left border x_border to box with right border x_next."""
    c.put(x_next + 1, y, '◄' + '─' * (x_border - x_next - 2))


# ───────────────────────── V1 system overview ─────────────────────────
c = C(100, 60)
c.box(0, 0, 30, ["ERCOT (gridstatus)", "load · prices · wind/solar"])
c.box(35, 0, 30, ["EIA-930 API", "hourly history 2023+"])
c.box(70, 0, 30, ["OPEN-METEO", "weather · 4 Texas cities"])
for x in (15, 50, 85):
    c.put(x, 3, '┬'); c.vl(x, 4, 4)
c.hl(15, 85, 5); c.put(15, 5, '└'); c.put(50, 5, '┼'); c.put(85, 5, '┘')
c.vl(50, 6, 6); c.put(50, 7, '▼')
c.box(25, 8, 50, ["INGESTION WORKER  ·  python -m ingestion.cli", "fetch -> parquet -> upload into a UC Volume"])
down(c, 50, 11, 14, "files.upload")
c.box(0, 14, 100, [], h=24, style='double')
c.put(1, 15, "DATABRICKS FREE EDITION   ·   one Job: gridwise-hourly (9 tasks)".center(98))
c.box(3, 17, 22, ["UC VOLUME", "landing/ parquet"])
c.box(27, 17, 22, ["BRONZE", "Auto Loader"])
c.box(51, 17, 22, ["SILVER", "hourly · DST-safe"])
c.box(75, 17, 22, ["GOLD", "features · strain"])
for x in (24, 48, 72):
    c.put(x + 1, 18, '─►')
down(c, 86, 20, 23)
c.box(3, 23, 22, ["GEMINI ADVICE", "daily plan +", "Why-red (rules fb)"])
c.box(27, 23, 22, ["RIPPLE", "210 what-if", "scenarios"])
c.box(51, 23, 22, ["SHAP", "top-3 drivers", "per forecast hour"])
c.box(75, 23, 22, ["MODELS A · B · D", "LightGBM · MLflow", "UC @champion"])
for x in (24, 48, 72):
    c.put(x + 1, 25, '◄─')
for x in (14, 38, 62, 86):
    c.put(x, 27, '┬'); c.vl(x, 28, 28)
c.hl(14, 86, 29); c.put(14, 29, '└'); c.put(38, 29, '┴'); c.put(62, 29, '┴'); c.put(86, 29, '┘'); c.put(50, 29, '┬')
c.put(50, 30, '▼')
c.box(15, 31, 70, ["GOLD SERVING TABLES", "forecasts · forecast_drivers · daily_advice",
                   "shift_scenarios · report_card · strain_reference"])
c.put(50, 35, '┬'); c.vl(50, 36, 36); c.put(50, 37, '╪'); c.vl(50, 38, 38); c.put(50, 39, '▼')
c.put(52, 38, "db.sync  (SQL warehouse -> upsert)")
c.box(25, 40, 50, ["TIGER DATA  ·  PostgreSQL + TimescaleDB", "hypertables · continuous aggregate"])
down(c, 50, 43, 46, "SQL (ms)")
c.box(25, 46, 50, ["FASTAPI  ·  8 endpoints  ·  :8000", "chat limits · auto-sync loop"])
c.box(81, 46, 19, ["GEMINI", "2.5 Flash", "live chat"])
c.put(75, 47, '╌╌╌╌╌►')
down(c, 50, 49, 52, "JSON /api/*")
c.box(25, 52, 50, ["NEXT.JS DASHBOARD  ·  :3000", "shaders · timeline · Ripple · chat"])
down(c, 50, 55, 57)
c.box(38, 57, 24, ["USER"])
V['V1'] = c.out()

# ───────────────────────── V2 Databricks job DAG ─────────────────────────
c = C(104, 21)
A = [["01_bronze", "Auto Loader", "→ bronze.* (7)"], ["02_silver", "hourly · DST-safe", "→ silver.*"],
     ["03_gold", "features · strain", "→ strain_reference"], ["05_predict", "Models A · D · B", "→ forecasts"]]
for i, ls in enumerate(A):
    c.box(i * 26, 0, 23, ls)
for x in (22, 48, 74):
    c.put(x + 1, 2, '──►')
c.put(101, 2, '─┐'); c.vl(102, 3, 9); c.put(101, 10, '◄┘')
B = [["genie_comments", "table docs", "→ Genie space"], ["09_advice", "Gemini / rules", "→ daily_advice"],
     ["08_ripple", "210 scenarios", "→ shift_scenarios"], ["06_explain", "SHAP top-3", "→ forecast_drivers"]]
for i, ls in enumerate(B):
    c.box(i * 26, 8, 23, ls)
for x in (22, 48, 74):
    c.put(x + 1, 10, '◄──')
down(c, 89, 12, 15)
c.box(78, 15, 23, ["07_report_card", "forecast vs actual", "→ report_card"])
c.hl(38, 77, 17); c.put(37, 17, '└'); c.vl(37, 14, 16); c.put(37, 13, '▲')
c.put(40, 16, "report_card + ripple both feed advice")
V['V2'] = c.out()

# ───────────────────────── V3 serving layer ─────────────────────────
c = C(100, 27)
c.box(0, 0, 30, ["DATABRICKS", "Gold tables", "SQL warehouse", "Jobs API"], style='double')
c.box(36, 0, 26, ["db/sync.py", "read Gold -> upsert", "~20-35 s"])
c.box(68, 0, 32, ["TIGER DATA", "Postgres 18 + TimescaleDB", "hypertables: forecasts,", "actuals",
                   "cagg: actuals_daily", "+ 6 plain tables"], style='double')
right(c, 29, 36, 2)
right(c, 61, 68, 2)
c.box(0, 11, 100, [], h=12, style='double')
c.put(3, 12, "FASTAPI  ·  backend/app  ·  uvicorn :8000")
mods = [["main.py", "8 routes", "chat limits"], ["core.py", "summaries", "Ripple snap"],
        ["db.py", "psycopg pool", "lazy open"], ["gemini.py", "grounded chat", "cache + errors"],
        ["refresh.py", "poll Jobs API", "-> run db.sync"]]
for i, ls in enumerate(mods):
    c.box(2 + i * 19, 14, 18, ls)
c.put(20, 16, '►'); c.put(39, 16, '►')
c.put(49, 14, '┴'); c.vl(49, 12, 13); c.put(49, 11, '╪'); c.vl(49, 10, 10)
c.put(49, 9, '┌'); c.hl(50, 83, 9); c.put(84, 9, '┘'); c.put(84, 8, '▲')
c.put(55, 8, "SQL reads")
c.put(14, 20, "limits: ≤500 chars · 10/min per IP · Gemini cap")
c.put(14, 21, "refresh.py: Jobs API poll (5 min) -> db.sync")
c.put(68, 18, '┬'); c.vl(68, 19, 21); c.put(68, 22, '╪'); c.put(68, 23, '▼')
c.box(58, 24, 21, ["GEMINI 2.5 FLASH"])
c.put(11, 18, '┬'); c.vl(11, 19, 21); c.put(11, 22, '╪'); c.put(11, 23, '▼'); c.put(13, 23, "JSON")
c.box(0, 24, 23, ["NEXT.JS DASHBOARD"])
V['V3'] = c.out()

# ───────────────────────── V4 Tiger schema ─────────────────────────
c = C(100, 30)
c.box(0, 0, 30, ["forecast_drivers", "run_ts · target_ts", "rank (1-3) · feature", "contribution_mw"],
      align='l', header=1)
c.box(35, 0, 30, ["forecasts  [HYPERTABLE]", "run_ts · target_ts (PK)", "net_load p10/p50/p90",
                   "demand_p50 · spike_prob", "strain_index · level", "low_confidence"],
      align='l', header=1, style='double')
c.box(70, 0, 30, ["daily_advice", "run_ts · date_local", "headline · tips (json)", "why_red (json)",
                   "generated_by"], align='l', header=1)
c.put(30, 3, '◄───►'); c.put(31, 2, 'N:1')
c.put(65, 3, '◄───►'); c.put(66, 2, '1:1')
c.put(40, 8, '┬'); c.vl(40, 9, 9); c.put(40, 10, '┘'); c.hl(16, 39, 10); c.put(15, 10, '┌'); c.put(15, 11, '▼')
c.put(17, 9, "re-scored per run")
c.box(0, 12, 30, ["shift_scenarios", "run_ts · pct · kwh", "from / to window", "peak_reduction_mw"],
      align='l', header=1)
c.box(35, 12, 30, ["shift_scenario_curves", "scenario key · target_ts", "before_mw · after_mw",
                    "spike_before / after"], align='l', header=1)
c.put(30, 15, '────►'); c.put(30, 14, '1:48')
c.box(70, 12, 30, ["report_card", "date · basis", "mape · demand_mape", "spike_recall", "band_coverage"],
      align='l', header=1)
c.box(0, 22, 30, ["actuals  [HYPERTABLE]", "ts (PK) · demand_mw", "net_load_mw", "price_hubavg"],
      align='l', header=1, style='double')
c.box(35, 22, 30, ["actuals_daily  [CAGG]", "day · peak_net_load", "max_price · max_strain",
                    "auto-refreshed rollup"], align='l', header=1, style='double')
c.put(30, 25, '────►'); c.put(30, 24, 'roll')
c.box(70, 22, 30, ["strain_reference", "month · percentile", "net_load_mw", "-> strain colors"],
      align='l', header=1)
V['V4'] = c.out()

# ───────────────────────── V5 endpoints -> sections ─────────────────────────
rows = [("GET /api/health", "forecasts", "Hero · Live pill"),
        ("GET /api/forecast?hours=48", "forecasts + strain_ref", "Hero · Timeline · Best · Spike"),
        ("GET /api/forecast/drivers?ts=", "forecast_drivers", "Why this color?"),
        ("GET /api/advice", "daily_advice", "Your plan · Why-red sentence"),
        ("POST /api/chat", "+ Gemini (live)", "Ask GridWise -> timeline glow"),
        ("GET /api/simulate", "shift_scenarios", "Ripple simulator"),
        ("GET /api/report-card?days=7", "report_card", "Report card"),
        ("GET /api/history?days=30", "actuals_daily (cagg)", "Last 30 days")]
c = C(100, 2 + 4 * len(rows))
c.put(0, 0, "ENDPOINT  (FastAPI)"); c.put(37, 0, "TIGER SOURCE"); c.put(62, 0, "DASHBOARD SECTION")
for i, (ep, tb, sec) in enumerate(rows):
    y = 2 + i * 4
    c.box(0, y, 34, [ep])
    c.put(34, y + 1, '─' * 27 + '►')
    c.put(37, y, tb)
    c.box(62, y, 38, [sec])
V['V5'] = c.out()

# ───────────────────────── V6 component tree ─────────────────────────
c = C(100, 39)
c.box(30, 0, 40, ["app/layout.tsx", "Geist fonts · dark theme"])
down(c, 50, 3, 5)
c.box(30, 5, 40, ["app/providers.tsx", "TanStack Query · MotionConfig"])
down(c, 50, 8, 10)
c.box(25, 10, 50, ["Dashboard.tsx", "5 queries · selected hour · highlights"], style='double')
down(c, 50, 13, 15)
c.box(0, 15, 100, [], h=19, style='dashed')
c.put(3, 16, "renders  (src/components/)")
grid = [[["Aurora shader", "page bg"], ["TopBar", "sticky nav"], ["Header", "verdict + ring"],
         ["StrainTimeline", "48-h bars"], ["WhyRedPanel", "SHAP drivers"]],
        [["BestHoursCard", "windows"], ["AdvicePanel", "daily plan"], ["SpikeChart", "P(price>$100)"],
         ["ChatBox", "Gemini chat"], ["RipplePanel", "ripple shader"]],
        [["ReportCard", "accuracy"], ["HistoryChart", "30-day peaks"], ["Footer", "credits"]]]
for r, items in enumerate(grid):
    for i, ls in enumerate(items):
        c.box(2 + i * 19, 18 + r * 5, 18, ls)
c.box(0, 35, 48, ["SHARED: ui.tsx · motion.tsx", "insights/ · shader/ (WebGL)"])
c.box(52, 35, 48, ["lib/: api.ts (fetch + fallbacks)", "types · format · drivers · offline"])
V['V6'] = c.out()

# ───────────────────────── V7 state flow ─────────────────────────
c = C(100, 20)
c.box(0, 0, 28, ["TanStack Query cache", "forecast · advice ·", "health · history"])
c.box(36, 0, 28, ["Timeline / SpikeChart", "tap · arrow keys · click", "glows on highlight"])
c.box(72, 0, 28, ["selected hour", "Dashboard state", "pre-set: peak hour"])
right(c, 27, 36, 2)
right(c, 63, 72, 2)
down(c, 86, 4, 8)
c.box(72, 8, 28, ["Why this color?", "own query:", "GET /drivers?ts="])
c.box(0, 8, 28, ["ChatBox", "POST /api/chat", "-> highlight_hours"])
c.box(36, 8, 28, ["highlight hours", "Dashboard state", "-> timeline glow"])
right(c, 27, 36, 10)
c.put(50, 8, '┴'); c.vl(50, 6, 7); c.put(50, 5, '▲')
c.box(0, 14, 64, ["RipplePanel · own query /api/simulate · 250 ms debounce"])
c.put(0, 18, "Query policy: 5-min stale · refetch every 10 min · report-card & history cached 1 h")
c.put(0, 19, "Loading states use isPending (same on server and client → no hydration mismatch)")
V['V7'] = c.out()

# ───────────────────────── V8–V11 sequences ─────────────────────────
V['V8'] = seq([("User", 8), ("Next.js", 28), ("FastAPI", 50), ("Tiger Data", 72)], 16, [
    (0, 1, 'open :3000'),
    (1, 0, 'shell+skeletons', True),
    (1, 2, '5 GETs parallel'),
    (2, 3, 'SQL'),
    (3, 2, 'rows', True),
    (2, 1, 'JSON', True),
    (1, 0, 'charts animate in', True),
    (1, 2, 'GET drivers?ts='),
    (2, 1, 'top-3 drivers', True),
    (1, 0, 'Why panel filled', True),
])

V['V9'] = seq([("User", 8), ("ChatBox", 26), ("FastAPI", 44), ("Tiger Data", 62), ("Gemini", 80)], 14, [
    (0, 1, 'EV question'),
    (1, 2, 'POST /chat'),
    ('self', 2, 'rate limits'),
    (2, 3, '48h + plan'),
    (3, 2, 'rows', True),
    (2, 4, 'grounded prompt'),
    (4, 2, 'answer+hours', True),
    (2, 1, 'JSON', True),
    (1, 0, 'bubble + glow', True),
])

V['V10'] = seq([("User", 8), ("RipplePanel", 28), ("FastAPI", 50), ("Tiger Data", 72)], 16, [
    (0, 1, 'drag slider'),
    ('self', 1, 'debounce 250ms'),
    (1, 2, 'GET /simulate'),
    (2, 3, 'nearest of 210'),
    (3, 2, 'scenario+curve', True),
    (2, 1, 'peak cut, curve', True),
    (1, 0, 'tween + morph', True),
])

V['V11'] = seq([("Laptop / CI", 8), ("Databricks", 28), ("refresh.py", 48), ("Tiger Data", 68),
                ("Dashboard", 88)], 16, [
    (0, 1, 'ingest + trigger'),
    ('self', 1, '9 tasks ~20m'),
    (2, 1, 'new run? (5 min)'),
    (1, 2, 'yes: finished', True),
    ('self', 2, 'run db.sync'),
    (2, 3, 'upsert Gold'),
    (4, 3, 'refetch (10 min)'),
    (3, 4, 'fresh data', True),
])

# ───────────────────────── V12 resilience ─────────────────────────
c = C(100, 35)
c.box(30, 0, 40, ["Dashboard request"])
down(c, 50, 2, 5)
c.box(30, 5, 40, ["API reachable?"], style='double')
c.put(70, 6, '── no ──►')
c.box(79, 4, 21, ["SNAPSHOT", "bundled real data", "amber notice"])
down(c, 50, 7, 10, "yes")
c.box(30, 10, 40, ["Forecast > 2 h old?"], style='double')
c.put(70, 11, '── yes ─►')
c.box(79, 10, 21, ["DELAYED pill", "+ notice"])
down(c, 50, 12, 15, "no")
c.box(30, 15, 40, ["LIVE  ·  green pill"])
c.box(0, 20, 26, ["Chat / plan request"])
right(c, 25, 34, 21)
c.box(34, 20, 26, ["Gemini OK & under cap?"], style='double')
c.put(60, 21, '─ yes ─►')
c.box(68, 20, 32, ["Gemini answer · Gemini badge"])
down(c, 47, 22, 25, "no")
c.box(34, 25, 26, ["Rules engine", "'Rules' badge"])
c.box(0, 31, 32, ["npm run dev:fixtures", "demo, no API / DB"])
c.box(34, 31, 32, ["prefers-reduced-motion", "shaders: 1 still frame"])
c.box(68, 31, 32, ["no WebGL", "plain dark background"])
V['V12'] = c.out()

# ───────────────────────── V13 shaders ─────────────────────────
c = C(100, 18)
c.box(0, 0, 30, ["AURORA  ·  page background", "domain-warped energy field", "tint = worst strain level"])
c.box(35, 0, 30, ["POWER LINES  ·  hero card", "6 lines + current pulses", "brighter when red"])
c.box(70, 0, 30, ["RIPPLE RINGS  ·  Ripple", "rings from 'homes'", "more homes = more rings"])
for x in (15, 50, 85):
    c.put(x, 5, '▲'); c.vl(x, 6, 6)
c.hl(15, 85, 7); c.put(15, 7, '└'); c.put(50, 7, '┼'); c.put(85, 7, '┘')
c.vl(50, 8, 8)
c.box(13, 9, 74, ["ShaderCanvas.tsx  ·  raw WebGL1  ·  1 full-screen triangle",
                  "0.5-0.75x res · ≤45 fps · pause off-screen · still if reduced motion"])
c.put(50, 9, '┴')
c.box(13, 14, 74, ["motion.tsx: Reveal · Stagger · AnimatedNumber · PulseDot",
                   "glass cards: blur(18px) · gradient border · hover glow"])
V['V13'] = c.out()

# ───────────────────────── V14 local ─────────────────────────
c = C(100, 17)
c.box(30, 0, 40, ["python -m tools.dev"])
c.put(50, 2, '┬'); c.hl(14, 86, 3); c.put(14, 3, '┌'); c.put(50, 3, '┼'); c.put(86, 3, '┐')
for x in (14, 50, 86):
    c.put(x, 4, '▼')
c.box(0, 5, 28, ["db.sync (startup)"])
c.box(36, 5, 28, ["uvicorn :8000  (API)"])
c.box(72, 5, 28, ["next dev :3000  (UI)"])
c.put(64, 6, '◄───────'); c.put(65, 8, '/api/*')
down(c, 14, 7, 10)
c.box(0, 10, 28, ["TIGER DATA"])
c.put(44, 7, '┬'); c.vl(44, 8, 10); c.put(44, 11, '┘'); c.hl(29, 43, 11); c.put(28, 11, '◄'); c.put(31, 10, "SQL")
c.put(56, 7, '┬'); c.vl(56, 8, 12); c.put(56, 13, '▼')
c.box(36, 14, 64, ["GEMINI (live chat)  ·  DATABRICKS JOBS API (5-min poll)"])
V['V14'] = c.out()

# ───────────────────────── V15 single VM ─────────────────────────
c = C(90, 34)
c.box(30, 0, 26, ["User browser"])
c.put(43, 2, '┬'); c.vl(43, 3, 3); c.put(45, 3, "https://<your-domain>"); c.put(43, 4, '▼')
c.box(30, 5, 26, ["GoDaddy DNS", "A record -> VM IP"])
c.put(43, 8, '┬'); c.put(43, 9, '▼')
c.box(4, 10, 78, [], h=17, style='double')
c.put(22, 10, " Vultr VM  (Ubuntu 24.04 + Docker Compose) ")
c.box(30, 12, 26, ["caddy :80 / :443", "auto-HTTPS proxy"])
c.put(43, 15, '┬'); c.hl(22, 64, 16); c.put(22, 16, '┌'); c.put(43, 16, '┴'); c.put(64, 16, '┐')
c.vl(22, 17, 17); c.vl(64, 17, 17); c.put(24, 17, "/*"); c.put(66, 17, "/api/*")
c.put(22, 18, '▼'); c.put(64, 18, '▼')
c.box(9, 19, 26, ["web :3000", "Next.js standalone"])
c.box(51, 19, 26, ["api :8000", "FastAPI x2 workers"])
c.put(64, 22, '┬'); c.vl(64, 23, 25); c.put(64, 26, '╤'); c.vl(64, 27, 27)
c.hl(48, 80, 28); c.put(48, 28, '┌'); c.put(64, 28, '┴'); c.put(80, 28, '┐')
c.put(48, 29, '▼'); c.put(50, 29, "SQL"); c.put(80, 29, '▼'); c.put(82, 29, "chat")
c.box(36, 30, 24, ["Tiger Data", "hypertables + cagg"])
c.box(70, 30, 20, ["Gemini API", "chat answers"])
c.box(0, 30, 26, ["Databricks Job", "-> db.sync"])
c.put(26, 32, '─────────►')
V['V15'] = c.out()

# ───────────────────────── V16 Vercel ─────────────────────────
c = C(100, 23)
c.box(30, 0, 40, ["User browser"])
down(c, 50, 2, 5, "https://<project>.vercel.app")
c.box(20, 5, 60, ["VERCEL PROJECT: dashboard", "Next.js · rewrites /api/* -> API project"], style='double')
down(c, 50, 8, 11, "same-origin proxy (no CORS)")
c.box(20, 11, 60, ["VERCEL PROJECT: api", "api/index.py -> path shim -> FastAPI"], style='double')
c.put(50, 14, '┬'); c.hl(25, 75, 15); c.put(25, 15, '┌'); c.put(50, 15, '┴'); c.put(75, 15, '┐')
c.vl(25, 16, 16); c.vl(75, 16, 16); c.put(25, 17, '▼'); c.put(75, 17, '▼')
c.box(10, 18, 30, ["Tiger Data"])
c.box(60, 18, 30, ["Gemini (chat)"])
c.put(0, 22, "Status: deployed + verified, then taken down on request. Redeploy ≈ 2 min.")
V['V16'] = c.out()

# ───────────────────────── V17 security ─────────────────────────
c = C(100, 21)
c.box(0, 0, 32, [".env  ·  laptop only", "git-ignored", "never in images / JS"], style='double')
c.box(40, 0, 28, ["pre-commit scanner", "+ gitleaks Action", "blocks secret commits"])
c.box(74, 0, 26, ["GitHub repo", "(no secrets)"])
right(c, 31, 40, 2)
right(c, 67, 74, 2)
down(c, 16, 4, 8, "runtime only (env_file / host env)")
c.box(0, 8, 32, ["API process", "TIGER_DATABASE_URL", "GEMINI_API_KEY · DBX token"])
right(c, 31, 40, 10)
c.box(40, 8, 28, ["Tiger · Gemini", "Databricks", "(server-side only)"])
c.box(74, 8, 26, ["VM: only 80/443 open", "containers non-root"])
c.box(0, 16, 32, ["BROWSER", "sees only JSON +", "NEXT_PUBLIC_API_BASE_URL"])
c.put(16, 16, '┴'); c.vl(16, 14, 15); c.put(16, 13, '▲'); c.put(18, 14, "/api/* JSON")
right(c, 31, 40, 18)
c.box(40, 16, 32, ["/api/chat guard", "≤ 500 chars · 10/min per IP", "global Gemini cap -> rules"])
V['V17'] = c.out()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--preview":
        for k, v in V.items():
            print(f"\n===== {k} =====\n{v}")
        sys.exit(0)
    tpl = open(sys.argv[1], encoding='utf-8').read()
    for k in sorted(V, key=lambda s: -len(s)):          # V17 before V1
        tpl = tpl.replace('{{' + k + '}}', '```text\n' + V[k] + '\n```')
    assert '{{V' not in tpl, "unfilled placeholder"
    open(sys.argv[2], 'w', encoding='utf-8', newline='\n').write(tpl)
    print("ok")
