# deployed-on-a-prayer

![CI](https://github.com/ob1-can-obi/deployed-on-a-prayer/actions/workflows/ci.yml/badge.svg)

**Live:** https://deployed-on-a-prayer.fly.dev (try `/excuses` before your demo)

FastAPI backend (`backend/`) and React + Vite frontend (`frontend/`). In prod they ship as one
Fly.io app: FastAPI serves `/api` and the built frontend from the same URL.

| | Backend | Frontend |
|---|---|---|
| Live (Fly) | https://deployed-on-a-prayer.fly.dev/api | https://deployed-on-a-prayer.fly.dev |
| Your machine (dev) | http://localhost:8000 | http://localhost:5173 |

## Getting started

1. `gh repo clone ob1-can-obi/deployed-on-a-prayer && cd deployed-on-a-prayer`
2. Ask your coding agent to **"set me up"**. It follows `.claude/skills/setup-dev/SKILL.md`.
   Without an agent, run `scripts/setup.sh`.
3. Start working, then open http://localhost:5173:
   - `scripts/dev.sh` runs the frontend against the live backend.
   - `scripts/dev.sh --local` runs the backend on your machine too. Use it when changing the backend.

## Shipping

1. Branch, commit, push. CI (lint, build, secret scan) runs on every push.
2. Open a PR. The owner approves and merges it. Pushes to `main` are blocked.
3. The owner deploys: **Actions → Deploy → Run workflow**. Merging alone doesn't deploy.

## API keys

Never put keys in code or commit a `.env` file.

1. Send the key to the owner privately (DM or password manager, not the group chat).
2. The owner adds it as a Fly secret, either in the dashboard
   (https://fly.io/apps/deployed-on-a-prayer/secrets) or with `fly secrets import`.
   The app restarts with it within a few seconds; no deploy needed.
3. Add the name, with no value, to `backend/.env.example` and commit that.
4. Read it in code with `os.environ["MY_API_KEY"]`.

For `--local`, put your own values in `backend/.env` (gitignored).

## Owner notes

- Deploy needs the `FLY_API_TOKEN` repo secret (a deploy token scoped to this app, expires after 90 days).
- `fly status`, `fly logs` and `fly secrets list` show what's running.
- Remove a key with `fly secrets unset NAME`.
