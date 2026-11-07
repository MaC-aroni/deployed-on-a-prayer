#!/usr/bin/env bash
# First-time local setup (macOS/Linux). Safe to re-run.
#   scripts/setup.sh frontend   install the frontend, use the host laptop's backend
#   scripts/setup.sh backend    install both, use your own local backend
set -euo pipefail

ROLE="${1:-}"
HOST_BACKEND="http://prayer-host:8000"
if [[ "$ROLE" != frontend && "$ROLE" != backend ]]; then
  echo "Usage: $0 frontend|backend" >&2
  exit 1
fi
cd "$(dirname "$0")/.."

fail() { echo "ERROR: $*" >&2; exit 1; }

command -v node >/dev/null || fail "Node.js is not installed (need 20.19+ or 22.12+)"
node -e '
  const [maj, min] = process.versions.node.split(".").map(Number);
  process.exit(maj > 22 || (maj === 22 && min >= 12) || (maj === 20 && min >= 19) ? 0 : 1);
' || fail "Node.js $(node -v) is too old (need 20.19+ or 22.12+)"

echo "Installing frontend dependencies..."
(cd frontend && npm ci --no-audit --no-fund)

if [[ "$ROLE" == backend ]]; then
  command -v python3 >/dev/null || fail "Python 3 is not installed (need 3.10+)"
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
    || fail "$(python3 --version) is too old (need 3.10+)"
  echo "Installing backend dependencies..."
  (cd backend && { [[ -d .venv ]] || python3 -m venv .venv; } && .venv/bin/pip install -q -r requirements.txt)
  [[ -f backend/.env ]] || cp backend/.env.example backend/.env
  BACKEND_URL="http://localhost:8000"
else
  BACKEND_URL="$HOST_BACKEND"
fi

echo "BACKEND_URL=$BACKEND_URL" > frontend/.env
echo "Frontend will use the backend at $BACKEND_URL"

if [[ "$ROLE" == frontend ]]; then
  if curl -fsS --max-time 5 -o /dev/null "$HOST_BACKEND/api/health"; then
    echo "Host backend is reachable."
  else
    echo "WARNING: can't reach $HOST_BACKEND. Is Tailscale connected, and is the host laptop awake?" >&2
  fi
fi

echo "Done. Start developing with: scripts/dev.sh"
