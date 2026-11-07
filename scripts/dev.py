"""Start local dev servers with hot reload, on macOS, Linux or Windows.

    mise run dev        frontend only, using the live backend on Fly
    mise run dev-local  backend and frontend, both on this machine
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PROD_BACKEND = "https://deployed-on-a-prayer.fly.dev"
WINDOWS = sys.platform == "win32"


def stop(proc):
    if proc.poll() is not None:
        return
    if WINDOWS:
        # uvicorn --reload runs the server in a child process; kill the whole tree.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
        proc.wait(timeout=10)


def main():
    local = "--local" in sys.argv[1:]
    python = BACKEND / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
    npm = shutil.which("npm")
    if not npm or not python.exists() or not (FRONTEND / "node_modules").exists():
        sys.exit("Run `mise run setup` first.")

    env = dict(os.environ)
    backend = None
    if local:
        backend = subprocess.Popen(
            [python, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"], cwd=BACKEND
        )
        env["BACKEND_URL"] = "http://localhost:8000"
        print("Backend:  http://localhost:8000/docs (on this machine, reloads on save)")
    else:
        env["BACKEND_URL"] = PROD_BACKEND
        print(f"Backend:  {PROD_BACKEND} (live on Fly)")
    print("Frontend: http://localhost:5173", flush=True)

    try:
        subprocess.run([npm, "run", "dev"], cwd=FRONTEND, env=env)
    except KeyboardInterrupt:
        pass
    finally:
        if backend:
            stop(backend)


if __name__ == "__main__":
    main()
