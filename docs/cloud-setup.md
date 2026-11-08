# Cloud setup: AWS, Jira and Confluence

What the runner needs from the outside world, who sets it up, and the values it reads.
Never commit keys: put them in `backend/.env` locally, and send them privately to
ob1-can-obi for Fly secrets.

## AWS

One AWS Organization with three accounts, not one account per teammate:

| Account | Used for | Who |
|---|---|---|
| management | billing, IAM Identity Center, the Terraform state bucket | maintainers |
| mac-rehearsal | Rehearse runs (everything is created, then undone) | the runner; teammates for debugging |
| mac-production | Deploy runs | the runner only; humans read-only |

Teammates sign in through IAM Identity Center with their own user. A single account also
works (the spec's `rehearsal` block is optional); then `MAC_ENV` naming is the only
separation between rehearsal and production.

Setup, in order:
1. Create the organization and the two member accounts. Turn on MFA for the root user and
   set a budget alert.
2. Create the state bucket in the management account (versioning on). The runner uses S3
   locking, so there is no DynamoDB table. Terraform state lands at
   `mac/<migration>/<rehearsal|production>/<step>.tfstate`.
3. Create a runner IAM user or role in each target account, allowed to create what the demo
   needs (VPC, security group, IAM role, ECS or RDS) and to read and write the bucket.
4. Put the account IDs in `examples/claims-adjudication/migration.yaml` (`target.account`,
   and `target.rehearsal` if rehearsal is a separate account).

## Jira

1. Create a free Atlassian site and a Jira project with key `MAC`.
2. Create `MAC-1` (tech risk), `MAC-2` (IAM review) and `MAC-3` (DBA sign-off), which the
   demo spec points at.
3. The runner treats the statuses `Approved` and `Done` as approved, and `Rejected` and
   `Declined` as rejected. Any other status is pending. Add an `Approved` status to the
   workflow if it only has To Do, In Progress and Done.
4. Create an API token for the account that owns the project.

## Confluence

Same Atlassian site and API token. Create a space with key `CLAIMS`, then run
`mise run load-confluence`. It loads the ten demo pages from
`examples/claims-adjudication/confluence/` (design doc, section 4.4) and can be re-run.

## Variables

| Variable | Where it is set |
|---|---|
| `ATLASSIAN_SITE` (for example `https://<site>.atlassian.net`), `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN` | `backend/.env`, Fly secrets |
| `MAC_TF_STATE_BUCKET`, `MAC_TF_STATE_REGION` | `backend/.env`, Fly secrets |
| `AWS_PROFILE`, or `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` | `backend/.env` or the AWS CLI, Fly secrets |
| `GITHUB_TOKEN` | `backend/.env`, Fly secrets |

## Checks

- `aws sts get-caller-identity` shows the runner in the right account.
- `GET <ATLASSIAN_SITE>/rest/api/3/issue/MAC-1` returns 200 with the token.
- `mise run mac validate examples/claims-adjudication/migration.yaml` passes.
- `mise run mac build examples/claims-adjudication/migration.yaml` reaches a real
  `terraform plan`.
