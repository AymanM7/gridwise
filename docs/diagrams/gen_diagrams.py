import sys, io

class C:
    def __init__(s, w, h):
        s.w, s.h = w, h
        s.g = [[' '] * w for _ in range(h)]

    def put(s, x, y, t):
        for i, ch in enumerate(t):
            assert 0 <= x + i < s.w and 0 <= y < s.h, (x, y, t)
            s.g[y][x + i] = ch

    def hl(s, x1, x2, y, ch='─'):
        for x in range(min(x1, x2), max(x1, x2) + 1):
            s.g[y][x] = ch

    def vl(s, x, y1, y2, ch='│'):
        for y in range(min(y1, y2), max(y1, y2) + 1):
            s.g[y][x] = ch

    def box(s, x, y, w, lines, h=None, align='c', style='single', header=0):
        sep = 1 if header else 0
        h = h or len(lines) + 2 + sep
        tl, tr, bl, br, hz, vt = {
            'single': '┌┐└┘─│', 'double': '╔╗╚╝═║', 'dashed': '┌┐└┘╌╎'}[style]
        s.put(x, y, tl + hz * (w - 2) + tr)
        s.put(x, y + h - 1, bl + hz * (w - 2) + br)
        for yy in range(y + 1, y + h - 1):
            s.put(x, yy, vt + ' ' * (w - 2) + vt)
        row = y + 1
        for i, l in enumerate(lines):
            if header and i == header:
                s.put(x, row, '├' + '─' * (w - 2) + '┤')
                row += 1
            assert len(l) <= w - 4, (l, w)
            if align == 'c' or (header and i < header):
                t = l.center(w - 2)
            else:
                t = ' ' + l.ljust(w - 3)
            s.put(x + 1, row, t)
            row += 1
        return h

    def out(s):
        return '\n'.join(''.join(r).rstrip() for r in s.g).rstrip('\n')


D = {}

# ---------------- D1 system design ----------------
c = C(101, 86)
c.box(6, 0, 34, ["ERCOT", "via gridstatus (Python)", "load · RT price · wind · solar"])
c.box(56, 0, 34, ["OPEN-METEO", "Houston · DFW · Austin · SA", "historical + forecast weather"])
c.put(23, 4, '┬'); c.put(73, 4, '┬')
c.vl(23, 5, 6); c.vl(73, 5, 6)
c.hl(23, 73, 7); c.put(23, 7, '└'); c.put(73, 7, '┘'); c.put(48, 7, '┬')
c.vl(48, 8, 8); c.put(48, 9, '▼')
c.box(0, 10, 101, [], h=46, style='double')
c.put(1, 11, "DATABRICKS LAKEHOUSE   ·   Unity Catalog: grid   ·   Delta Lake   ·   MLflow".center(99))
c.put(4, 13, "[1] MEDALLION PIPELINE  (Delta Lake)")
xs = [4, 28, 52, 76]
c.box(4, 14, 21, ["AUTO LOADER", "Volume -> Delta", "incremental", "availableNow"])
c.box(28, 14, 21, ["BRONZE", "raw Delta tables", "stored as-is", "+ _ingested_at"])
c.box(52, 14, 21, ["SILVER", "hourly UTC grid", "DST duplicate fix", "grid+weather join"])
c.box(76, 14, 21, ["GOLD", "net load = D-W-S", "strain idx 0-100", "features · spikes"])
for x in (25, 49, 73):
    c.put(x, 16, '──►')
