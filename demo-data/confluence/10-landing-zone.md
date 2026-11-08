---
id: platform-landing-zone
title: "Platform: AWS Landing Zone Standards"
parent: handbook
owner: platform-engineering
labels: [platform, aws, standard]
---
## Scope

These standards apply to every workload Prayerwell Health runs on AWS, including systems
migrated from the on-prem data centre.

## Region and accounts

- All workloads run in **us-east-1**.
- Each programme has one AWS account. The **rehearsal** and **production** environments share
  it and are kept apart by name: every resource name contains the environment (see "Platform:
  Naming and Tagging Standard").
- Nothing may be created in production that hasn't first been created, tested and removed in
  rehearsal by the same pipeline.

## Approved services

New workloads may only use these services without a Tech Risk exception:

- **AWS Lambda** for compute, with Python 3.12. See "Platform: Lambda Service Standard".
- **Amazon DynamoDB** for operational key-value data such as claims lookups, billed on demand
  (`PAY_PER_REQUEST`).
- **AWS IAM** roles for every workload, one role per function, least privilege.
- **Amazon S3** for Terraform state only, in the programme's state bucket.
- **Amazon CloudWatch Logs** through the standard Lambda execution policy.

Relational databases, containers, VPCs and NAT gateways need a Tech Risk exception, because
serverless workloads in the landing zone don't need private networking.

## Access between workloads

Workloads call each other over **Lambda function URLs with AWS_IAM authentication**. Callers
sign requests with their role (AWS SigV4). Public, unauthenticated URLs are not allowed.

## Changes

All infrastructure is created by Terraform from a reviewed repository (see "Platform: Terraform
Standards"). Changes made by hand in the console are not allowed and are removed on sight.
