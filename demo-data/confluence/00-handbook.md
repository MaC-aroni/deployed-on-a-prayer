---
id: handbook
title: "Prayerwell Health Engineering Handbook"
owner: engineering-enablement
labels: [handbook]
---
## About this handbook

This is the home of Prayerwell Health's engineering standards, policies and service
documentation. Everything a team needs to build, change or migrate a system lives under this
page. If a standard here conflicts with what a team was told elsewhere, this handbook wins.

Prayerwell Health is a US health plan. Our systems process medical claims, which contain
protected health information (PHI), so most changes are regulated and need sign-off.

## How the handbook is organised

- **Platform** pages say how systems must be built on AWS: the landing zone, Terraform,
  naming and tagging, Lambda services and the MCP tool platform.
- **Risk and access** pages say which changes need approval, from whom, and how to ask.
- **Data** pages say how claims data may be moved and checked.
- **Engineering** pages say how code reaches production: repositories, reviews and MaC.
- **Services** pages describe each system, who owns it and where its code lives.
- **Directory** pages list the teams and approvers.

## Modernisation programme

We are moving our on-prem claims platform to AWS during 2026. Every migration runs as a MaC
pipeline (Migration as Code): a reviewed `migration.yaml` that is rehearsed in full before it
is allowed to touch production. See "Engineering: Change Management and MaC".
