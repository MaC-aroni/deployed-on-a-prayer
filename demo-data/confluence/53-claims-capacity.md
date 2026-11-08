---
id: service-claims-capacity
title: "Services: ClaimsAdjudicationService Capacity and Usage"
parent: handbook
owner: claims-platform
labels: [service, claims, capacity, usage, cost]
---
## Why this page exists

These are the measured usage figures for ClaimsAdjudicationService and the parts of AWS it uses.
MaC's cost estimate is calculated from this page, so every figure here must be a measurement or
a documented design fact, never a guess. If a figure is missing, ask claims-platform to measure
it and add it here.

## Claims volume

- ClaimsAdjudicationService decides an average of 40,000 claims per day, measured on the
  on-prem service over the last 12 months.
- The busiest day of the month, the 1st, reaches 95,000 claims per day. Lambda and DynamoDB on
  demand are billed per request, so the monthly bill follows the average, not the peak.

## How each claim uses AWS

- Each claim invokes the service function `mac-claims-<env>-service` 1 time, with
  `POST /adjudicate`.
- Each claim calls the Claims MCP tool's `check_eligibility` 1 time, which invokes the tool's
  function `mac-claims-<env>-mcp` 1 time.
- Each claim reads its record from the claims table `mac-claims-<env>-claims` 1 time.
- Each claim writes to the claims table 1 time, when its decision is stored on the claim.
- Monitoring calls `GET /health` on each of the two functions 1 time per minute.

## Claims table size

- The claims table keeps the last 12 months of claims: 14,600,000 claims.
- An average claim record is 1.2 KB in DynamoDB format, measured from the CLAIMS_DB export.
- The data migration loads all 14,600,000 claims into the table 1 time.

## Lambda measurements

- The Claims MCP tool was load-tested on Lambda in the platform sandbox, at the standard
  256 MB: its average billed duration is 60 ms per invocation.
- ClaimsAdjudicationService has not been load-tested on Lambda yet, so its billed duration on
  AWS is not known. claims-platform will add it here after the first rehearsal.

## Logs

- Each invocation of either function writes about 2 KB of logs to CloudWatch Logs: the
  platform's START, END and REPORT lines and one JSON line from the service.
- Log groups keep logs for 30 days.
