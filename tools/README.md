# 🧰 tools/: Developer Helpers

| Tool | Command | What it does |
|---|---|---|
| `login.py` | `python -m tools.login https://<workspace>.cloud.databricks.com` | Browser login to Databricks, creates a 90-day token, saves it to `.env` |
| `deploy.py` | `python -m tools.deploy --run 02_silver 03_gold` | Uploads `pipeline/` + `ml/` notebooks to the workspace, runs them on serverless, prints results |
| `sql.py` | `python -m tools.sql "SELECT ..."` | Runs SQL on your Databricks SQL warehouse and prints a table |
| `check_secrets.py` | `python tools/check_secrets.py --install` | Installs the pre-commit hook that blocks commits containing keys (rules in `.gitleaks.toml` + your real `.env` values) |

Run all commands from the repo root with the virtual environment active.
