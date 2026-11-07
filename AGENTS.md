# deployed-on-a-prayer: notes for coding agents

Hackathon project: FastAPI backend in `backend/`, React + Vite frontend in `frontend/`.
Prod runs on the team's host laptop (`prayer-host` on Tailscale; backend :8000, frontend :3000).

**First-time setup or a broken local environment:** follow `.claude/skills/setup-dev/SKILL.md`.

## Rules

- Never commit to `main`. Use a branch and open a PR (`gh pr create`); only the owner merges.
- Never put API keys in code, and never commit `.env` files. New keys: add the name to
  `backend/.env.example` and tell the user to send the value to the owner.
- The frontend calls the backend only through relative `/api/...` URLs. Vite forwards them
  to whatever `BACKEND_URL` is in `frontend/.env`. Don't hardcode backend hosts or ports.
- All backend routes go under `/api`.
- CI must pass before a PR can merge: `ruff check --select E9,F63,F7,F82 .` and an import
  of `app.main` in `backend/`, `npm run build` in `frontend/`, and a gitleaks secret scan.
