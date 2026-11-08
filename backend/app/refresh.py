"""Background Tiger refresh: re-runs `python -m db.sync` after the Databricks Job finishes.

Without this, Tiger only changes when someone runs db.sync by hand, so the dashboard drifts into its
"pipeline may be delayed" banner. The loop is cheap on the Free Edition quota:

* every AUTO_SYNC_MINUTES (default 5) it asks the Jobs API for the newest finished run of
  DATABRICKS_JOB_ID: no compute. A run that ended after the last `sync_log` row triggers a sync.
* only while the Tiger forecast is stale (> STALE_MINUTES) does it also ask the SQL warehouse for
  max(gold.forecasts.run_ts), at most every GOLD_CHECK_MINUTES (default 30). That covers notebooks run
  outside the Job (tools.deploy --run).
* a Postgres advisory lock makes sure only one uvicorn worker / API instance syncs at a time.
* after a failed sync it backs off for GOLD_CHECK_MINUTES.

The sync itself runs in a subprocess (full `db.sync`, ~15 s), so a crash there never takes the API down.
Disable with AUTO_SYNC_MINUTES=0. Needs DATABRICKS_HOST / DATABRICKS_TOKEN (+ DATABRICKS_WAREHOUSE_ID,
DATABRICKS_JOB_ID) in the API's environment; without them the loop stays off.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import psycopg

from .config import (AUTO_SYNC_MINUTES, DATABASE_URL, GOLD_CHECK_MINUTES, ROOT, STALE_MINUTES,
                     databricks_configured)

log = logging.getLogger("gridwise.refresh")
LOCK_KEY = 4_826_150_001          # pg advisory lock id shared by every API worker
SYNC_TIMEOUT_S = 900

_stop = threading.Event()
_thread: threading.Thread | None = None
state: dict = {"enabled": False, "last_check": None, "last_sync": None, "last_result": None}


def _age_minutes(conn) -> float | None:
    ts = conn.execute("SELECT coalesce(max(created_at), max(run_ts)) FROM forecasts "
                      "WHERE run_ts = (SELECT max(run_ts) FROM forecasts)").fetchone()[0]
    return None if ts is None else (datetime.now(timezone.utc) - ts).total_seconds() / 60


def _run_sync(reason: str) -> bool:
    log.info("auto-sync starting: %s", reason)
    t0 = time.time()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        p = subprocess.run([sys.executable, "-m", "db.sync"], cwd=str(ROOT), env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=SYNC_TIMEOUT_S)
        ok = p.returncode == 0
        tail = " | ".join((p.stdout or "").strip().splitlines()[-2:])
        if not ok:
            tail += " | " + " | ".join((p.stderr or "").strip().splitlines()[-3:])
    except subprocess.TimeoutExpired:
        ok, tail = False, f"timed out after {SYNC_TIMEOUT_S}s"
    state["last_sync"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["last_result"] = ("ok" if ok else "failed") + f" in {time.time() - t0:.0f}s: {tail}"
    (log.info if ok else log.warning)("auto-sync %s", state["last_result"])
    return ok


def tick(last_gold_check: float) -> tuple[float, bool | None]:
    """One check. Returns (new last_gold_check, sync outcome or None if no sync ran)."""
    from db import sync as dbsync  # repo-root package; imported lazily so the API starts without it

    state["last_check"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=10) as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]:
            return last_gold_check, None          # another worker is checking / syncing
        try:
            if conn.execute("SELECT to_regclass('sync_log') IS NULL").fetchone()[0]:
                return last_gold_check, _run_sync("schema missing: first sync")
            age = _age_minutes(conn)
            stale = age is None or age > STALE_MINUTES
            check_gold = stale and (time.time() - last_gold_check) >= GOLD_CHECK_MINUTES * 60
            if check_gold:
                last_gold_check = time.time()
            needed, why = dbsync.sync_needed(conn, check_gold=check_gold)
            if not needed:
                log.debug("auto-sync: %s", why)
                return last_gold_check, None
            return last_gold_check, _run_sync(why)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))


def _loop() -> None:
    last_gold_check = 0.0
    wait = 5.0                                    # first check shortly after startup
    while not _stop.wait(wait):
        wait = AUTO_SYNC_MINUTES * 60
        try:
            last_gold_check, ok = tick(last_gold_check)
            if ok is False:
                wait = max(wait, GOLD_CHECK_MINUTES * 60)   # back off after a failed sync
        except Exception as e:                    # never let the loop die
            state["last_result"] = f"check error: {type(e).__name__}: {e}"[:300]
            log.warning("auto-sync check failed: %s: %s", type(e).__name__, e)
            wait = max(wait, GOLD_CHECK_MINUTES * 60)


def start() -> None:
    global _thread
    if AUTO_SYNC_MINUTES <= 0:
        log.info("auto-sync off (AUTO_SYNC_MINUTES=0)")
        return
    if not (DATABASE_URL and databricks_configured()):
        log.info("auto-sync off (needs TIGER_DATABASE_URL + DATABRICKS_HOST/TOKEN)")
        return
    _stop.clear()
    state["enabled"] = True
    _thread = threading.Thread(target=_loop, name="gridwise-auto-sync", daemon=True)
    _thread.start()
    log.info("auto-sync on: Jobs API every %g min, Gold check every %g min while stale",
             AUTO_SYNC_MINUTES, GOLD_CHECK_MINUTES)


def stop() -> None:
    _stop.set()
