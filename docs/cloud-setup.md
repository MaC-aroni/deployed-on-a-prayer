# Cloud setup: AWS, Atlassian (Jira + Confluence) and NVIDIA

What the runner needs from the outside world and the values it reads. **Never commit keys:**
put them in `backend/.env` locally (gitignored), and send them privately to ob1-can-obi for
the Fly secrets.

## AWS: one account

We use **one AWS account** for the hackathon. Rehearsal and production share it and are kept
apart by name: every resource includes `MAC_ENV` (`mac-claims-rehearsal-...` vs
`mac-claims-production-...`), and Terraform state is separate per environment. Leave
`target.rehearsal` out of the spec.

1. **Budget alert:** set an AWS Budget, for example $20 a month, with an email alert. The demo
   uses Lambda, DynamoDB on demand and S3, which cost cents when idle.
2. **State bucket:** create an S3 bucket in `us-east-1` with versioning on, for example
   `mac-terraform-state-<account-id>`. There's no DynamoDB lock table: the runner uses S3's
   own locking. State lands at `mac/<migration>/<rehearsal|production>/<step>.tfstate`.
3. **Runner credentials:** an IAM user (or role) for the runner, with the policy below and an
   access key. It only reaches resources named `mac-claims-*` and the state bucket.
4. **Account ID:** put it in `examples/claims-adjudication/migration.yaml` as `target.account`.
   The preflight check refuses to run against any other account.

### The runner's IAM policy

Replace `<account-id>` and `<state-bucket>`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "WhoAmI", "Effect": "Allow", "Action": "sts:GetCallerIdentity", "Resource": "*"},
    {"Sid": "PreflightLists", "Effect": "Allow",
     "Action": ["dynamodb:ListTables", "lambda:ListFunctions"], "Resource": "*"},
    {"Sid": "ClaimsTables", "Effect": "Allow", "Action": "dynamodb:*",
     "Resource": "arn:aws:dynamodb:us-east-1:<account-id>:table/mac-claims-*"},
    {"Sid": "ClaimsFunctions", "Effect": "Allow", "Action": "lambda:*",
     "Resource": "arn:aws:lambda:us-east-1:<account-id>:function:mac-claims-*"},
    {"Sid": "ClaimsRoles", "Effect": "Allow",
     "Action": ["iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole",
                "iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy", "iam:GetRolePolicy",
                "iam:DeleteRolePolicy", "iam:AttachRolePolicy", "iam:DetachRolePolicy",
                "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
                "iam:ListInstanceProfilesForRole"],
     "Resource": "arn:aws:iam::<account-id>:role/mac-claims-*"},
    {"Sid": "PassClaimsRolesToLambda", "Effect": "Allow", "Action": "iam:PassRole",
     "Resource": "arn:aws:iam::<account-id>:role/mac-claims-*",
     "Condition": {"StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}}},
    {"Sid": "TerraformState", "Effect": "Allow",
     "Action": ["s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
     "Resource": ["arn:aws:s3:::<state-bucket>", "arn:aws:s3:::<state-bucket>/mac/*"]}
  ]
}
```

## Atlassian: one site for Jira and Confluence

1. Create a free Atlassian site with Jira and Confluence, for example
   `https://<your-site>.atlassian.net`.
2. **Jira:** create a project with key **`MAC`**. In its workflow, add the statuses
   **`Approved`** and **`Rejected`**. The runner treats `Approved` and `Done` as approved;
   `Rejected`, `Declined` and `Won't Do` as rejected; anything else as pending.
   **Don't create any tickets:** MaC raises them itself during Build, one per approval in the
   spec (Tech Risk; then manager, then the Claims MCP team for MCP access).
3. **Confluence:** create a space with key **`CLAIMS`**.
4. **API token:** create one at id.atlassian.com (Security → API tokens), for an account that
   can create Jira issues and Confluence pages.
5. **Optional, to assign tickets:** find each approver's Jira accountId and set
   `MAC_JIRA_ASSIGNEES`, for example
   `{"tech-risk": "712020:...", "manager": "712020:...", "claims-mcp-team": "712020:..."}`.
   Without it, tickets are created unassigned.
6. **Publish the company knowledge base** (the 14 pages in `demo-data/confluence/`) into
   the space. It's safe to re-run, and it updates the same pages:
   `mise run mac publish-knowledge demo-data/confluence`

## NVIDIA (the LLM that writes the design page)

Create an API key at build.nvidia.com and set `NVIDIA_API_KEY`. The default model is
`nvidia/nemotron-3-ultra-550b-a55b` (the older `nemotron-3-super-120b-a12b` is listed by NIM
but returns 404 on chat calls). Override it with `MAC_LLM_MODEL`. Without the key, Build still works, but the design page
isn't written and the Tech Risk ticket waits.

## Variables

All go in `backend/.env` locally, and in Fly secrets for the deployed app:

| Variable | Value |
|---|---|
| `GITHUB_TOKEN` | a token that can read the `MaC-aroni` repos |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (or `AWS_PROFILE` locally) | the runner's credentials |
| `MAC_TF_STATE_BUCKET`, `MAC_TF_STATE_REGION` | the state bucket, and `us-east-1` |
| `ATLASSIAN_SITE`, `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN` | the site URL, the token's account email, and the token |
| `CONFLUENCE_SPACE_KEY` | `CLAIMS` |
| `JIRA_PROJECT` | `MAC` (the default) |
| `MAC_JIRA_ASSIGNEES` | optional, see above |
| `NVIDIA_API_KEY` | the NVIDIA key |

## Checks, in order

1. `aws sts get-caller-identity` shows the runner's user in the right account.
2. `mise run mac validate examples/claims-adjudication/migration.yaml` passes.
3. `mise run mac publish-knowledge demo-data/confluence` prints `published 14 pages`.
4. `mise run mac build examples/claims-adjudication/migration.yaml` passes all of these:
   - the guardrails
   - the preflight (right account)
   - a real `terraform plan` for each infrastructure step
   - the design page written to Confluence
   - the Tech Risk and manager tickets raised in Jira
