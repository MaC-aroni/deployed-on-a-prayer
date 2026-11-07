# deployed-on-a-prayer: notes for coding agents

Hackathon project: FastAPI backend in `backend/`, React + Vite frontend in `frontend/`.
Prod is one Fly.io app at https://deployed-on-a-prayer.fly.dev: FastAPI serves `/api` and the
built frontend (see `Dockerfile`, `fly.toml`). Locally, `mise run dev` runs the frontend
against the live backend, and `mise run dev-local` runs both on this machine.

**First-time setup or a broken local environment:** follow `.claude/skills/setup-dev/SKILL.md`.

## Rules

- Never commit to `main`. Use a branch and open a PR (`gh pr create`); only the owner merges.
- Never put API keys in code, and never commit `.env` files. New keys: add the name to
  `backend/.env.example` and tell the user to send the value to the owner.
- Run tools through mise (`mise run ...`, `mise exec -- <cmd>`) so the versions pinned in
  `mise.toml` are used. Teammates are on macOS and Windows; prod and CI are Linux.
- Python dependencies: edit `backend/requirements.in`, then `mise run lock`. Never hand-edit
  `backend/requirements.txt`. Use `pathlib` for paths, and keep import paths' case exact.
- The frontend calls the backend only through relative `/api/...` URLs. Vite forwards them
  to `BACKEND_URL`, which `scripts/dev.py` sets. Don't hardcode backend hosts or ports.
- All backend routes go under `/api`. Every other path serves the frontend, so new pages are
  added in `frontend/src/App.jsx`.
- CI must pass before a PR can merge: `ruff check --select E9,F63,F7,F82 .` and an import
  of `app.main` in `backend/`, `npm run build` in `frontend/`, and a gitleaks secret scan.
