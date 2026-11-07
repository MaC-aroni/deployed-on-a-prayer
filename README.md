# deployed-on-a-prayer

![Deploy](https://github.com/ob1-can-obi/deployed-on-a-prayer/actions/workflows/deploy.yml/badge.svg)

## How to ship

1. `git checkout -b your-feature`
2. Commit, push, and open a pull request.
3. Merge into `main`. The host laptop picks it up and deploys within seconds.

Watch deploys at https://github.com/ob1-can-obi/deployed-on-a-prayer/actions

## How it works

A GitHub Actions self-hosted runner on the host laptop runs `.github/workflows/deploy.yml`
on every push to `main`, which calls `deploy.sh`. Change `deploy.sh` to change how the app starts.
