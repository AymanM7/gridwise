# 🚀 infra/: Deployment (Vultr + GoDaddy)

One small Vultr VM runs the API and dashboard behind Caddy (automatic HTTPS). Tiger Data and Databricks stay in the cloud, so the VM only serves.

```text
 browser ──► GoDaddy DNS (A record) ──► Vultr VM
                                         └─ Caddy :80/:443 ──┬─ /api/*  → api  (FastAPI, backend/Dockerfile)
                                                             └─ /*      → web  (Next.js standalone, frontend/Dockerfile)
                                                api ──► Tiger Data · Gemini · Databricks Jobs API / SQL warehouse
```

| File | Purpose |
|---|---|
| `docker-compose.yml` | `api` + `web` + `caddy` |
| `Caddyfile` | Routes `/api/*` → api, the rest → web. `SITE_ADDRESS=:80` (IP, HTTP) or your domain (HTTPS) |
| `server-setup.sh` | One-time VM setup: Docker, firewall (22/80/443), 2 GB swap |
| [`../tools/deploy_vultr.py`](../tools/deploy_vultr.py) | Deploy from your laptop in one command |

## Step 1: Create the VM (you, ~5 min)

1. Sign in at **vultr.com** (ask the Vultr booth for hackathon credits).
2. **Deploy → Cloud Compute (Shared CPU)**
   - **Location:** Dallas (closest to Texas)
   - **Image:** Ubuntu 24.04 LTS x64
   - **Plan:** 1 vCPU / 2 GB RAM (1 GB also works; the setup script adds swap)
   - **SSH Keys → Add New:** paste the contents of `C:\Users\<you>\.ssh\id_ed25519.pub`
   - **Hostname:** `gridwise`
3. Click **Deploy** and copy the **IPv4 address** when it shows *Running*.

## Step 2: Deploy (one command, ~6–8 min the first time)

From the repo root on your laptop:

```powershell
.venv\Scripts\python -m tools.deploy_vultr --host <VM_IP>
```

It sets up the server, uploads the code (never `.venv`, `node_modules` or `data/`), uploads `.env` with `chmod 600`, builds the containers and waits for `/api/health`. Then open `http://<VM_IP>`.

## Step 3: Domain + HTTPS (GoDaddy, ~10 min)

1. GoDaddy → **My Products → your domain → DNS**.
2. Edit the **A** record for `@` → value = `<VM_IP>`, TTL 600. Add an **A** record for `www` → same IP (or a CNAME `www` → `@`).
3. Wait until `nslookup yourdomain.tech` returns the VM IP (usually minutes).
4. Redeploy with the domain; Caddy fetches the Let's Encrypt certificate automatically:

```powershell
.venv\Scripts\python -m tools.deploy_vultr --host <VM_IP> --domain yourdomain.tech --skip-setup
```

## Redeploying after code changes

```powershell
.venv\Scripts\python -m tools.deploy_vultr --host <VM_IP> [--domain yourdomain.tech] --skip-setup
```

## Useful server commands

```bash
ssh root@<VM_IP>
cd /opt/gridwise
docker compose -f infra/docker-compose.yml ps                 # status
docker compose -f infra/docker-compose.yml logs -f --tail 100  # logs
docker compose -f infra/docker-compose.yml restart api         # restart one service
```

## Notes

- **Secrets:** `.env` is copied only to `/opt/gridwise/.env` on the VM (mode 600) and is never in git or in an image layer (`env_file` at runtime; `.dockerignore` excludes it).
- **Freshness:** the API's background loop polls the Databricks Jobs API every 5 min and re-syncs Tiger after each pipeline run, so the live site updates on its own once the pipeline runs.
- **Fallback:** if Vultr setup stalls, deploy `frontend/` to Vercel with `NEXT_PUBLIC_USE_FIXTURES=1` for a public demo link (no live API, doesn't count for the Vultr track).