c.put(86, 19, '┬'); c.vl(86, 20, 22); c.put(86, 23, '▼')
c.put(4, 21, "[2] MACHINE LEARNING  (MLflow)")
c.hl(38, 86, 21); c.put(38, 21, '┌'); c.put(86, 21, '┤')
c.vl(38, 22, 22); c.put(38, 23, '▼')
c.box(4, 24, 21, ["MLflow + UC", "Model Registry", "experiments", "@champion alias"])
c.box(28, 24, 21, ["MODEL A", "LightGBM net load", "24-48 h ahead", "P10 · P50 · P90"])
c.box(52, 24, 21, ["SHAP  [NEW]", "top-3 drivers", "per forecast hour", "-> 'Why Red?'"])
c.box(76, 24, 21, ["MODEL B", "spike classifier", "P(price > $100)", "per hour"])
c.put(25, 26, '◄──'); c.put(49, 26, '──►')
# A -> B (forecast as feature)
c.put(44, 29, '┬'); c.vl(44, 30, 30); c.put(44, 31, '└'); c.hl(45, 91, 31)
c.put(92, 31, '┘'); c.put(92, 30, '▲')
c.put(64, 32, "forecast -> Model B")
# A -> Gemini
c.put(36, 29, '┬'); c.vl(36, 30, 34); c.put(36, 35, '▼')
# SHAP -> Gemini
c.put(62, 29, '┬'); c.vl(62, 30, 32); c.put(62, 31, '┼'); c.put(62, 33, '┘')
c.hl(42, 61, 33); c.put(41, 33, '┌'); c.vl(41, 34, 34); c.put(41, 35, '▼')
# B -> Ripple
c.put(84, 29, '┬'); c.vl(84, 30, 34); c.put(84, 31, '┼'); c.put(84, 35, '▼')
c.put(4, 34, "[3] AI & ANALYTICS")
c.box(4, 36, 21, ["GENIE SPACE", "natural-language", "Q&A over Gold", "(demo live)"])
c.box(28, 36, 21, ["GEMINI", "ai_query() or", "worker publish", "advice + Why Red?"])
c.box(52, 36, 21, ["REPORT CARD [NEW]", "forecast vs real", "MAPE · recall", "band coverage"])
c.box(76, 36, 21, ["RIPPLE  [NEW]", "what-if shifting", "re-scores Model B", "scenario grid"])
for x in (38, 62, 86):
    c.put(x, 41, '┬'); c.vl(x, 42, 42); c.put(x, 43, '▼')
c.box(4, 44, 93, ["GOLD SERVING TABLES",
                  "forecasts · forecast_drivers · daily_advice · shift_scenarios · report_card"])
c.put(14, 44, '┴'); c.put(14, 43, '│'); c.put(14, 42, '▲')
c.box(4, 49, 93, ["DATABRICKS WORKFLOWS  ·  HOURLY JOB",
                  "bronze -> silver -> gold -> predict -> explain -> ripple -> report card",
                  "triggered hourly by the worker  ·  Unity Catalog governance  ·  train runs weekly"],
      style='dashed')
c.put(50, 55, '╤'); c.vl(50, 56, 57); c.put(52, 57, "hourly sync (worker publish)"); c.put(50, 58, '▼')
c.box(30, 59, 41, ["TIGER DATA  (TimescaleDB)", "hypertables + continuous aggregates", "hourly + daily rollups"])
c.put(50, 63, '┬'); c.vl(50, 64, 64); c.put(50, 65, '▼')
c.box(30, 66, 41, ["FASTAPI on VULTR", "Docker + Caddy (HTTPS)",
                   "/forecast  /advice  /history", "/simulate  /chat  /report-card"])
c.box(79, 66, 22, ["GEMINI API", "chat answers", "grounded in", "forecast JSON"])
c.put(71, 68, '◄──────►')
c.box(0, 66, 24, ["ANALYSTS / JUDGES", "ask Genie in", "plain English", ""])
c.put(12, 55, '╧'); c.put(12, 56, '▲'); c.vl(12, 57, 65); c.put(12, 66, '┴')
c.put(14, 60, "Genie Q&A")
c.put(50, 71, '┬'); c.vl(50, 72, 72); c.put(52, 72, "JSON / HTTPS"); c.put(50, 73, '▼')
c.box(22, 74, 57, ["NEXT.JS DASHBOARD   ·   gridwise.tech",
                   "strain timeline + P10-P90 band  ·  spike risk",
                   "best hours  ·  Gemini advice  ·  chat box",
                   "Ripple simulator  ·  Why Red?  ·  report card"])
