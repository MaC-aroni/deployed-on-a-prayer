# Eligibility Service: Interface Contract

Owner: member-services team. Consumers: ClaimsAdjudicationService and others.

## Endpoint
`POST /v2/eligibility/check`

Request:
- `memberId` (string, required)
- `serviceDate` (ISO 8601 date, required)
- `procedureCode` (string, required)

Response:
- `eligible` (boolean)
- `reason` (string, only when `eligible` is false)

## Service levels
- Availability 99.9%, p95 latency under 250 ms.
- Timeout for callers: 2 seconds, one retry.

## Constraints for migrations
- The Eligibility Service stays on-prem for now. A migrated ClaimsAdjudicationService must
  still reach it over the existing network path (Direct Connect to the Dallas data centre).
- ClaimsAdjudicationService is its **only** claims-side dependency. Eligibility does not call
  back into claims.
- Any change to the calling network path needs a Tech Risk review.
