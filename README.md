# deployed-on-a-prayer

![CI](https://github.com/ob1-can-obi/deployed-on-a-prayer/actions/workflows/ci.yml/badge.svg)

FastAPI backend (`backend/`) and React + Vite frontend (`frontend/`). Both run on the host
laptop, which teammates reach over Tailscale at `prayer-host`:

| | Backend | Frontend |
|---|---|---|
| Host laptop (prod) | http://prayer-host:8000 | http://prayer-host:3000 |
| Your machine (dev) | http://localhost:8000 | http://localhost:5173 |

## Getting started

1. Install [Tailscale](https://tailscale.com/download) and open the invite link from the owner.
2. `gh repo clone ob1-can-obi/deployed-on-a-prayer && cd deployed-on-a-prayer`
3. Ask your coding agent to **"set me up for frontend"** (or backend). It follows
   `.claude/skills/setup-dev/SKILL.md`. Without an agent, run `scripts/setup.sh frontend` (or `backend`).
4. `scripts/dev.sh`, then open http://localhost:5173

Frontend work uses the host's backend, so you only run the frontend. Backend work runs both locally.

## Shipping

1. Branch, commit, push. CI (lint, build, secret scan) runs on every push.
2. Open a PR. The owner approves and merges it. Pushes to `main` are blocked.
3. The owner deploys: **Actions → Deploy → Run workflow**. Merging alone doesn't deploy.

## API keys

Never put keys in code or commit a `.env` file.

1. Send the key to the owner privately (DM or password manager, not the group chat).
2. The owner adds it: `gh secret set MY_API_KEY -R ob1-can-obi/deployed-on-a-prayer`
   (or Settings → Secrets and variables → Actions).
3. Add the name, with no value, to `backend/.env.example` and commit that.
4. The next deploy writes it into the host's `backend/.env`. Read it with `os.environ["MY_API_KEY"]`.

Non-sensitive settings go under the Variables tab instead and work the same way.
Locally, put your own values in `backend/.env` (gitignored).

## Host laptop (owner)

- Runner: `~/actions-runner`, a background service that picks up Deploy runs.
- Prod copy: `~/deployed-on-a-prayer-prod`, with both servers managed by pm2:
  `pm2 status`, `pm2 logs`, `pm2 restart all`.
- After a reboot, log in, then run Deploy again (or `pm2 resurrect`) to bring the servers back.
