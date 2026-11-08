---
id: finance-onprem-costs
title: "Finance: ClaimsAdjudicationService Run Costs Today"
parent: handbook
owner: finance-team
labels: [finance, cost, on-prem, claims]
---
## What it costs today

What ClaimsAdjudicationService and CLAIMS_DB cost to run in the data centre, from the 2026 IT
cost allocation. These are the costs the migration to AWS removes.

- Application VMs for the service (2 VMs, 8 vCPU and 32 GB each): $1,150 per month.
- Oracle Database 12c Enterprise Edition licence support for CLAIMS_DB: $50,400 per year.
- SAN storage and backups for CLAIMS_DB: $590 per month.
- The service's share of data-centre space, power and cooling: $420 per month.
- DBA and operations time: $1,900 per month, about 20 hours at $95 an hour.
- The Claims MCP tool's on-prem server, which moves to AWS in the same migration: $380 per month.

## What is not included

- Development work, which doesn't change with the migration.
