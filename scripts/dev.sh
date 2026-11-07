#!/usr/bin/env bash
# Starts the frontend dev server with hot reload.
#   scripts/dev.sh          use the live backend on Fly (nothing else to run)
#   scripts/dev.sh --local  also run the backend on this machine, and use that
set -euo pipefail
cd "$(dirname "$0")/.."

PROD_BACKEND="https://deployed-on-a-prayer.fly.dev"
[[ -d frontend/node_modules && -d backend/.venv ]] || { echo "Run scripts/setup.sh first." >&2; exit 1; }

if [[ "${1:-}" == --local ]]; then
  (cd backend && exec .venv/bin/uvicorn app.main:app --reload --port 8000) &
  BACKEND_PID=$!
  trap 'kill $BACKEND_PID 2>/dev/null' EXIT
  export BACKEND_URL="http://localhost:8000"
  echo "Backend:  http://localhost:8000/docs (on this machine, reloads on save)"
else
  export BACKEND_URL="$PROD_BACKEND"
  echo "Backend:  $PROD_BACKEND (live on Fly)"
fi

echo "Frontend: http://localhost:5173"
cd frontend && npm run dev
