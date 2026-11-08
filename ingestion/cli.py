"""GridWise ingestion CLI.

    python -m ingestion.cli backfill --start 2023-01-01      # one-time history (Phase 1.5)
    python -m ingestion.cli ingest                           # hourly refresh (Phase 1.6)
    add --local-only to skip the Databricks upload (writes data/landing/ only)
"""
import argparse
import sys
import time
import traceback
from datetime import date, timedelta

import pandas as pd

from .config import get_settings
from .landing import land, run_job
from .sources import eia, ercot, weather


def _with_retry(fn, attempts=3, wait=10):
    for i in range(attempts):
        try:
            return fn()
        except Exception as ex:
            if i == attempts - 1:
                raise
            print(f"    retry {i + 1}/{attempts - 1} after {type(ex).__name__}")
            time.sleep(wait * (i + 1))


def _run_steps(steps, s, upload):
    failed = []
    for source, name, fn in steps:
        try:
            df = _with_retry(fn)
            if df is None or df.empty:
                print(f"  - {source:<18} {name:<28} no rows")
                continue
            where = land(df, s, source, name, upload=upload)
            print(f"  ✓ {source:<18} {name:<28} {len(df):>8,} rows -> {where}")
        except Exception as ex:  # keep going; report at the end
            failed.append(f"{source}/{name}")
            print(f"  ✗ {source:<18} {name:<28} {type(ex).__name__}: {ex}")
            traceback.print_exc(limit=1)
    return failed


def backfill(args, s):
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today()
    archive_end = min(end, date.today() - timedelta(days=6))  # Open-Meteo archive lags ~5 days
    steps = []
    for yr in range(start.year, end.year + 1):
        ys, ye = max(start, date(yr, 1, 1)), min(end, date(yr, 12, 31))
        if "eia" in args.sources:
            steps.append(("eia_hourly", f"eia_{yr}", lambda ys=ys, ye=ye: eia.fetch(ys, ye, s.eia_api_key)))
        if "prices" in args.sources:
            steps.append(("ercot_prices", f"spp_archive_{yr}", lambda yr=yr: ercot.prices_year(yr)))
        if "weather" in args.sources and ys <= archive_end:
            steps.append(("weather_hist", f"weather_{yr}",
                          lambda ys=ys, ye=min(ye, archive_end): weather.history(ys, ye)))
    print(f"Backfill {start} -> {end}  (upload={'yes' if not args.local_only else 'no'})")
    return _run_steps(steps, s, upload=not args.local_only)


def ingest(args, s):
    now = pd.Timestamp.now(tz="US/Central")
    run_id = now.tz_convert("UTC").strftime("%Y%m%dT%H%M")
    today = now.normalize()
    yday = today - pd.Timedelta(days=1)
    tomorrow = today + pd.Timedelta(days=1)
    steps = [
        ("eia_hourly",       f"eia_{run_id}",     lambda: eia.fetch((now - pd.Timedelta(days=4)).date(), now.date(), s.eia_api_key)),
        ("ercot_load",       f"load_{run_id}",    lambda: ercot.load(yday, tomorrow)),
        ("ercot_prices",     f"spp_{run_id}",     lambda: ercot.prices(yday, tomorrow)),
        ("ercot_wind",       f"wind_{run_id}",    ercot.wind_latest),
        ("ercot_solar",      f"solar_{run_id}",   ercot.solar_latest),
        ("weather_forecast", f"wxfc_{run_id}",    lambda: weather.forecast(past_days=10, forecast_days=3)),
    ]
    print(f"Ingest run {run_id}  (upload={'yes' if not args.local_only else 'no'})")
    failed = _run_steps(steps, s, upload=not args.local_only)
    if args.trigger_job and not args.local_only:
        if s.job_id:
            run_job(s)
        else:
            print("  (DATABRICKS_JOB_ID not set; skipping job trigger)")
    return failed


def main(argv=None):
    p = argparse.ArgumentParser(prog="ingestion")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--start", default="2023-01-01")
    b.add_argument("--end")
    b.add_argument("--sources", nargs="+", default=["eia", "prices", "weather"],
                   choices=["eia", "prices", "weather"])
    b.add_argument("--local-only", action="store_true")
    i = sub.add_parser("ingest")
    i.add_argument("--local-only", action="store_true")
    i.add_argument("--trigger-job", action="store_true", help="run the Databricks Job after landing data")
    args = p.parse_args(argv)

    s = get_settings()
    if not args.local_only and not s.has_databricks:
        sys.exit("DATABRICKS_HOST / DATABRICKS_TOKEN missing in .env (or pass --local-only)")
    failed = (backfill if args.cmd == "backfill" else ingest)(args, s)
    if failed:
        print(f"\n{len(failed)} step(s) failed: {', '.join(failed)}")
        sys.exit(1)
    print("\nDone.")


if __name__ == "__main__":
    main()
