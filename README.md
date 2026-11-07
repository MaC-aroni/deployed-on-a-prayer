# deployed-on-a-prayer

![CI](https://github.com/MaC-aroni/deployed-on-a-prayer/actions/workflows/ci.yml/badge.svg)

**Live:** https://deployed-on-a-prayer.fly.dev (try `/excuses` before your demo)

FastAPI backend (`backend/`) and React + Vite frontend (`frontend/`). In prod they ship as one
Fly.io app: FastAPI serves `/api` and the built frontend from the same URL.

| | Backend | Frontend |
|---|---|---|
| Live (Fly) | https://deployed-on-a-prayer.fly.dev/api | https://deployed-on-a-prayer.fly.dev |
| Your machine (dev) | http://localhost:8000 | http://localhost:5173 |

## Getting started

Ask your coding agent to **"set me up"**. It follows `.claude/skills/setup-dev/SKILL.md`.
Or do it by hand. These are the same steps on macOS, Linux and Windows once the tools are in:

1. Install the tools: `brew bundle` (macOS) or `winget install GitHub.cli jdx.mise` (Windows).
2. `gh repo clone MaC-aroni/deployed-on-a-prayer && cd deployed-on-a-prayer`
3. `mise trust && mise install` installs the exact Node and Python versions in `mise.toml`.
4. `mise run setup` installs the packages.
5. Start working, then open http://localhost:5173:
   - `mise run dev` runs the frontend against the live backend.
   - `mise run dev-local` runs the backend on your machine too. Use it when changing the backend.

New backend package: add it to `backend/requirements.in`, run `mise run lock`, and commit both files.

## Shipping

1. Branch, commit, push. CI (lint, build, secret scan) runs on every push.
2. Open a PR. A maintainer (ob1-can-obi, Elathius or Zafeer-R) approves and merges it.
   Pushes to `main` are blocked for everyone else.
3. A maintainer deploys: **Actions → Deploy → Run workflow**. Merging alone doesn't deploy.

## API keys

Never put keys in code or commit a `.env` file.

1. Send the key to ob1-can-obi privately (DM or password manager, not the group chat).
2. They add it as a Fly secret, either in the dashboard
   (https://fly.io/apps/deployed-on-a-prayer/secrets) or with `fly secrets import`.
   The app restarts with it within a few seconds; no deploy needed.
3. Add the name, with no value, to `backend/.env.example` and commit that.
4. Read it in code with `os.environ["MY_API_KEY"]`.

For `dev-local`, put your own values in `backend/.env` (gitignored).

## Maintainer notes

- Deploy needs the `FLY_API_TOKEN` repo secret (a deploy token scoped to this app, expires after 90 days).
- `fly status`, `fly logs` and `fly secrets list` show what's running.
- Remove a key with `fly secrets unset NAME`.
