#!/usr/bin/env bash
# Starts local dev servers with hot reload. Also starts the backend if
# scripts/setup.sh was run with the backend role.
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f frontend/.env ]] || { echo "Run scripts/setup.sh frontend|backend first." >&2; exit 1; }

if grep -q '^BACKEND_URL=http://localhost' frontend/.env; then
  (cd backend && exec .venv/bin/uvicorn app.main:app --reload --port 8000) &
  BACKEND_PID=$!
  trap 'kill $BACKEND_PID 2>/dev/null' EXIT
  echo "Backend:  http://localhost:8000/docs"
fi

echo "Frontend: http://localhost:5173"
cd frontend && npm run dev
