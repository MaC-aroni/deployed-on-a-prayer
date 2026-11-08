---
id: eng-change-management
title: "Engineering: Change Management and MaC"
parent: handbook
owner: engineering-enablement
labels: [engineering, mac, repositories, policy]
---
## Production repositories

Every repository whose code can run in production must have:

- a protected `main` branch, which can only change through a pull request;
- **one approving review** on every pull request, from someone other than its author;
- CI that must pass before merging.

## MaC (Migration as Code)

Migrations run as MaC pipelines. A pipeline is a `migration.yaml` in the `mac-migrations`
repository, reviewed like any other code. It is made of steps that run existing, reviewed
code from the owning teams' repositories.

- **Build** checks everything without changing anything: every step's repository must have
  CI passing on the exact commit, the commit must be on the protected `main` branch, and it
  must have reached `main` through an approved pull request. It also previews every Terraform
  change.
- **Rehearse** runs the whole pipeline in the rehearsal environment, then undoes all of it.
- **Deploy** runs in production, using exactly the commits that were rehearsed, and waits for
  every required approval.
- **If any step fails, every completed step is undone, newest first.**

## Stages

Pipelines run in this order of stages:

1. **check:** read-only checks, such as being in the right AWS account.
2. **infrastructure:** storage and roles.
3. **data:** data migration.
4. **release:** deploying the services and MCP tools.
5. **access:** access grants between them.
6. **verify:** smoke tests against the migrated system.

## Who writes a step's code

Each step says whether its code is written by the engineers or by the LLM (`codegen`). LLM-written
code always arrives as a pull request that a person reviews, like any other change.
