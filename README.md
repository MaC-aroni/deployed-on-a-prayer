# deployed-on-a-prayer

![Deploy](https://github.com/ob1-can-obi/deployed-on-a-prayer/actions/workflows/deploy.yml/badge.svg)

## How to ship

1. `git checkout -b your-feature`
2. Commit, push, and open a pull request.
3. Merge into `main`. The host laptop picks it up and deploys within seconds.

Watch deploys at https://github.com/ob1-can-obi/deployed-on-a-prayer/actions

## Adding an API key

Never put keys in code or commit a `.env` file.

1. Send the key to the repo owner privately (DM or password manager, not the group chat).
2. The owner adds it as a repo secret:
   `gh secret set MY_API_KEY -R ob1-can-obi/deployed-on-a-prayer`
   (or Settings → Secrets and variables → Actions).
3. Add the key name, with no value, to `.env.example` and commit that.
4. The next deploy writes it into `.env` on the host laptop. Read it in code as `process.env.MY_API_KEY` / `os.environ["MY_API_KEY"]`.

Non-sensitive settings (like `PORT`) go under the Variables tab instead and work the same way.

**Local dev:** `cp .env.example .env` and fill in your own values. `.env` is gitignored.

## How it works

A GitHub Actions self-hosted runner on the host laptop runs `.github/workflows/deploy.yml`
on every push to `main`, which calls `deploy.sh`. Change `deploy.sh` to change how the app starts.
