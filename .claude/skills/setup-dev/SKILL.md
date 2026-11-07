---
name: setup-dev
description: Set up this repo on a teammate's machine (macOS, Linux or Windows) — pinned Node/Python via mise, frontend and backend dependencies, and .env — and explain the team workflow. Use when someone has just cloned the repo, asks to be set up, or local dev or the live backend isn't working.
---

# Set up local development

Two services: a FastAPI backend (`backend/`, port 8000) and a React + Vite frontend
(`frontend/`, dev port 5173). Prod is one Fly.io app at https://deployed-on-a-prayer.fly.dev
that serves both.

`mise.toml` pins the exact Node, Python and uv versions and defines the commands, so every
OS runs the same thing. Always go through `mise run ...`, never plain `python`/`npm`, so
the pinned versions are used. Which backend to use is chosen each time they start:

- `mise run dev`: frontend locally, `/api` requests go to the live backend on Fly.
- `mise run dev-local`: backend and frontend both locally. Needed when changing the
  backend; changes reload on save.

## 1. Install the tools

Only two tools are installed system-wide. mise installs everything else, inside this project only.

- **macOS:** `brew bundle` (installs `gh` and `mise` from the `Brewfile`). No Homebrew?
  Install it from https://brew.sh first.
- **Windows:** `winget install GitHub.cli jdx.mise`, then open a new terminal.
- **Linux:** `gh` from https://cli.github.com, mise with `curl https://mise.run | sh`.

Then make sure `gh auth status` shows them logged in (otherwise `gh auth login`).

## 2. Install the pinned versions and dependencies

From the repo root:

```
mise trust      # mise asks before using a project's config; this approves this repo
mise install    # exact Node, Python, uv from mise.toml
mise run setup  # frontend + backend packages, creates backend/.env
```

`mise run setup` warns if the Node or Python it ran with doesn't match `mise.toml`. If
you see that, something bypassed mise; re-run through `mise run`.

## 3. Verify

- `mise run dev`, then open http://localhost:5173. The page should say "Hello from the
  backend" with `env: production`. `mise run dev-local` should show `env: local`.
- http://localhost:5173/excuses should show an excuse.

Tell the user what you checked and how to start: `mise run dev` or `mise run dev-local`.

## 4. Explain the team workflow

Tell the user these rules once setup works:

- Work on a branch: `git checkout -b <name>/<feature>`. Pushes to `main` are blocked.
- Every push runs CI (backend lint and import, frontend build, secret scan) on GitHub,
  on Linux with the same pinned versions.
- Open a PR with `gh pr create`. Only the repo owner can approve and merge it.
- Deploying to Fly is a manual step only the owner runs, after merging. A merged PR
  isn't live until the owner deploys.
- New backend package: add it to `backend/requirements.in`, run `mise run lock`, and
  commit both files. Never edit `backend/requirements.txt` by hand.
- API keys: never put them in code or commit a `.env` file. Send the key to the owner
  privately and add the name, with no value, to `backend/.env.example`. For
  `dev-local`, put your own value in `backend/.env`.

## Troubleshooting

- **`mise: command not found` (Windows):** open a new terminal after installing.
- **`mise run` says the config isn't trusted:** run `mise trust` in the repo root.
- **Live backend unreachable:** check https://deployed-on-a-prayer.fly.dev/api/health in a
  browser. If it's down, tell the owner (`fly status`, `fly logs`). Meanwhile use `dev-local`.
- **Frontend shows "Backend unreachable":** the chosen backend isn't running. Use
  `dev-local`, or see above.
- **Port 8000 or 5173 already in use:** another dev server is running. On macOS find it
  with `lsof -i :8000`; on Windows, `netstat -ano | findstr :8000`.
- **Works locally, fails in CI:** CI runs on Linux, which is case-sensitive. Check that
  import paths match file names exactly (`./Home.jsx`, not `./home.jsx`).
