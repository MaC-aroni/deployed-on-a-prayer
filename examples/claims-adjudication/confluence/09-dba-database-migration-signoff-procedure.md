# DBA: Database Migration Sign-off Procedure

Owner: Enterprise DBA team. Approver team: DBA. Review SLA: 3 business days.

## When sign-off is required
Any migration, copy or schema change of a production database.

## What is required
- A **DBA database migration approval** (Jira ticket in the `MAC` project, type
  `dba_db_migration`) before the migration step runs.
- The migration is a **manual gate**: an engineer presses play. It never starts on its own.
- A tested `rollback.py` that returns the target to its prior state, and is safe to run twice.
- A `verify.py` that compares row counts and checksums per table, and compares date and
  timestamp columns including the time of day.

## Checklist before sign-off
1. Rehearsal run completed and fully undone.
2. Source column types mapped to target types. Oracle `DATE` maps to PostgreSQL
   `timestamp`, not `date`.
3. Verification output attached to the ticket.
4. Rollback tested in rehearsal.

## Related
- "Tech Risk: PHI/PII Data Handling Standard"
- "CLAIMS_DB: Data Dictionary and Classification"
