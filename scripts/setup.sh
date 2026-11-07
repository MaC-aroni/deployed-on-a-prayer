#!/usr/bin/env bash
# First-time local setup (macOS/Linux). Installs both the frontend and backend. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

PROD_BACKEND="https://deployed-on-a-prayer.fly.dev"

fail() { echo "ERROR: $*" >&2; exit 1; }

command -v node >/dev/null || fail "Node.js is not installed (need 20.19+ or 22.12+)"
node -e '
  const [maj, min] = process.versions.node.split(".").map(Number);
  process.exit(maj > 22 || (maj === 22 && min >= 12) || (maj === 20 && min >= 19) ? 0 : 1);
' || fail "Node.js $(node -v) is too old (need 20.19+ or 22.12+)"
command -v python3 >/dev/null || fail "Python 3 is not installed (need 3.10+)"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || fail "$(python3 --version) is too old (need 3.10+)"

echo "Installing frontend dependencies..."
(cd frontend && npm ci --no-audit --no-fund)

echo "Installing backend dependencies..."
(cd backend && { [[ -d .venv ]] || python3 -m venv .venv; } && .venv/bin/pip install -q -r requirements.txt)
[[ -f backend/.env ]] || cp backend/.env.example backend/.env

if curl -fsS --max-time 10 -o /dev/null "$PROD_BACKEND/api/health"; then
  echo "Live backend on Fly is reachable."
else
  echo "WARNING: can't reach $PROD_BACKEND. It may not be deployed yet." >&2
  echo "         You can still work fully locally with: scripts/dev.sh --local" >&2
fi

echo "Done. Start with: scripts/dev.sh (live backend) or scripts/dev.sh --local (your own backend)"
