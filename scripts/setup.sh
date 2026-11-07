#!/usr/bin/env bash
# First-time local setup (macOS/Linux). Installs both the frontend and backend. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST_BACKEND="http://prayer-host.tail051cbb.ts.net:8000"

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

if curl -fsS --max-time 5 -o /dev/null "$HOST_BACKEND/api/health"; then
  echo "Host laptop's backend is reachable."
else
  echo "WARNING: can't reach $HOST_BACKEND. Is Tailscale connected, and is the host laptop awake?" >&2
  echo "         You can still work fully locally with: scripts/dev.sh --local" >&2
fi

echo "Done. Start with: scripts/dev.sh (host backend) or scripts/dev.sh --local (your own backend)"