c.box(83, 74, 18, ["GODADDY", "DNS: A record", "-> Vultr IP"])
c.put(79, 76, '◄───')
c.put(50, 80, '▲'); c.vl(50, 81, 81)
c.box(30, 82, 41, ["TEXANS · EV OWNERS · TOU PLANS", "shift usage off-peak, save money"])
c.put(50, 82, '┴')
body = c.out().split('\n')[10:]
t = C(101, 14)
t.box(0, 0, 30, ["ERCOT (gridstatus)", "live load · RT price", "wind/solar + forecasts"])
t.box(33, 0, 30, ["EIA-930 API", "hourly history 2023+", "demand · wind · solar"])
t.box(66, 0, 30, ["OPEN-METEO", "HOU · DFW · AUS · SAT", "archive + forecast"])
t.put(15, 4, '┬'); t.put(48, 4, '┬'); t.put(81, 4, '┬')
t.hl(15, 81, 5); t.put(15, 5, '└'); t.put(48, 5, '┼'); t.put(81, 5, '┘'); t.put(48, 6, '▼')
t.box(17, 7, 63, ["GRIDWISE WORKER   ·   GitHub Actions, every hour",
                  "fetch -> parquet -> upload INTO a Unity Catalog Volume",
                  "(Free Edition blocks outbound calls from notebooks)"])
t.put(48, 11, '┬'); t.vl(48, 12, 12); t.put(50, 12, "files.upload -> /Volumes/grid/bronze/landing")
t.put(48, 13, '▼')
D['D1'] = t.out() + '\n' + '\n'.join(body)

# ---------------- D2 job DAG ----------------
c = C(85, 40)
c.box(26, 0, 29, ["worker: ingest + upload", "GitHub Actions (hourly)"], style='dashed')
c.put(40, 3, '┬'); c.put(40, 4, '▼')
c.box(29, 5, 23, ["bronze", "Auto Loader"]); c.put(40, 8, '┬'); c.put(40, 9, '▼')
c.box(29, 10, 23, ["build_silver"]); c.put(40, 12, '┬'); c.put(40, 13, '▼')
c.box(29, 14, 23, ["build_gold"]); c.put(40, 16, '┬'); c.put(40, 17, '▼')
c.box(29, 18, 23, ["predict", "Model A + Model B"])
c.box(60, 18, 24, ["train", "manual / weekly"], style='dashed')
c.put(52, 19, '◄╌╌╌╌╌╌╌'); c.put(53, 17, "registers @champion")
c.put(40, 21, '┬')
c.hl(15, 65, 22); c.put(15, 22, '┌'); c.put(40, 22, '┼'); c.put(65, 22, '┐')
for x in (15, 40, 65):
    c.put(x, 23, '▼')
c.box(3, 24, 24, ["explain", "SHAP drivers"])
c.box(28, 24, 24, ["ripple_scenarios", "Ripple  [NEW]"])
c.box(53, 24, 24, ["report_card", "daily ~6am CT  [NEW]"])
c.put(15, 27, '┬'); c.put(15, 28, '▼')
c.box(3, 29, 24, ["gemini_advice", "ai_query if allowed"])
c.put(15, 32, '┬'); c.vl(15, 33, 33)
c.put(40, 27, '┬'); c.vl(40, 28, 33)
c.put(65, 27, '┬'); c.vl(65, 28, 33)
c.hl(15, 65, 34); c.put(15, 34, '└'); c.put(40, 34, '┼'); c.put(65, 34, '┘'); c.put(40, 35, '▼')
c.box(24, 36, 33, ["worker: publish", "Gemini advice + Tiger sync"], style='dashed')
D['D2'] = c.out()

# ---------------- D3 medallion ----------------
c = C(96, 13)
c.box(0, 0, 24, ["BRONZE", "raw, stored as-is", "eia_hourly", "ercot_load", "ercot_prices",
                 "ercot_wind", "ercot_solar", "weather_hist", "weather_forecast", ""], align='l', header=2)
