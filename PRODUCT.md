# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Platform and migration engineers at a company moving a legacy service to the cloud, working at
their desk in a browser, usually with Jira, Confluence and GitHub open beside the console. Their
job: get a migration planned, approved, rehearsed and deployed without a step nobody can undo,
and know at any moment where it stands and why it stopped. Around them, approvers (Tech Risk,
DBA, Security, service owners) act in Jira and only read the console. Secondary audience during
the hackathon: judges and the team watching a short live demo.

## Product Purpose

MaC (Migration as Code) turns a company's existing documentation into an executable migration.
Nemotron agents read the Confluence knowledge base, build a knowledge graph, write the
`migration.yaml` pipeline as a reviewable pull request and raise the approvals as Jira tickets
with justifications. A deterministic runner executes the reviewed pipeline (Build → Rehearse →
Deploy) against real AWS with approval gates, manual breakpoints and full rollback on any failure;
when a step fails, an AI diagnostician explains it, writes a report or proposes a fix a person
approves. Success: a typed request becomes a running, verified service in AWS with every decision
traceable to a document, a ticket or a person, and nothing irreversible done by a model.

## Positioning

Models plan, review and diagnose; a boring state machine executes, and no model is in Deploy's
execution path. Approvals are part of the artifact (raised by code from the spec, one ticket per
approval per plan version), the pipeline is a pull request people review, every mutating step
has an undo and the runner undoes everything on failure, and steps inherit the guardrails of the
source repositories they pin. Cloud vendors' migration tools propose a plan and stop; MaC raises
the approvals, commits the pipeline, runs it with rollback, and fixes it when it breaks.

## Operating Context

- Knowledge base: Confluence pages (16 drafted pages for the demo tenant Prayerwell Health in
  `demo-data/confluence/`); every agent output cites page sections by stable id.
- Work systems: Jira (project `MAC`) for approvals, review and fix tickets; GitHub for the
  pipeline repo `MaC-aroni/mac-migrations`, the four "existing prod" repos and sign-in; AWS (one
  account, rehearsal and production separated by name, Terraform state in S3).
- The console is one Fly.io app (FastAPI serves `/api` and the built React frontend); sign-in is
  GitHub OAuth with write access to the repo; the buttons change real AWS, Jira and Confluence.
- Rituals: a migration is launched from the Migration page, followed on the pipeline page, its
  agents watched on the agent-hierarchy page, approvals given in Jira (or the console for pages
  MaC wrote), failures investigated and fixes approved by a person. Runs take minutes.

## Capabilities and Constraints

- Spec `mac/v0.3`: stages, steps (`check`, `script`, `iac`, `db_migration`), `needs`,
  `requires_approval`, `when: manual` (a breakpoint), `codegen`, `outputs` with signed probes,
  approvals with `after` chains and `design_doc`.
- Runner: Build, Rehearse, Deploy, Cancel, Undo and Retry undo; run statuses `running`,
  `waiting`, `rolling_back`, `succeeded`, `failed`, `rollback_failed`, `undone`, `cancelled`.
- Agents: knowledge graph, Planner, approvals/compliance, guide and code writers (CLI),
  design-page writer, usage reader and cost estimate, AI help on failure (Explain · Report ·
  Auto-fix), Investigate and Approve fix, Learn and Describe (Confluence pages with review
  tickets), licence check for repositories added by URL, a read-only chat assistant. Every agent
  emits `agent` events drawn as a Director → workers → Compiler hierarchy.
- Console: Pipelines, Migration, pipeline page (graph, step panel, approvals, endpoints, cost,
  Build report, activity, history), agent hierarchy, knowledge pages with review, Services, Runs,
  Chat, Demo, sign-in gate, light and dark themes.
- Constraints: the UI talks to the backend only through `/api/...`; the runner never calls a
  model; all agent output is reviewed by a person before it has effect; secrets never in the
  repo; macOS, Windows and Linux; CI gates every merge; frontend dependencies are React, Vite and
  `lucide-react` only.
- Terminology: migration, pipeline, run, step, stage, approval, breakpoint, Learn, Describe,
  Investigate, Approve fix, knowledge base, graph.
- Undecided: the agents' end-to-end behaviour against real Nemotron on the live deployment; API
  endpoints for the guide and code writers.

## Brand Commitments

- Name: **MaC · Migration as Code**. Organisation `MaC-aroni`. Binding.
- Logo: the mark-only file (`frontend/src/assets/maclogo.png`, `frontend/public/maclogo*.png`).
  Binding.
- Nemotron / NVIDIA stays visible wherever an agent works: the working-agent icon, the agent
  hierarchy page, model names and reasoning traces. Binding.
- Not binding: the GitLab-pipeline mental model of the console; the Prayerwell Health demo tenant.
- Voice: plain, concrete, short sentences; server messages shown verbatim; no marketing adjectives.
- Visual direction requested on 2026-11-08 for the replacement world: light, well spaced,
  high-end luxury feel, nothing that reads as generic AI-generated UI. Binding.

## Evidence on Hand

- Real runs: Build and Rehearse have run end to end against the AWS account. A real production
  Deploy has not been confirmed in this record.
- Demo pipeline `examples/claims-adjudication/migration.yaml` (8 steps, 4 repos, 3 approvals, one
  breakpoint, declared outputs with probes), 16 knowledge pages, the four demo repositories.
- Backend test suite: about 300 tests.
- No customer testimonials, benchmarks, pricing, case studies or press exist; do not invent any.
- Decisions: `MAC.md` (pre-build), `plan.md`, `docs/api.md`, `docs/planning-api.md`,
  `docs/ui-data-needs.md`, `docs/runner.md`, `docs/agents.md`.

## Product Principles

1. A person decides where something is irreversible, accountable or ambiguous; everything else is
   friction to remove. Show every such decision as one clear action.
2. The runner is boring and the agents are visible: never hide what a model did, where, or what
   it cited.
3. Show the server's truth. Statuses, reasons and refusals come from the API and are shown as
   written; the UI never re-implements the rules.
4. One next action per screen, large and obvious; everything else behind the menu.
5. Nothing fabricated: no invented data, numbers or claims beyond the declared demo tenant.
