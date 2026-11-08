# Platform: Approved Terraform Modules

Owner: Platform engineering. Only the modules below may be used for migrations.

| Module | Purpose | Notes |
|---|---|---|
| `network` | VPC, subnets, route tables, security groups | Takes `mac_env`; names every resource with it |
| `iam` | Service task role and execution role | Any new role needs a Security review |
| `ecs-service` | Fargate service and load balancer | Private subnets only |
| `aurora-postgres` | Aurora PostgreSQL cluster with KMS | Required for PHI databases |

## Rules
- Pin module versions. Do not use a module from outside this list.
- Declare `variable "mac_env" {}` and use it in every resource name and tag.
- State is kept per environment and per step; never share state between rehearsal and
  production.
- Every mutating step needs a rollback (`terraform destroy` scoped to its own state).

## Repositories
Infrastructure for ClaimsAdjudicationService is in github.com/MaC-aroni/claims-service-iac:
`terraform/network` and `terraform/iam`.