c.box(36, 0, 24, ["SILVER", "cleaned + joined", "grid_hourly", "1 row per UTC hour",
                  "load · wind · solar", "RT price", "4-city weather", "", "", ""], align='l', header=2)
c.box(72, 0, 24, ["GOLD", "business-ready", "features", "strain_hourly", "spike_events",
                  "forecasts", "forecast_drivers", "daily_advice", "shift_scenarios", "report_card"],
      align='l', header=2)
for i, t in enumerate(["CPT -> UTC", "DST fix", "dedupe", "join"]):
    c.put(25, 4 + i, t)
c.put(24, 9, '──────────►')
for i, t in enumerate(["net load", "lags/rolls", "heat index", "strain"]):
    c.put(61, 4 + i, t)
c.put(60, 9, '──────────►')
D['D3'] = c.out()

# ---------------- D4 DST ----------------
c = C(83, 26)
c.box(0, 0, 34, ["ERCOT row: local CPT hour", "+ DSTFlag column"], align='l')
c.put(17, 3, '┬'); c.put(17, 4, '▼')
c.box(0, 5, 34, ["Fall-back day?", "(01:00 appears twice)"], align='l')
c.put(34, 6, '── yes ────►')
c.box(46, 5, 34, ["DSTFlag True  -> 1st 01:00 CDT", "DSTFlag False -> 2nd 01:00 CST"], align='l')
c.put(17, 8, '┬'); c.put(17, 9, '│'); c.put(19, 9, 'no'); c.put(17, 10, '▼')
c.box(0, 11, 34, ["Spring-forward day?", "(02:00 is missing)"], align='l')
c.put(34, 12, '── yes ────►')
c.box(46, 11, 34, ["23-hour day:", "don't impute 02:00"], align='l')
c.put(17, 14, '┬'); c.put(17, 15, '│'); c.put(19, 15, 'no'); c.put(17, 16, '▼')
c.box(0, 17, 34, ["tz_localize('America/Chicago')", "-> tz_convert('UTC')"], align='l')
c.put(80, 6, '──┐'); c.put(80, 12, '──┤')
c.vl(82, 7, 11); c.vl(82, 13, 18); c.put(82, 19, '┘'); c.hl(35, 81, 19); c.put(34, 19, '◄')
c.put(17, 20, '┬'); c.put(17, 21, '▼')
c.box(0, 22, 34, ["dedupe on ts_utc", "-> silver.grid_hourly"], align='l')
D['D4'] = c.out()

# ---------------- D5 gold relationships ----------------
c = C(93, 14)
c.box(33, 0, 22, ["gold.features"])
c.put(44, 2, '┬'); c.vl(44, 3, 3); c.put(46, 3, "Models A + B"); c.put(44, 4, '▼')
c.box(33, 5, 22, ["gold.forecasts"])
c.box(71, 5, 22, ["gold.strain_hourly"])
c.put(44, 7, '┬'); c.put(82, 7, '┬')
c.hl(10, 82, 8); c.put(10, 8, '┌'); c.put(34, 8, '┬'); c.put(44, 8, '┴'); c.put(58, 8, '┬'); c.put(82, 8, '┤')
for x in (10, 34, 58, 82):
    c.put(x, 9, '▼')
c.box(0, 10, 20, ["forecast_drivers", "(SHAP)"])
c.box(24, 10, 20, ["daily_advice", "(Gemini)"])
c.box(48, 10, 20, ["shift_scenarios", "(Ripple)"])
c.box(72, 10, 20, ["report_card", "(eval vs actual)"])
D['D5'] = c.out()

