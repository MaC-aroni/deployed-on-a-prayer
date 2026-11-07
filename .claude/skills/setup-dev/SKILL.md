---
name: setup-dev
description: Set up this repo on a teammate's machine for frontend or backend work — prerequisites, dependencies, .env files, and the connection to the host laptop's servers. Use when someone has just cloned the repo, asks to be set up, or local dev or the host backend isn't working.
---

# Set up local development

Two services: a FastAPI backend (`backend/`, port 8000) and a React + Vite frontend
(`frontend/`, dev port 5173). Both also run 24/7 on the team's host laptop, reachable
over Tailscale at `prayer-host` (backend `:8000`, frontend `:3000`).

- **Frontend role:** run only the frontend locally. Its `/api` requests go to the host
  laptop's backend, so there's nothing else to run.
- **Backend role:** run both locally. The frontend's `/api` requests go to `localhost:8000`.

## 1. Ask which role

If the user hasn't said, ask: "Are you working on the frontend or the backend?"

## 2. Check prerequisites

Check each one, and install whatever is missing after the user agrees. On macOS use
Homebrew; elsewhere, point them to the download page.

| Tool | Needed for | Check | Install (macOS) |
|---|---|---|---|
| git, gh | everyone | `gh auth status` | `brew install git gh`, then `gh auth login` |
| Node.js 20.19+ or 22.12+ | everyone | `node -v` | `brew install node` |
| Python 3.10+ | backend role | `python3 --version` | `brew install python` |
| Tailscale | everyone (reaching the host) | `tailscale status` | https://tailscale.com/download |

**Tailscale:** the user needs an invite from the repo owner. If `prayer-host` doesn't
appear in `tailscale status`, ask them for the invite link, have them open it and sign in,
and check again. Don't continue past this for the frontend role; it can't work without it.

## 3. Install

macOS/Linux, from the repo root:

```bash
scripts/setup.sh frontend   # or: scripts/setup.sh backend
```

On Windows (no bash), do the same steps by hand:
1. `cd frontend && npm ci`
2. Backend role only: `cd backend && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`,
   then copy `backend/.env.example` to `backend/.env`.
3. Write `frontend/.env` with one line: `BACKEND_URL=http://prayer-host:8000` (frontend role)
   or `BACKEND_URL=http://localhost:8000` (backend role).

## 4. Verify

- Frontend role: `curl http://prayer-host:8000/api/health` returns `{"status":"ok"}`.
- Backend role: start `scripts/dev.sh`, then `curl http://localhost:8000/api/health`.
- Either: `scripts/dev.sh` and open http://localhost:5173. The page should say
  "Hello from the backend" (`env: production` means it's the host's backend).

Report what you checked to the user and how to start working: `scripts/dev.sh`.

## 5. Explain the team workflow

Tell the user these rules once setup works:

- Work on a branch: `git checkout -b <name>/<feature>`. Pushes to `main` are blocked.
- Every push runs CI (backend lint and import, frontend build, secret scan) on GitHub.
- Open a PR with `gh pr create`. Only the repo owner can approve and merge it.
- Deploying to the host laptop is a manual step only the owner can run, after merging.
  A merged PR isn't live until the owner deploys.
- API keys: never put them in code or commit a `.env` file. Send the key to the owner
  privately and add the name, with no value, to `backend/.env.example`. Locally, put
  your own value in `backend/.env`.

## Troubleshooting

- **Can't reach `prayer-host`:** check `tailscale status`. If the host is listed but
  offline, the host laptop is asleep or off; tell the owner.
- **Host reachable but `/api/health` fails:** the servers on the host are down. The owner
  checks with `pm2 status` and redeploys.
- **Frontend shows "Backend unreachable":** check `frontend/.env` has the right
  `BACKEND_URL`, then restart `scripts/dev.sh` (Vite reads it at startup).
- **Port 8000 already in use (backend role):** another backend is running. On the host
  laptop itself, prod uses 8000 and 3000, so use the frontend role there.
