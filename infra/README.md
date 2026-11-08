# 🚀 infra/: Deployment

> **Status:** planned for **Phase 5.8**. Not built yet.

**Planned contents**

| File | Purpose |
|---|---|
| `docker-compose.yml` | Runs `api` (FastAPI :8000) and `web` (Next.js :3000) on one Vultr VM |
| `Caddyfile` | Reverse proxy + automatic HTTPS for `gridwise.tech` (`/` → web, `/api` → api) |
| `vultr.md` | VM setup steps |

**Domain:** a GoDaddy A record points `gridwise.tech` at the Vultr VM's IP.
**Fallback:** frontend on Vercel if Vultr setup runs long.

Automation lives in [`.github/workflows/`](../.github/workflows): `secret-scan` (every push) and `gridwise-hourly` (pipeline trigger; schedule is off until Phase 4.6).
