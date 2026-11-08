---
id: data-migration
title: "Data: Claims Data Handling and Migration Procedure"
parent: handbook
owner: dba-team
labels: [data, phi, migration, procedure]
---
## Claims data is PHI

Claims records contain protected health information. Moving them is a regulated change.

- **A person must start every claims data copy.** In MaC pipelines, data migration steps are
  `when: manual`, so the copy waits for an engineer to press play, in rehearsal and production.
- Copies are loaded from the approved export, never from a live connection to the on-prem
  database.

## The CLAIMS_DB export

The on-prem Oracle CLAIMS_DB is exported to `data/claims_export.csv` in the `claims-db-migrate`
repository, with columns `CLAIM_ID`, `MEMBER_ID`, `PROVIDER_ID`, `SERVICE_DATE`, `AMOUNT`,
`DIAGNOSIS_CODE` and `CLAIM_STATUS`.

## Converting the data

- **Dates:** Oracle exports dates as `DD-MON-YY`, for example `01-JAN-24`. **Every date must be
  converted to ISO 8601 (`YYYY-MM-DD`, for example `2024-01-01`) before it's written to the
  target.** Services on AWS only accept ISO dates.
- **Amounts** are stored as exact decimals, never floating point.
- Field names change to lowercase snake case (`CLAIM_ID` becomes `claim_id`), and status values
  become lowercase.

## Checking the copy

Every data migration has a verify step that proves nothing was lost: every exported claim is in
the target table, and the row counts match. A failed verify fails the migration.

## Undoing a copy

The rollback deletes every migrated claim from the target. It must be safe to run after a
partial copy, run twice, or run when the table is already gone.
