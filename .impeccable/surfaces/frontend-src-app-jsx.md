---
version: 1
slug: "frontend-src-app-jsx"
primary_target: "frontend/src/App.jsx"
related_targets: ["frontend/src/dial.css","frontend/src/components/Shell.jsx","frontend/src/pages/Migrations.jsx"]
---

# Surface: the MaC console (every route under /)

Scope: the whole console shell and its pages; visitor mode Operate. Audience: platform and
migration engineers running a migration; approvers who only read. Job: see where every
migration stands, launch and follow runs, decide at breakpoints, approvals and fixes. Proof and
content come from the API; nothing is invented. Constraints: full existing functionality kept;
React + Vite + lucide only; frontend-only change; works in both themes (dark becomes a night dial).

## Direction contract

THESIS: a migration console as a fine instrument you glance at and trust: silvered ground, ink,
one blued-steel accent and a trace of gilt on the single primary action. It refuses the
category's dark-mode dashboard of glowing cards and the stacked hero-metric tiles.

OWN-WORLD: plain silvered ground (#ecebe7, no texture: the user asked for plain grounds in both
themes), graphite ink (#1c1e24), muted (#5d6170), blued-steel accent (#2b4bb7) for selection,
links and the running hand, gilt (#b89a5a) only on the primary action and the brand ring.
One-device-pixel hairline rules replace surfaces; panels are transparent on the ground, no
shadows, no borders thicker than a hairline. Didone numerals (Bodoni Moda) for figures and
counts only; Source Serif 4 (500) for titles, since the Didone was hard to read at title sizes;
Albert Sans for UI text; JetBrains Mono for ids only. Generous space: 32px gutters, rows at least 72px
(a title line and up to two meta lines), one headline per screen. The night dial is the same ink logic inverted (#15161a).

STORY: the engineer sees the state of every migration as a quiet instrument, finds the one next
action, and trusts that the hand only moves when the runner does.

FIRST VIEWPORT: the Pipelines page. Sidebar (288px) as a silvered rail with hairline-separated
groups and the gilt brand mark. Headline "Pipelines" in Didone at 40px with one muted line
beneath. A ruled statement, not tiles: three figures set as a single hairline-ruled row
(Pipelines · Active · Deployed) in Didone numerals at 48px. Below, the filter and the one gilt
primary "Build a migration pipeline" on one line; then the pipeline table with 72px rows, a
mini stage gauge at the row's left, status as a hairline pill, stages as plain small caps.

FORM: candidate 4 of the grounded list (haute-horlogerie dial; the Swiss annual report was
candidate 1), assigned by the roll. Signature move: the stage gauge, a slim ring whose index
marks are the stages and whose blued hand points at the current step, sweeping while a run is
active; large in the pipeline page header, small in every pipeline row. Raises from the beaten
hand: hairlines at one device pixel (centre-rail reference setting); stable colour meanings for
states (orienteering map); vast unprinted space and one headline per screen (factory sleeve).
seed:d4cda442c82a5dd2

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the
verdict, DESIGN.md, and every shipping raster carrying its provenance.
