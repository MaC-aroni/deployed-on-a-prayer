#!/usr/bin/env bash
# Runs on the host laptop when the owner clicks Deploy (.github/workflows/deploy.yml).
# Copies the code to a prod folder, installs, and (re)starts both servers with pm2.
set -euo pipefail

PROD="$HOME/deployed-on-a-prayer-prod"
echo "Deploying commit $(git rev-parse --short HEAD) by ${GITHUB_ACTOR:-local} to $PROD"

# A separate folder, so the runner's checkout cleanup never touches the running servers.
# Excluded paths survive --delete, so installs and .env stay put between deploys.
mkdir -p "$PROD"
rsync -a --delete --exclude .git --exclude node_modules --exclude .venv --exclude .env --exclude dist ./ "$PROD/"

# GitHub secrets and variables -> backend/.env (secrets win on name clashes).
(
  umask 077
  /usr/bin/jq -rn \
    --argjson v "${VARS_JSON:-"{}"}" \
    --argjson s "${SECRETS_JSON:-"{}"}" \
    '{APP_ENV: "production"} + $v + $s | del(.github_token) | to_entries[] | "\(.key)=\(.value | @json)"' \
    > "$PROD/backend/.env"
)
echo "Wrote $(wc -l < "$PROD/backend/.env" | tr -d ' ') keys to backend/.env"
# Keep the raw secrets out of the environment pm2 hands to the servers.
unset SECRETS_JSON VARS_JSON

cd "$PROD/backend"
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

cd "$PROD/frontend"
npm ci --no-audit --no-fund
npm run build

cd "$PROD"
pm2 startOrRestart ecosystem.config.cjs --update-env
pm2 save

# Fail the deploy if either server doesn't come up.
for url in http://localhost:8000/api/health http://localhost:3000/api/health; do
  if curl -fsS --retry 15 --retry-delay 1 --retry-connrefused -o /dev/null "$url"; then
    echo "OK: $url"
  else
    echo "Not responding: $url"
    pm2 logs --lines 30 --nostream
    exit 1
  fi
done