# ---------------- D6 ML lifecycle ----------------
c = C(80, 37)
c.box(22, 0, 34, ["gold.features"]); c.put(39, 2, '┬'); c.put(39, 3, '▼')
c.box(22, 4, 34, ["time-based split", "train / val / test"])
c.put(39, 7, '┬'); c.hl(19, 59, 8); c.put(19, 8, '┌'); c.put(39, 8, '┴'); c.put(59, 8, '┐')
c.put(19, 9, '▼'); c.put(59, 9, '▼')
c.box(4, 10, 30, ["Train Model A", "P50 + P10 + P90 quantiles"])
c.box(44, 10, 30, ["Train Model B", "spike classifier"])
c.put(19, 13, '┬'); c.put(59, 13, '┬')
c.hl(19, 59, 14); c.put(19, 14, '└'); c.put(39, 14, '┬'); c.put(59, 14, '┘'); c.put(39, 15, '▼')
c.box(22, 16, 34, ["MLflow runs", "params · metrics · artifacts"])
c.put(39, 19, '┬'); c.put(39, 20, '▼')
c.box(22, 21, 34, ["beats current champion", "on validation set?"])
c.put(39, 24, '┬'); c.hl(19, 59, 25); c.put(19, 25, '┌'); c.put(39, 25, '┴'); c.put(59, 25, '┐')
c.put(19, 26, '▼'); c.put(21, 26, 'yes'); c.put(59, 26, '▼'); c.put(61, 26, 'no')
c.box(4, 27, 30, ["register in Unity Catalog", "alias @champion"])
c.box(44, 27, 30, ["keep existing", "champion"])
c.put(19, 30, '┬'); c.put(59, 30, '┬')
c.hl(19, 59, 31); c.put(19, 31, '└'); c.put(39, 31, '┬'); c.put(59, 31, '┘'); c.put(39, 32, '▼')
c.box(22, 33, 34, ["hourly batch inference", "-> gold.forecasts"])
D['D6'] = c.out()

# ---------------- D7 Ripple ----------------
c = C(80, 35)
c.box(0, 0, 32, ["USER SLIDERS", "participation %", "kWh per home", "from / to windows"])
c.box(46, 0, 32, ["FORECAST P50 CURVE", "gold.forecasts", "(net load, MW)"], h=6)
c.put(16, 5, '┬'); c.put(16, 6, '▼')
c.box(0, 7, 32, ["shifted MW =", "pct x meters x kWh / hrs"])
c.put(16, 10, '┬'); c.put(62, 5, '┬'); c.vl(62, 6, 10)
c.hl(16, 62, 11); c.put(16, 11, '└'); c.put(39, 11, '┬'); c.put(62, 11, '┘'); c.put(39, 12, '▼')
c.box(22, 13, 34, ["subtract from peak window", "add back to off-peak window"])
c.put(39, 16, '┬'); c.hl(16, 62, 17); c.put(16, 17, '┌'); c.put(39, 17, '┴'); c.put(62, 17, '┐')
c.put(16, 18, '▼'); c.put(62, 18, '▼')
c.box(0, 19, 32, ["re-score with Model B"])
c.box(46, 19, 32, ["recompute strain index"])
c.put(16, 21, '┬'); c.put(62, 21, '┬')
c.hl(16, 62, 22); c.put(16, 22, '└'); c.put(39, 22, '┬'); c.put(62, 22, '┘'); c.put(39, 23, '▼')
c.box(10, 24, 58, ["RESULT  (before vs. after)", "Δ peak MW   ·   Δ spike probability",
                   "Δ red hours   ·   ≈ gas peaker plants avoided"])
c.put(39, 29, '▲'); c.put(41, 29, "instant lookup"); c.put(39, 30, '╎')
c.box(22, 31, 34, ["gold.shift_scenarios", "precomputed scenario grid"], style='dashed')
c.put(39, 31, '┴')
D['D7'] = c.out()

