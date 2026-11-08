---
id: access-mcp
title: "Access: Requesting Access to an MCP Tool"
parent: handbook
owner: security-engineering
labels: [access, mcp, approval, policy]
---
## When this applies

Any service, agent or person that needs to call an MCP tool owned by another team must
request access first, including services being migrated that used the tool on-prem.

## Approvals, in order

1. **The requester's manager** approves first, confirming the requester needs the access for
   their work. Approver: `manager`.
2. **Then the team that owns the MCP tool** approves, confirming the consumer may use it and
   how. Approver: the owning team, for example `claims-mcp-team` for the Claims MCP tool.

The owning team is only asked after the manager approves. If the manager rejects, the request
ends and the owning team is never asked.

## What the request must say

- Which service or role needs access, and to which MCP tool.
- Which tools it will call, and why.
- That the grant will be made by the owning team's `terraform/access` component and can be
  revoked by destroying it.

Requests are Jira tickets in project `MAC`. In a MaC pipeline they are raised automatically,
one per approval, with the owning team's ticket created only after the manager's is approved.

## The change itself

The grant runs only after both approvals. It runs as its own step, after the MCP tool and the
consumer are deployed, so that undoing the migration revokes it first.
