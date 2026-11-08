# Tech Risk: Cloud Migration Approval Policy

Policy owner: Tech Risk. Approver team: Tech Risk. Review SLA: 5 business days.

## When this policy applies
Any production service, or any change to its hosting, moving from on-prem to a public cloud.

## What is required
- A **Tech Risk cloud migration approval** (Jira ticket in the `MAC` project, type
  `tech_risk_cloud_migration`) before network or compute is provisioned and before the
  service is deployed.
- The ticket carries a business justification with: what is moving, why, the risk, the
  mitigation, and the rollback plan.
- Every change must be rehearsed in a non-production environment first, and must be
  fully reversible.

## Approval criteria
1. The target uses services on the Platform approved list.
2. The rollback is tested.
3. Data classification is stated. If the service holds PHI or PII, the PHI/PII Data Handling
   Standard also applies.

## Related
- "Tech Risk: PHI/PII Data Handling Standard"
- "Platform: AWS Landing Zone Standards"
