#!/usr/bin/env bash
# Runs on the host laptop on every push to main.
# Fill in the section for your stack once it's decided.
set -euo pipefail

echo "Deploying commit $(git rev-parse --short HEAD) by ${GITHUB_ACTOR:-local}"

# Write GitHub secrets and variables to .env (secrets win on name clashes),
# then export them so anything started below inherits them too.
if [[ -n "${SECRETS_JSON:-}" ]]; then
  umask 077
  /usr/bin/jq -rn \
    --argjson v "${VARS_JSON:-"{}"}" \
    --argjson s "$SECRETS_JSON" \
    '$v + $s | del(.github_token) | to_entries[] | "\(.key)=\(.value | @json)"' > .env
  echo "Wrote $(wc -l < .env | tr -d ' ') keys to .env"
  set -a; source .env; set +a
fi

# --- Docker Compose ---
# docker compose up -d --build --remove-orphans

# --- Node (pm2) ---
# npm ci
# npm run build --if-present
# pm2 startOrRestart ecosystem.config.js   # or: pm2 restart app || pm2 start server.js --name app

# --- Python (pm2) ---
# python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# pm2 restart app || pm2 start ".venv/bin/python app.py" --name app

echo "Deploy step is a placeholder. Edit deploy.sh to start your server."
