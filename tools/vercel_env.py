"""Copy the API's runtime secrets from .env into the linked Vercel project (gridwise-api).

    python -m tools.vercel_env

Sets TIGER_DATABASE_URL and GEMINI_API_KEY (production + preview) plus AUTO_SYNC_MINUTES=0.
Values are piped to `vercel env add` on stdin and never printed. The Databricks token is NOT sent:
serverless functions can't run the background sync, so Vercel doesn't need it.
Run from the repo root after `vercel link --project gridwise-api`.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    vals = dotenv_values(ROOT / ".env")
    want = {
        "TIGER_DATABASE_URL": vals.get("TIGER_DATABASE_URL"),
        "GEMINI_API_KEY": vals.get("GEMINI_API_KEY"),
        "AUTO_SYNC_MINUTES": "0",
    }
    npx = shutil.which("npx") or "npx"
    for key, val in want.items():
        if not val:
            print(f"  {key}: missing in .env, skipped")
            continue
        for env in ("production", "preview"):
            subprocess.run([npx, "--yes", "vercel", "env", "rm", key, env, "--yes"], cwd=ROOT, capture_output=True)
            r = subprocess.run([npx, "--yes", "vercel", "env", "add", key, env], cwd=ROOT,
                               input=val.encode(), capture_output=True)
            ok = r.returncode == 0
            err = "" if ok else " " + r.stderr.decode(errors="ignore")[-200:].replace(val, "***")
            print(f"  {"OK " if ok else "FAIL"} {key} [{env}]{err}")


if __name__ == "__main__":
    main()
