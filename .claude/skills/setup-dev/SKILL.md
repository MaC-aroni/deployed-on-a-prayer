---
name: setup-dev
description: Set up this repo on a teammate's machine — prerequisites, frontend and backend dependencies, .env, and the Tailscale connection to the host laptop's servers. Use when someone has just cloned the repo, asks to be set up, or local dev or the host backend isn't working.
---

# Set up local development

Two services: a FastAPI backend (`backend/`, port 8000) and a React + Vite frontend
(`frontend/`, dev port 5173). Both also run all the time on the team's host laptop,
reachable over Tailscale at `prayer-host.tail051cbb.ts.net` (backend `:8000`, frontend `:3000`).

Everyone installs everything. Which backend to use is chosen each time they start:

- `scripts/dev.sh`: frontend locally, `/api` requests go to the host laptop's backend.
  Good when only changing the frontend, or when you need the real prod data and keys.
- `scripts/dev.sh --local`: backend and frontend both locally. Needed when changing the
  backend; changes reload on save.

## 1. Check prerequisites

Check each one, and install whatever is missing after the user agrees. On macOS use
Homebrew; elsewhere, point them to the download page.

| Tool | Check | Install (macOS) |
|---|---|---|
| git, gh | `gh auth status` | `brew install git gh`, then `gh auth login` |
| Node.js 20.19+ or 22.12+ | `node -v` | `brew install node` |
| Python 3.10+ | `python3 --version` | `brew install python` |
| Tailscale | `tailscale status` | https://tailscale.com/download |

**Tailscale** connects their laptop to the host laptop over any wifi. They need an invite
from the repo owner: either a tailnet invite or a shared-machine link. If `prayer-host`
doesn't appear in `tailscale status`, ask for that link, have them open it and sign in
(any Google/GitHub/Microsoft account works), and check again. Without it they can still
work with `scripts/dev.sh --local`, so don't block the rest of setup on it.

## 2. Install

macOS/Linux, from the repo root:

```bash
scripts/setup.sh
```

On Windows (no bash), do the same by hand:
1. `cd frontend && npm ci`
2. `cd backend && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`
3. Copy `backend/.env.example` to `backend/.env`.
4. To start: set `BACKEND_URL` to `http://prayer-host.tail051cbb.ts.net:8000` (host) or
   `http://localhost:8000` (after starting `.venv\Scripts\uvicorn app.main:app --reload`
   in `backend/`), then `npm run dev` in `frontend/`.

## 3. Verify

- Host connection: `curl http://prayer-host.tail051cbb.ts.net:8000/api/health` returns
  `{"status":"ok"}`.
- Start `scripts/dev.sh` and open http://localhost:5173. The page should say
  "Hello from the backend" with `env: production` (host) or `env: local` (`--local`).

Tell the user what you checked and how to start: `scripts/dev.sh` or `scripts/dev.sh --local`.

## 4. Explain the team workflow

Tell the user these rules once setup works:

- Work on a branch: `git checkout -b <name>/<feature>`. Pushes to `main` are blocked.
- Every push runs CI (backend lint and import, frontend build, secret scan) on GitHub.
- Open a PR with `gh pr create`. Only the repo owner can approve and merge it.
- Deploying to the host laptop is a manual step only the owner runs, after merging.
  A merged PR isn't live until the owner deploys.
- API keys: never put them in code or commit a `.env` file. Send the key to the owner
  privately and add the name, with no value, to `backend/.env.example`. For
  `--local`, put your own value in `backend/.env`.

## Troubleshooting

- **Can't reach the host:** run `tailscale status`. If `prayer-host` is missing, they
  haven't accepted the invite. If it's listed but offline, the host laptop is asleep or
  off; tell the owner. As a fallback, try its IP: `curl http://100.103.190.35:8000/api/health`.
- **Host reachable but `/api/health` fails:** the servers on the host are down. The owner
  checks with `pm2 status` and redeploys.
- **Frontend shows "Backend unreachable":** the chosen backend isn't running. Use
  `--local`, or fix the host connection above.
- **Port 8000 already in use with `--local`:** another backend is running. On the host
  laptop itself, prod uses 8000 and 3000, so use plain `scripts/dev.sh` there.
