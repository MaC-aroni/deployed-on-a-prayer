# deployed-on-a-prayer: notes for coding agents

Hackathon project: FastAPI backend in `backend/`, React + Vite frontend in `frontend/`.
Prod is one Fly.io app at https://deployed-on-a-prayer.fly.dev: FastAPI serves `/api` and the
built frontend (see `Dockerfile`, `fly.toml`). Locally, `mise run dev` runs the frontend
against the live backend, and `mise run dev-local` runs both on this machine.

**First-time setup or a broken local environment:** follow `.claude/skills/setup-dev/SKILL.md`.

## Repo and team

- Repo: https://github.com/MaC-aroni/deployed-on-a-prayer (public, in the MaC-aroni org).
  Clone with `gh repo clone MaC-aroni/deployed-on-a-prayer`.
- Maintainers (repo admins): ob1-can-obi, Elathius, Zafeer-R. Any of them can approve and
  merge PRs (not their own) and run Deploy (Actions → Deploy → Run workflow on `main`).
  The list lives in `.github/CODEOWNERS` and in `.github/workflows/deploy.yml`; change both together.
- Only ob1-can-obi has access to the Fly app, so API key values and Fly problems go to them.

## Rules

- Never commit to `main`. Use a branch and open a PR (`gh pr create`); a maintainer
  (ob1-can-obi, Elathius, Zafeer-R) approves and merges.
- Don't add AI attribution to commits: no `Co-Authored-By: Claude ...` (or any other agent)
  trailer, and no "Generated with ..." lines in commit messages.
- Never put API keys in code, and never commit `.env` files. New keys: add the name to
  `backend/.env.example` and tell the user to send the value to ob1-can-obi,
  who manages the Fly secrets.
- Run tools through mise (`mise run ...`, `mise exec -- <cmd>`) so the versions pinned in
  `mise.toml` are used.
- Python dependencies: edit `backend/requirements.in`, then `mise run lock`. Never hand-edit
  `backend/requirements.txt`. The lock is universal, so it covers every OS.
- The frontend calls the backend only through relative `/api/...` URLs. Vite forwards them
  to `BACKEND_URL`, which `scripts/dev.py` sets. Don't hardcode backend hosts or ports.
- All backend routes go under `/api`. Every other path serves the frontend, so new pages are
  added in `frontend/src/App.jsx`.
- CI must pass before a PR can merge: `python -m ruff check --select E9,F63,F7,F82 .` and an import
  of `app.main` in `backend/`, `npm run build` in `frontend/`, and a gitleaks secret scan.

## Cross-platform code

Teammates develop on macOS and Windows; CI and prod (Fly, Docker) run Linux. Code must work
on all three, and passing on one laptop proves nothing about the others.

- **File name case:** macOS and Windows ignore case, Linux doesn't. An import of
  `./home.jsx` for `Home.jsx` works locally and breaks CI and prod. Match case exactly in
  every import, `open()`, static file path and URL to a file. When renaming only the case
  of a file, use `git mv`, or git on macOS/Windows won't notice.
- **Paths:** build them with `pathlib.Path` in Python and `path.join` in Node, anchored to
  the file (`Path(__file__).resolve().parent`), not the current directory. Never hardcode
  `/` or `\` separators, absolute paths like `/Users/...` or `C:\...`, or `~`.
- **Scripts:** write tooling in Python (stdlib only, like `scripts/`) and expose it as a
  `mise.toml` task. No bash or PowerShell scripts, and no shell-only syntax (`&&` chains,
  `export`, `$VAR`) in `package.json` scripts.
- **Subprocesses:** pass argument lists, not shell strings (`subprocess.run([...])`, not
  `shell=True`). Find executables with `shutil.which`, since `npm` is `npm.cmd` on Windows.
  A virtualenv's programs are in `.venv/bin` on macOS/Linux and `.venv\Scripts` on Windows.
- **Files:** open text files with `encoding="utf-8"`, since Windows defaults to another
  encoding. Line endings are normalized to LF by `.gitattributes`; don't fight it.
- **Packages:** before adding a dependency, check that it supports Windows. If it doesn't,
  add an environment marker in `requirements.in` (for example `; sys_platform != "win32"`)
  and make the code work without it.
- **Environment variables:** read them in code (`os.environ`, `process.env`) or `.env`
  files. Don't document commands that set them inline (`FOO=1 cmd` doesn't work on Windows).
- **Ports and hosts:** use `localhost` and the existing ports (backend 8000, frontend 5173).
  Fly serves on 8080 inside the container.