# ---------------- D8 Why Red ----------------
c = C(96, 26)
c.box(0, 0, 28, ["Model A (champion)"], h=4)
c.put(14, 3, '┬'); c.put(14, 4, '│'); c.put(14, 5, '▼')
c.box(0, 6, 28, ["SHAP TreeExplainer", "per forecast hour"])
c.put(14, 9, '┬'); c.put(14, 10, '▼')
c.box(0, 11, 28, ["top-3 drivers", "feature · value · ±MW"])
c.put(14, 14, '┬'); c.put(14, 15, '▼')
c.box(0, 16, 28, ["Gemini via ai_query", "1-sentence 'Why Red?'"])
c.box(34, 0, 28, ["quantile models", "P10 / P90"])
c.put(48, 3, '┬'); c.vl(48, 4, 9); c.put(48, 10, '▼')
c.box(34, 11, 28, ["confidence band", "+ low-confidence flag"])
c.box(68, 0, 28, ["yesterday's forecast", "+ yesterday's actuals"])
c.put(82, 3, '┬'); c.vl(82, 4, 9); c.put(82, 10, '▼')
c.box(68, 11, 28, ["REPORT CARD", "MAPE · spike hits · band"])
c.put(14, 19, '┬')
c.put(48, 14, '┬'); c.vl(48, 15, 19)
c.put(82, 14, '┬'); c.vl(82, 15, 19)
c.hl(14, 82, 20); c.put(14, 20, '└'); c.put(48, 20, '┼'); c.put(82, 20, '┘')
c.put(48, 21, '▼')
c.box(20, 22, 56, ["DASHBOARD", "hover tooltip on red hours + report card"])
D['D8'] = c.out()


