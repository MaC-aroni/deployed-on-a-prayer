# Tech Risk: PHI/PII Data Handling Standard

Standard owner: Tech Risk.

## Scope
Any system, database or copy of data that contains protected health information (PHI) or
personally identifiable information (PII).

## Requirements
- Encrypt at rest with a customer-managed KMS key, and in transit with TLS 1.2 or later.
- Databases holding PHI live in **private subnets** only, with no public IP.
- Database migrations that move PHI need approval from both the **DBA team** and **Tech Risk**.
- PHI migration steps must be **manual gates**: an engineer presses play, nothing runs
  unattended.
- Verification after a load is mandatory: row counts and checksums per table.
- No PHI in logs, tickets, or test fixtures. Use masked data outside production.

## Evidence
Attach the verification output to the approval ticket.

## Related
- "CLAIMS_DB: Data Dictionary and Classification" (classified Restricted, contains PHI)
- "DBA: Database Migration Sign-off Procedure"
