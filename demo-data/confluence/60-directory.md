---
id: directory-approvers
title: "Directory: Teams and Approvers"
parent: handbook
owner: engineering-enablement
labels: [directory, approvers, teams]
---
## Teams

- **claims-platform**: owns ClaimsAdjudicationService and `claims-service-iac`.
- **claims-mcp-team**: owns the Claims MCP tool and `claims-mcp-server`.
- **dba-team**: owns CLAIMS_DB and `claims-db-migrate`.
- **qa-team**: owns `claims-smoke-tests`.
- **platform-engineering**: owns the landing zone and the Platform standards.
- **finance-team**: owns the IT cost allocation and the Finance pages.

## Approvers

All approvals are Jira tickets in project **MAC**. The approver names below are what MaC
pipelines use in `approver:`.

- **`tech-risk`**, the Tech Risk team: approves every production change a cloud migration
  makes, per "Tech Risk: Cloud Migration Approval Policy". Needs a design document.
- **`manager`**, the requester's people manager: approves access requests first, per "Access:
  Requesting Access to an MCP Tool".
- **`claims-mcp-team`**: approves access to the Claims MCP tool, after the manager.

## Approval types

- `tech_risk_cloud_migration`: from `tech-risk`.
- `access_request_manager`: from `manager`.
- `access_request_owner`: from the owning team of the resource.
