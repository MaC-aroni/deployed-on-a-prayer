---
id: service-claims-mcp
title: "Services: Claims MCP Tool"
parent: handbook
owner: claims-mcp-team
labels: [service, mcp, claims, migration]
---
## What it does

The Claims MCP tool answers eligibility questions for agents and services. Its tools:

- `check_eligibility(member_id, service_date)`: whether the member was covered on that date
  (an ISO date).
- `coverage_period(member_id)`: the member's coverage start and end dates.

## Today and target

- Today it runs on-prem next to the claims platform.
- On AWS it is a Lambda function, `mac-claims-<env>-mcp`, following "Platform: MCP Tool
  Platform", with its own role `mac-claims-<env>-mcp` that may only write logs.
- Owner: **claims-mcp-team**.

## Repository

`MaC-aroni/claims-mcp-server`:

- `server/handler.py`: the MCP server.
- `terraform/server`: the function and its AWS_IAM function URL.
- `terraform/access`: the access grants to consumers, which claims-mcp-team controls.

## Consumers

**ClaimsAdjudicationService** calls `check_eligibility` for every claim. When it moves to AWS,
its role `mac-claims-<env>-service` needs access, approved by its manager and then by
claims-mcp-team.
