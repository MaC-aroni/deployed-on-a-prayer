# Security: IAM Role Review Process

Owner: Security. Approver team: Security. Review SLA: 2 business days.

## When review is required
Any migration that creates or changes an IAM role or policy.

## What is required
- An **IAM role review** (Jira ticket in the `MAC` project, type `iam_role_review`) before the
  IAM step runs.
- Least privilege: list every action and resource the role needs. No `*` actions and no `*`
  resources, except where AWS has no resource-level support.
- Workloads use roles with short-lived credentials. No long-lived user access keys.
- Roles are named with the environment (`rehearsal` or `production`) and tagged with the
  owning team.

## Review checklist
1. Policy attached to the role is the smallest set that works.
2. Trust policy names only the intended service.
3. Rollback removes the role and its policies.

## Related
- "Platform: AWS Landing Zone Standards"
- "Platform: Approved Terraform Modules" (`iam` module)
