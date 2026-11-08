"""First-time local setup on macOS, Linux or Windows. Safe to re-run.

Run through mise so the pinned Node/Python from mise.toml are used: `mise run setup`.
Standard library only, since nothing is installed yet when this runs.
"""

import shutil
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PROD_BACKEND = "https://deployed-on-a-prayer.fly.dev"
WINDOWS = sys.platform == "win32"


def fail(message):
    sys.exit(f"ERROR: {message}")


def run(cmd, cwd):
    print(f"> {' '.join(str(c) for c in cmd)}", flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def venv_python():
    return BACKEND / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")


def check_versions():
    """Warn, rather than fail, when the tools aren't the ones mise.toml pins."""
    pinned = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))["tools"]

    python = ".".join(map(str, sys.version_info[:3]))
    if python != pinned["python"]:
        print(f"WARNING: Python {python}, but mise.toml pins {pinned['python']}. Use `mise run setup`.")

    npm = shutil.which("npm")
    if not npm:
        fail("Node.js is not installed. Run `mise install`.")
    node = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    if node != pinned["node"]:
        print(f"WARNING: Node {node}, but mise.toml pins {pinned['node']}. Use `mise run setup`.")
    return npm


def main():
    npm = check_versions()

    print("\nInstalling frontend dependencies...")
    run([npm, "ci", "--no-audit", "--no-fund"], cwd=FRONTEND)

    print("\nInstalling backend dependencies...")
    if not venv_python().exists():
        run([sys.executable, "-m", "venv", ".venv"], cwd=BACKEND)
    run([venv_python(), "-m", "pip", "install", "-q", "--disable-pip-version-check",
         "-r", "requirements.txt", "-r", "requirements-dev.txt"], cwd=BACKEND)

    env_file = BACKEND / ".env"
    if not env_file.exists():
        shutil.copy(BACKEND / ".env.example", env_file)
        print("Created backend/.env from backend/.env.example")

    try:
        urllib.request.urlopen(f"{PROD_BACKEND}/api/health", timeout=10)
        print("\nLive backend on Fly is reachable.")
    except OSError:
        print(f"\nWARNING: can't reach {PROD_BACKEND}. You can still work locally with `mise run dev-local`.")

    print("\nDone. Start with `mise run dev` (live backend) or `mise run dev-local` (your own backend).")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        fail(f"command failed with exit code {e.returncode}")
