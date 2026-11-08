"""Deploy GridWise (API + dashboard + Caddy) to a Vultr VM over SSH.

    python -m tools.deploy_vultr --host 203.0.113.10                     # HTTP on the IP
    python -m tools.deploy_vultr --host 203.0.113.10 --domain gridwise.tech   # HTTPS on a domain
    python -m tools.deploy_vultr --host 203.0.113.10 --skip-setup        # redeploy code only

Steps: (1) one-time server setup (Docker, firewall, swap) → (2) upload the repo (tracked +
untracked-but-not-ignored files only, so .venv / node_modules / data never leave this machine)
→ (3) upload .env (chmod 600) → (4) docker compose up --build → (5) wait for /api/health.

Needs: SSH key access as root (add your public key when creating the VM in Vultr).
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/opt/gridwise"
SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15"]


def ssh(target: str, cmd: str, stdin: bytes | None = None) -> None:
    r = subprocess.run(["ssh", *SSH_OPTS, target, cmd], input=stdin)
    if r.returncode != 0:
        sys.exit(f"✗ remote command failed ({r.returncode}): {cmd[:80]}")


def repo_tarball() -> bytes:
    files = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode().split("\0")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in filter(None, files):
            p = ROOT / f
            if p.is_file() and not f.startswith(".env"):
                tar.add(p, arcname=f)
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True, help="VM public IPv4")
    ap.add_argument("--domain", help="e.g. gridwise.tech (A record must point at --host); enables HTTPS")
    ap.add_argument("--www", action="store_true", help="also serve www.<domain> (needs a www DNS record)")
    ap.add_argument("--user", default="root")
    ap.add_argument("--skip-setup", action="store_true", help="skip Docker/firewall/swap setup")
    args = ap.parse_args()

    target = f"{args.user}@{args.host}"
    env_file = ROOT / ".env"
    if not env_file.exists():
        sys.exit("✗ .env not found at repo root")

    print(f"→ checking SSH access to {target}")
    ssh(target, "echo ok >/dev/null")

    if not args.skip_setup:
        print("→ server setup: Docker, firewall, swap (first run takes ~2 min)")
        ssh(target, "bash -s", (ROOT / "infra" / "server-setup.sh").read_bytes())

    print("→ uploading code")
    tb = repo_tarball()
    ssh(target, f"mkdir -p {REMOTE} && tar -xzf - -C {REMOTE}", tb)
    print(f"  {len(tb) / 1e6:.1f} MB")

    print("→ uploading .env (chmod 600)")
    ssh(target, f"umask 077 && cat > {REMOTE}/.env", env_file.read_bytes())

    if args.domain:
        site = f"{args.domain} www.{args.domain}" if args.www else args.domain
        origin = f"https://{args.domain}"
    else:
        site, origin = ":80", f"http://{args.host}"
    print(f"→ building and starting containers ({site}); first build takes ~5 min")
    ssh(
        target,
        f"cd {REMOTE} && SITE_ADDRESS='{site}' PUBLIC_ORIGIN='{origin}' "
        f"docker compose -f infra/docker-compose.yml up -d --build --remove-orphans && docker image prune -f >/dev/null",
    )

    url = f"{origin}/api/health"
    print(f"→ waiting for {url}")
    for _ in range(60):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    print(f"\n✓ GridWise is live: {origin}\n  API docs: {origin}/api/docs")
                    return
        except Exception:
            pass
        time.sleep(5)
    sys.exit(f"✗ not healthy yet. Check logs: ssh {target} 'cd {REMOTE} && docker compose -f infra/docker-compose.yml logs --tail 80'")


if __name__ == "__main__":
    main()
