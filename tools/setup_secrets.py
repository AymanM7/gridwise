"""Create the Databricks secret scope 'gridwise' and store the keys the notebooks need, read from .env.

Run this YOURSELF (a human), once, from the repo root with the venv active:

    python -m tools.setup_secrets            # create scope + put the 3 secrets
    python -m tools.setup_secrets --check    # only list which keys exist in the scope (never prints values)

| secret key        | .env variable        | used by                         |
|-------------------|----------------------|---------------------------------|
| gemini_api_key    | GEMINI_API_KEY       | ml/09_advice (Gemini daily plan) |
| tiger_db_url      | TIGER_DATABASE_URL   | Gold -> Tiger sync (Phase 5.2)  |
| eia_api_key       | EIA_API_KEY          | in-Databricks ingestion, if used |

Notebooks read them with dbutils.secrets.get('gridwise', '<key>') inside try/except, so everything still runs
(with rule-based fallbacks) before this script has been run. Values are never printed or logged; Databricks
redacts secret values in notebook output.
"""
import argparse
import os
import sys

from databricks.sdk import WorkspaceClient

from ingestion.config import get_settings   # also loads .env into os.environ

SCOPE = "gridwise"
SECRETS = {
    "gemini_api_key": "GEMINI_API_KEY",
    "tiger_db_url": "TIGER_DATABASE_URL",
    "eia_api_key": "EIA_API_KEY",
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true", help="only list existing keys in the scope")
    args = p.parse_args()

    s = get_settings()
    if not s.has_databricks:
        sys.exit("DATABRICKS_HOST / DATABRICKS_TOKEN missing in .env (run python -m tools.login first).")
    w = WorkspaceClient(host=s.databricks_host, token=s.databricks_token)

    scopes = {sc.name for sc in w.secrets.list_scopes()}
    if args.check:
        if SCOPE not in scopes:
            sys.exit(f"scope '{SCOPE}' does not exist yet")
        have = {k.key for k in w.secrets.list_secrets(SCOPE)}
        for key in SECRETS:
            print(f"  {key:16s} {'present' if key in have else 'MISSING'}")
        return

    if SCOPE in scopes:
        print(f"scope '{SCOPE}' already exists")
    else:
        w.secrets.create_scope(scope=SCOPE)
        print(f"created scope '{SCOPE}'")

    for key, env in SECRETS.items():
        value = (os.getenv(env) or "").strip()
        if not value:
            print(f"  skip {key}: {env} is not set in .env")
            continue
        w.secrets.put_secret(scope=SCOPE, key=key, string_value=value)
        print(f"  stored {key} (from {env}, {len(value)} chars)")
    print("done. Verify with: python -m tools.setup_secrets --check")


if __name__ == "__main__":
    main()
