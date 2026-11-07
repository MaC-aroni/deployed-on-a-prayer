---
name: setup-dev
description: Set up this repo on a teammate's machine — prerequisites, frontend and backend dependencies, and .env — and explain the team workflow. Use when someone has just cloned the repo, asks to be set up, or local dev or the live backend isn't working.
---

# Set up local development

Two services: a FastAPI backend (`backend/`, port 8000) and a React + Vite frontend
(`frontend/`, dev port 5173). Prod is one Fly.io app at https://deployed-on-a-prayer.fly.dev
that serves both.

Everyone installs everything. Which backend to use is chosen each time they start:

- `scripts/dev.sh`: frontend locally, `/api` requests go to the live backend on Fly.
  Good when only changing the frontend, or when you need the real prod keys.
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

## 2. Install

macOS/Linux, from the repo root:

```bash
scripts/setup.sh
```

On Windows (no bash), do the same by hand:
1. `cd frontend && npm ci`
2. `cd backend && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`
3. Copy `backend/.env.example` to `backend/.env`.
4. To start: set `BACKEND_URL` to `https://deployed-on-a-prayer.fly.dev` (live) or
   `http://localhost:8000` (after starting `.venv\Scripts\uvicorn app.main:app --reload`
   in `backend/`), then `npm run dev` in `frontend/`.

## 3. Verify

- Live backend: `curl https://deployed-on-a-prayer.fly.dev/api/health` returns `{"status":"ok"}`.
- Start `scripts/dev.sh` and open http://localhost:5173. The page should say
  "Hello from the backend" with `env: production` (live) or `env: local` (`--local`).

Tell the user what you checked and how to start: `scripts/dev.sh` or `scripts/dev.sh --local`.

## 4. Explain the team workflow

Tell the user these rules once setup works:

- Work on a branch: `git checkout -b <name>/<feature>`. Pushes to `main` are blocked.
- Every push runs CI (backend lint and import, frontend build, secret scan) on GitHub.
- Open a PR with `gh pr create`. Only the repo owner can approve and merge it.
- Deploying to Fly is a manual step only the owner runs, after merging. A merged PR
  isn't live until the owner deploys.
- API keys: never put them in code or commit a `.env` file. Send the key to the owner
  privately and add the name, with no value, to `backend/.env.example`. For
  `--local`, put your own value in `backend/.env`.

## Troubleshooting

- **Live backend unreachable:** check https://deployed-on-a-prayer.fly.dev/api/health in a
  browser. If it's down, tell the owner (`fly status`, `fly logs`). Meanwhile use `--local`.
- **Frontend shows "Backend unreachable":** the chosen backend isn't running. Use
  `--local`, or see above.
- **Port 8000 already in use with `--local`:** another backend is running on this machine.
  Stop it, or find it with `lsof -i :8000`.
