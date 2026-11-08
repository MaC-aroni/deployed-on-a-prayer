# ClaimsAdjudicationService: Runbook

Owner: claims-platform on-call. Escalation: claims-platform lead, then Platform duty manager.

## Health checks
- `GET /health` returns 200 when the service and its database connection are up.
- The nightly batch must report `BATCH_COMPLETE` in the log by 05:00 CT.

## Common incidents
| Symptom | Likely cause | Action |
|---|---|---|
| Claims stuck in PENDING | Eligibility Service timeout | Check Eligibility health; restart the worker pool |
| Batch overruns 05:00 | Slow Oracle query on ADJUDICATION_DT | Rebuild the index, rerun the batch |
| 500 on adjudicate | Connection pool exhausted | Restart the service, raise a ticket |

## Restart procedure
1. Drain the VM from the load balancer.
2. Stop the service (`systemctl stop claims-adjudication`).
3. Start it and wait for `/health` to return 200.
4. Return the VM to the load balancer.

## Migration notes
- Before any change to the database, run the preflight checks (`checks/preflight.py`).
- A migration is reversible only if `rollback.py` has been tested in rehearsal.
- Never run a database migration without DBA sign-off. See "DBA: Database Migration
  Sign-off Procedure".
