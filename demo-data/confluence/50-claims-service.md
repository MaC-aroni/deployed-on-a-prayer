---
id: service-claims-adjudication
title: "Services: ClaimsAdjudicationService"
parent: handbook
owner: claims-platform
labels: [service, claims, migration]
---
## What it does

ClaimsAdjudicationService decides medical claims. For each claim it reads the claim record,
checks with the Claims MCP tool that the member had coverage on the date of service, and
returns a decision:

- `approved` if the member was eligible and the amount is at most 5,000.
- `pending_review` if eligible but over 5,000.
- `denied` if the member wasn't covered.

## Today (on-prem)

- A Java 8 application on a data-centre VM, reading the Oracle CLAIMS_DB directly.
- It calls the on-prem Claims MCP tool for eligibility.
- Owner: **claims-platform**.

## Target (AWS)

- A Python 3.12 Lambda function, `mac-claims-<env>-service`, behind an AWS_IAM function URL,
  with `GET /health` and `POST /adjudicate {"claim_id": "..."}`.
- Reads claims from the DynamoDB table `mac-claims-<env>-claims`.
- Calls the Claims MCP tool `check_eligibility`, which needs access approved through "Access:
  Requesting Access to an MCP Tool".

## Repositories

- `MaC-aroni/claims-service-iac`: the service code (`service/`) and its infrastructure:
  `terraform/storage` (the claims table), `terraform/iam` (the service's and the MCP tool's
  roles) and `terraform/service` (the Lambda function).
- `MaC-aroni/claims-db-migrate`: moves CLAIMS_DB (`migrate.py`, `verify.py`, `rollback.py`).
- `MaC-aroni/claims-smoke-tests`: `checks/preflight.py` before the migration, and
  `checks/smoke.py` after it, which adjudicates claim `CLM-1001` end to end.

## Dependencies

- **Claims MCP tool** (owner claims-mcp-team) for eligibility.
- **CLAIMS_DB** (owner dba-team), whose claims are PHI.
