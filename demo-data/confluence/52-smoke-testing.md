---
id: qa-smoke-testing
title: "QA: Migration Smoke Testing Standard"
parent: handbook
owner: qa-team
labels: [qa, testing, migration, standard]
---
## Before a migration: preflight

Every pipeline starts with a read-only preflight check, which must pass before anything changes:

- The credentials belong to the AWS account the migration targets. A different account fails
  the check, so nothing is ever deployed to the wrong account.
- The services the migration uses (DynamoDB, Lambda) are reachable.

## After a migration: smoke test

Every pipeline ends with a smoke test against the migrated system, in the same environment:

- Each MCP tool answers `initialize` and `tools/list` like an MCP server.
- Each service's `GET /health` returns `ok`.
- **A real migrated record goes through the whole system.** For the claims migration:
  adjudicate claim `CLM-1001`. That proves at once that the data was copied correctly, the
  service works, and the service can call the Claims MCP tool.

A failing smoke test fails the migration, which undoes everything.

## Where the checks live

`MaC-aroni/claims-smoke-tests`: `checks/preflight.py` and `checks/smoke.py`, owned by qa-team.
