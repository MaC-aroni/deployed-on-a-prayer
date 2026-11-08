"""Run the backend's virtualenv Python with the given arguments, from the repo root.

Used by mise tasks (`mise run mac ...`, `mise run test`) so they work the same on macOS,
Linux and Windows. Paths in arguments stay relative to the repo root, where you typed them.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
PYTHON = BACKEND / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def main():
    if not PYTHON.exists():
        sys.exit("Run `mise run setup` first.")
    env = dict(os.environ)
    # Make the backend's packages (app, mac) importable without changing directory.
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(BACKEND), env.get("PYTHONPATH")]))
    sys.exit(subprocess.run([str(PYTHON), *sys.argv[1:]], cwd=ROOT, env=env).returncode)


if __name__ == "__main__":
    main()
