# Platform: AWS Landing Zone Standards

Owner: Platform engineering.

## Approved services
| Need | Approved service |
|---|---|
| Networking | VPC, security groups, NAT gateway |
| Compute for services | ECS on Fargate (EKS needs an exception) |
| Relational database | Aurora PostgreSQL, RDS PostgreSQL |
| Object storage | S3 (versioned, encrypted) |
| Encryption keys | KMS customer-managed keys |
| Identity | IAM roles (no long-lived user keys for workloads) |

Oracle on RDS is **not** approved for new migrations; move to PostgreSQL.

## Network layout
- Region: us-east-1.
- One VPC per environment, CIDR `10.20.0.0/16`, two availability zones.
- Public subnets for load balancers only; services and databases in private subnets.
- Names and tags include the environment (`rehearsal` or `production`).

## Environments
- `rehearsal` and `production` must never share resources. Everything is named with the
  environment so a rehearsal cannot touch production.

## Related
- "Platform: Approved Terraform Modules"
- "Security: IAM Role Review Process"
