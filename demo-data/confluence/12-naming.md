---
id: platform-naming
title: "Platform: Naming and Tagging Standard"
parent: handbook
owner: platform-engineering
labels: [platform, naming, tagging, standard]
---
## Resource names

Names follow `mac-<system>-<env>-<component>`, where `<env>` is `rehearsal` or `production`.
For the claims system:

- Claims table (DynamoDB): `mac-claims-<env>-claims`, partition key `claim_id` (string).
- ClaimsAdjudicationService role and Lambda function: `mac-claims-<env>-service`.
- Claims MCP tool role and Lambda function: `mac-claims-<env>-mcp`.

Because the environment is part of every name, a rehearsal can never change or delete a
production resource.

## Required tags

Every resource carries these tags, set through the Terraform provider's `default_tags`:

- `mac:migration`: the migration's name, for example `claims-adjudication-onprem-to-aws`.
- `mac:env`: `rehearsal` or `production`.
- `mac:deployment-id`: the MaC run that last changed the resource (`mac_run_id`).
- `managed-by`: `MaC`.
- `owner-team`: the owning team from "Directory: Teams and Approvers".

The `mac:deployment-id` tag is how on-call engineers find which deployment created or changed
something.
