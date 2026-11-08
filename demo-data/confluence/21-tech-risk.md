---
id: techrisk-cloud-migration
title: "Tech Risk: Cloud Migration Approval Policy"
parent: handbook
owner: tech-risk
labels: [tech-risk, approval, policy, migration]
---
## What needs Tech Risk approval

**Every change a cloud migration makes to production** needs Tech Risk approval before it runs:
creating storage, roles or functions, moving data, and deploying services. One approval covers
one version of the migration plan. If the plan changes, it needs approval again.

Access grants between services are approved through the access process instead (see "Access:
Requesting Access to an MCP Tool"), not by Tech Risk.

## What Tech Risk needs to see

- A **design document** in Confluence covering the current and target architecture, the
  migration steps, the risks and mitigations, the rollback plan and the approvals. Tech Risk
  will not review a request without one.
- Evidence that the **whole migration was rehearsed** end to end in the rehearsal environment
  and fully undone, using exactly the code that will run in production.
- That **every step can be undone**, and that any failure undoes all completed steps.

## How to request it

Raise a Jira ticket in project `MAC` for approver `tech-risk`, linking the design document.
In MaC pipelines this is automatic: the ticket is raised once the design page exists, and every
production-changing step waits for it.

## Turnaround

Tech Risk aims to decide within two business days. Rejections say what must change.
