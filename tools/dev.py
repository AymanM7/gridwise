"""Start the whole GridWise stack with one command.

    python -m tools.dev              # sync Tiger, start API :8000 + dashboard :3000, open browser
    python -m tools.dev --no-sync    # skip the Databricks -> Tiger sync
    python -m tools.dev --fixtures   # dashboard only, demo data (no API / DB needed)

Ctrl+C stops everything.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
API_PORT, WEB_PORT = 8000, 3000


def _up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status < 500
    except Exception:
        return False


def _wait(name: str, url: str, procs: list, timeout: int = 180) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _up(url):
            print(f"  ✓ {name:<9} {url}")
            return
        if any(p.poll() is not None for p in procs):
            raise SystemExit(f"  ✗ {name}: a process exited early, see output above")
        time.sleep(1)
    raise SystemExit(f"  ✗ {name} not ready after {timeout}s: {url}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-sync", action="store_true", help="skip db.sync")
    ap.add_argument("--fixtures", action="store_true", help="dashboard only, bundled demo data")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    npm = shutil.which("npm") or "npm"
    for port, label in ((API_PORT, "API"), (WEB_PORT, "dashboard")):
        if _up(f"http://localhost:{port}"):
            print(f"! port {port} ({label}) is already in use; stop that process first")
            if not args.fixtures or port == WEB_PORT:
                sys.exit(1)

    if not (FRONTEND / "node_modules").exists():
        print("→ npm install (first run)")
        subprocess.run([npm, "install"], cwd=FRONTEND, check=True, shell=os.name == "nt")

    procs: list[subprocess.Popen] = []
    try:
        if not args.fixtures:
            if not args.no_sync:
                print("→ database: syncing Databricks Gold → Tiger Data")
                subprocess.run([sys.executable, "-m", "db.sync"], cwd=ROOT, env=env, check=True)
            print(f"→ backend:  FastAPI on :{API_PORT}")
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", str(API_PORT)],
                cwd=ROOT, env=env))
        print(f"→ frontend: Next.js on :{WEB_PORT}")
        procs.append(subprocess.Popen(
            [npm, "run", "dev:fixtures" if args.fixtures else "dev"],
            cwd=FRONTEND, env=env, shell=os.name == "nt"))

        print("\nwaiting for services…")
        if not args.fixtures:
            _wait("API", f"http://localhost:{API_PORT}/api/health", procs)
            print(f"    API docs  http://localhost:{API_PORT}/api/docs")
        _wait("dashboard", f"http://localhost:{WEB_PORT}", procs)
        print("\nGridWise is running. Ctrl+C to stop.\n")
        if not args.no_browser:
            webbrowser.open(f"http://localhost:{WEB_PORT}")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("a service exited; shutting down")
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        for p in procs:
            if p.poll() is None:
                if os.name == "nt":  # kill the whole tree (npm → node)
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                                   capture_output=True)
                else:
                    p.terminate()


if __name__ == "__main__":
    main()
