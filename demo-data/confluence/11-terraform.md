---
id: platform-terraform
title: "Platform: Terraform Standards"
parent: handbook
owner: platform-engineering
labels: [platform, terraform, iac, standard]
---
## Versions

- Terraform **1.10 or newer** (the platform pins 1.17.1), with `required_version = ">= 1.10"`.
- The AWS provider **`hashicorp/aws` version `~> 6.0`**. Use `hashicorp/archive` `~> 2.7` to
  package Lambda code.
- Commit `.terraform.lock.hcl`, with hashes for `linux_amd64`, `linux_arm64`, `darwin_arm64`,
  `darwin_amd64` and `windows_amd64`.

## Layout

- One directory per component: `terraform/<component>/main.tf`, for example
  `terraform/storage`, `terraform/iam` or `terraform/service`. Each is applied, and destroyed,
  on its own.
- Declare `backend "s3" {}` with no settings. MaC supplies the bucket, key and locking, so
  state lands where rollback will find it: one state file per migration, environment and step.

## Variables every component declares

- `mac_env` (string): `rehearsal` or `production`. Every resource name must include it.
- `mac_run_id` (string, default `manual`): the MaC deployment ID that last changed the
  resources, used in tags.

## Provider configuration

Set **default_tags** on the provider with the tags from "Platform: Naming and Tagging Standard",
so every resource is tagged without repeating them.

## Plans must work before dependencies exist

MaC's Build runs `terraform plan` for every component before anything has been created. So
**never look up resources created by other components** with data sources. Build their names
and ARNs from the naming standard instead, using `data "aws_caller_identity"` for the account
and `data "aws_region"` for the region. Those always resolve.

## Checks

Every repository's CI runs `terraform fmt -check`, `terraform init -backend=false` and
`terraform validate` on each component directory.
