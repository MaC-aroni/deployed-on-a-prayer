# ClaimsAdjudicationService: Architecture Overview

Owner: claims-platform team. Criticality: Tier 1. Last reviewed: 2026-08-14.

## Purpose
ClaimsAdjudicationService decides whether a submitted Medicare claim is paid, denied or sent
for manual review. It processes about 1.2 million claims a day in a nightly batch plus a
real-time API for provider portals.

## Runtime
- Runs on two on-prem VMs (RHEL 7) in the Dallas data centre, behind a hardware load balancer.
- Java 8 (Spring Boot 1.5), packaged as a single fat jar. Java 8 and RHEL 7 are both
  approaching end of support.
- Database: CLAIMS_DB, Oracle 12c Enterprise, 450 GB. See "CLAIMS_DB: Data Dictionary and
  Classification".

## Dependencies
- **Eligibility Service** (downstream, REST): checked for every claim before a decision. See
  "Eligibility Service: Interface Contract".
- **CLAIMS_DB** (Oracle 12c): system of record for claims and adjudication results.
- Nightly SFTP drop from the clearinghouse (input files).

## Code and deployment
- Source: github.com/MaC-aroni/claims-service-iac holds the infrastructure for the target
  platform; the service itself is deployed with `deploy.py` and removed with `undeploy.py`.
- Smoke tests live in github.com/MaC-aroni/claims-smoke-tests (`checks/preflight.py` before a
  change, `checks/smoke.py` after).
- Database migration scripts live in github.com/MaC-aroni/claims-db-migrate (`migrate.py`,
  `verify.py`, `rollback.py`).

## Known issues
- Oracle DATE columns carry a time of day. Any consumer that treats them as plain dates
  loses information. See the data dictionary.
- Batch window is tight: the nightly job must finish by 05:00 CT.

## Target direction
Move to AWS following the Platform landing zone standards: ECS Fargate for the service,
Aurora PostgreSQL (or RDS) for the database.