def seq(parts, w, msgs, start=4, gap=3, H=None):
    n = len(parts)
    centers = [p[1] for p in parts]
    H = H or start + gap * len(msgs) + 1
    W = max(centers) + w // 2 + 2
    c = C(W, H)
    for name, cx in parts:
        c.box(cx - w // 2, 0, w, [name])
    for cx in centers:
        c.vl(cx, 3, H - 1)
        c.put(cx, 2, '┬')
    y = start
    for m in msgs:
        if m[0] == 'self':
            cx = centers[m[1]]
            c.put(cx, y, '├──┐'); c.put(cx + 3, y + 1, '│ ' + m[2]); c.put(cx, y + 2, '│◄─┘')
            y += gap + 1
            continue
        a, b, label = centers[m[0]], centers[m[1]], m[2]
        dashed = len(m) > 3 and m[3]
        ch = '╌' if dashed else '─'
        lo, hi = min(a, b), max(a, b)
        assert len(label) <= hi - lo - 3, label
        c.put(lo + 2, y, label)
        c.hl(lo + 1, hi - 1, y + 1, ch)
        if b > a:
            c.put(hi - 1, y + 1, '►')
        else:
            c.put(lo + 1, y + 1, '◄')
        y += gap
    return c.out()

D['D9'] = seq([("User", 8), ("Next.js", 26), ("FastAPI", 44), ("Tiger Data", 62), ("Gemini API", 80)], 14, [
    (0, 1, '"EV question"'),
    (1, 2, 'POST /chat'),
    (2, 3, 'next 48h fcst'),
    (3, 2, 'rows', True),
    (2, 4, 'prompt + JSON'),
    (4, 2, '"plug in 1-5am"', True),
    (2, 1, 'answer + hours', True),
    (1, 0, 'highlight', True),
])

D['D10'] = seq([("Databricks Job", 9), ("Tiger Data", 31), ("FastAPI", 53), ("Browser", 75)], 18, [
    (0, 1, 'hourly upsert'),
    ('self', 1, 'refresh caggs'),
    (3, 2, 'GET /forecast'),
    (2, 1, 'SQL query'),
    (1, 2, 'rows (ms)', True),
    (2, 3, 'JSON -> charts', True),
], H=24)

# ---------------- D11 deployment ----------------
c = C(90, 34)
c.box(30, 0, 26, ["User browser"])
c.put(43, 2, '┬'); c.vl(43, 3, 3); c.put(45, 3, "https://gridwise.tech"); c.put(43, 4, '▼')
c.box(30, 5, 26, ["GoDaddy DNS", "A record -> Vultr IP"])
c.put(43, 8, '┬'); c.put(43, 9, '▼')
c.box(4, 10, 78, [], h=17, style='double')
c.put(25, 10, " Vultr VM  (Ubuntu + Docker Compose) ")
c.box(30, 12, 26, ["caddy :80 / :443", "auto-HTTPS proxy"])
c.put(43, 15, '┬'); c.hl(22, 64, 16); c.put(22, 16, '┌'); c.put(43, 16, '┴'); c.put(64, 16, '┐')
c.vl(22, 17, 17); c.vl(64, 17, 17); c.put(24, 17, "/"); c.put(66, 17, "/api")
c.put(22, 18, '▼'); c.put(64, 18, '▼')
c.box(9, 19, 26, ["web :3000", "Next.js"])
c.box(51, 19, 26, ["api :8000", "FastAPI"])
c.put(64, 22, '┬'); c.vl(64, 23, 25); c.put(64, 26, '╤'); c.vl(64, 27, 27)
c.hl(48, 80, 28); c.put(48, 28, '┌'); c.put(64, 28, '┴'); c.put(80, 28, '┐')
c.put(48, 29, '▼'); c.put(50, 29, "SQL"); c.put(80, 29, '▼'); c.put(82, 29, "chat")
c.box(36, 30, 24, ["Tiger Data", "hypertables + caggs"])
c.box(70, 30, 20, ["Gemini API", "chat answers"])
c.box(0, 30, 26, ["Databricks Job", "hourly sync"])
c.put(26, 32, '─────────►')
D['D11'] = c.out()

# ---------------- D12 gantt ----------------
phases = [("1  Setup & Ingestion", 0, 2), ("2  Silver & Gold", 2, 4), ("3  Machine Learning", 4, 6.5),
          ("4  AI Layer & Automation", 6.5, 8), ("5  Serving & Dashboard", 6, 10), ("6  Ship", 10, 11.5)]
L, S, N = 28, 5, 12
lines = []
hdr = [' '] * (L + N * S + 4)
for h in range(N + 1):
    for i, ch in enumerate(str(h)):
        hdr[L + h * S + i] = ch
lines.append(''.join(hdr).rstrip() + '   (hours from kickoff)')
lines.append(' ' * L + '├' + ('─' * (S - 1) + '┼') * (N - 1) + '─' * (S - 1) + '┤')
for name, a, b in phases:
    bar = ' ' * int(a * S) + '█' * int(round((b - a) * S))
    lines.append(name.ljust(L) + bar + f'  {b - a:g} h')
D['D12'] = '\n'.join(lines)

# ---------------- D13 phase flow ----------------
c = C(88, 12)
ph = [["PHASE 1", "Setup +", "Ingestion", "2 h"], ["PHASE 2", "Silver +", "Gold", "2 h"],
      ["PHASE 3", "Machine", "Learning", "2.5 h"], ["PHASE 4", "AI layer +", "Automation", "1.5 h"],
      ["PHASE 6", "Ship", "Devpost", "1.5 h"]]
for i, p in enumerate(ph):
    c.box(i * 18, 0, 14, p)
    if i < 4:
        c.put(i * 18 + 14, 2, '───►')
c.put(43, 5, '┬'); c.vl(43, 6, 7); c.put(43, 8, '└'); c.put(44, 8, '─'); c.put(45, 8, '►')
c.box(46, 7, 28, ["PHASE 5", "Serving + Dashboard", "4 h, starts during P3"])
c.hl(74, 78, 8); c.put(79, 8, '┘'); c.vl(79, 7, 7); c.put(79, 6, '▲')
D['D13'] = c.out()

tpl = open(sys.argv[1], encoding='utf-8').read()
for k, v in D.items():
    tpl = tpl.replace('{{' + k + '}}', '```text\n' + v + '\n```')
assert '{{D' not in tpl
open(sys.argv[2], 'w', encoding='utf-8', newline='\n').write(tpl)
print("ok")
