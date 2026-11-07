"""Block commits that contain secrets.

Checks every staged file (or every tracked file with --all) against:
  1. the custom rules in .gitleaks.toml, and
  2. the literal values of every key in your local .env (so even a key format we
     didn't write a regex for can't slip through).

Installed as .git/hooks/pre-commit by:  python scripts/check_secrets.py --install
Run manually:                          python scripts/check_secrets.py --all
"""
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".parquet", ".ico", ".pdf", ".zip"}


def git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def load_rules():
    cfg = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    rules = [(r["id"], re.compile(r["regex"])) for r in cfg.get("rules", [])]
    allow = cfg.get("allowlist", {})
    allow_paths = [re.compile(p) for p in allow.get("paths", [])]
    allow_regexes = [re.compile(p) for p in allow.get("regexes", [])]
    return rules, allow_paths, allow_regexes


def env_values() -> dict[str, str]:
    env = ROOT / ".env"
    vals = {}
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                # only real secrets: long values, not URLs of public endpoints / names / ids
                if len(v) >= 16 and not v.startswith("https://") and k.strip() not in {
                    "DATABRICKS_HOST", "DATABRICKS_WAREHOUSE_ID", "DATABRICKS_JOB_ID",
                    "GRIDWISE_CATALOG", "GEMINI_MODEL", "OPEN_METEO_BASE_URL",
                    "OPEN_METEO_ARCHIVE_URL", "CORS_ORIGINS", "API_BASE_URL",
                    "NEXT_PUBLIC_API_BASE_URL", "SOLANA_RPC_URL"}:
                    vals[k.strip()] = v
    return vals


def scan(files: list[str]) -> list[str]:
    rules, allow_paths, allow_regexes = load_rules()
    secrets = env_values()
    problems = []
    for rel in files:
        p = ROOT / rel
        if rel == ".env" or p.suffix.lower() in SKIP_SUFFIXES or not p.is_file():
            continue
        if any(a.search(rel.replace("\\", "/")) for a in allow_paths):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for name, value in secrets.items():
                if value in line:
                    problems.append(f"{rel}:{n}  contains the value of {name} from .env")
            for rid, rx in rules:
                m = rx.search(line)
                if m and not any(a.search(m.group(0)) for a in allow_regexes):
                    problems.append(f"{rel}:{n}  matches rule '{rid}'")
    return problems


def install():
    hook = ROOT / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        "# GridWise: block commits containing secrets (see scripts/check_secrets.py)\n"
        'PY="$(git rev-parse --show-toplevel)/.venv/Scripts/python.exe"\n'
        '[ -x "$PY" ] || PY="$(git rev-parse --show-toplevel)/.venv/bin/python"\n'
        '[ -x "$PY" ] || PY=python\n'
        'exec "$PY" "$(git rev-parse --show-toplevel)/scripts/check_secrets.py"\n',
        encoding="utf-8", newline="\n")
    print(f"installed {hook}")


def main():
    if "--install" in sys.argv:
        return install()
    files = git("ls-files") if "--all" in sys.argv else git("diff", "--cached", "--name-only", "--diff-filter=ACM")
    if ".env" in files:
        print("BLOCKED: .env is staged. Run: git rm --cached .env")
        sys.exit(1)
    problems = scan(files)
    if problems:
        print("BLOCKED: possible secrets found (values not shown):")
        for p in problems:
            print("  " + p)
        print("Move the value into .env (git-ignored) and read it with os.getenv().")
        sys.exit(1)
    print(f"secret scan ok ({len(files)} files)")


if __name__ == "__main__":
    main()
