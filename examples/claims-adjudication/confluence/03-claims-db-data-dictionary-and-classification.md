# CLAIMS_DB: Data Dictionary and Classification

Engine: Oracle 12c Enterprise. Size: 450 GB. Owner: claims-platform. DBA owner: Enterprise DBA team.

## Classification
**This database contains PHI** (protected health information) and PII. It is classified
Restricted. The PHI/PII Data Handling Standard applies in full.

## Tables
| Table | Rows (approx.) | Contains |
|---|---|---|
| CLAIM | 380 million | Claim header: member id, provider id, amounts |
| CLAIM_LINE | 1.4 billion | Procedure codes, charges (PHI) |
| ADJUDICATION_RESULT | 380 million | Decision, reason codes, ADJUDICATION_DT |
| MEMBER_REF | 41 million | Name, date of birth, address (PII and PHI) |

## Column notes
- `ADJUDICATION_RESULT.ADJUDICATION_DT` is an Oracle `DATE`. **Oracle DATE stores a time of
  day** as well as a calendar date. Downstream reports group by the full timestamp.
- `CLAIM.SERVICE_DT` is also an Oracle `DATE` and also carries a time.
- Amounts are `NUMBER(12,2)`.

## Migration implications
- Target engine is PostgreSQL (Aurora or RDS). PostgreSQL `date` has no time of day. Use
  `timestamp` for these columns or the time is lost and reports change.
- After the load, `verify.py` compares row counts and checksums per table, and compares the
  `ADJUDICATION_DT` values including the time.
- A migration of this database needs approval from the DBA team and from Tech Risk because it
  holds PHI.
