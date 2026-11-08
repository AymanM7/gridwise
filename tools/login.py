"""One-time helper: browser login to Databricks, then create a personal access token
for the worker and save DATABRICKS_HOST / DATABRICKS_TOKEN into .env.

    python -m tools.login https://dbc-xxxxxxxx-xxxx.cloud.databricks.com
"""
import re
import sys

from databricks.sdk import WorkspaceClient

from ingestion.config import ROOT


def set_env(key: str, value: str) -> None:
    path = ROOT / ".env"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", line, text, flags=re.M)
    else:
        text += ("" if text.endswith("\n") or not text else "\n") + line + "\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    m = re.match(r"https://[^/]+", sys.argv[1].strip())
    if not m:
        sys.exit("Pass the workspace URL, e.g. https://dbc-xxxx.cloud.databricks.com")
    host = m.group(0)

    print(f"Opening a browser to sign in to {host} ... click 'Allow' if asked.")
    w = WorkspaceClient(host=host, auth_type="external-browser")
    me = w.current_user.me()
    print(f"Signed in as {me.user_name}")

    tok = w.tokens.create(comment="gridwise-worker", lifetime_seconds=90 * 24 * 3600)
    set_env("DATABRICKS_HOST", host)
    set_env("DATABRICKS_TOKEN", tok.token_value)
    print("Created a 90-day token 'gridwise-worker' and saved it to .env (token not printed).")

    check = WorkspaceClient(host=host, token=tok.token_value).current_user.me()
    print(f"Token works for {check.user_name}.")


if __name__ == "__main__":
    main()
