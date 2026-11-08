---
name: "MaC · Migration as Code"
description: "A migration console as a fine instrument: silvered ground, graphite ink, one blued-steel hand, a trace of gilt."
colors:
  ground: "#ecebe7"
  surface: "#f6f5f2"
  surface-2: "#e9e7e1"
  ink: "#1c1e24"
  ink-hover: "#2a2d36"
  muted: "#5d6170"
  faint: "#5f6478"
  hairline: "rgba(28, 30, 36, 0.12)"
  hairline-strong: "rgba(28, 30, 36, 0.22)"
  ink-wash: "rgba(28, 30, 36, 0.035)"
  selection-wash: "#e6e3f3"
  blued-steel: "#2b4bb7"
  blued-steel-wash: "rgba(43, 75, 183, 0.1)"
  gilt: "#b89a5a"
  gilt-deep: "#9a7d3f"
  gilt-wash: "rgba(184, 154, 90, 0.16)"
  bad: "#b3263f"
  bad-wash: "rgba(179, 38, 63, 0.1)"
  warn: "#b7791f"
  log-ground: "#1c1e24"
  log-ink: "#e6e4dc"
  night-ground: "#15161a"
  night-surface: "#1b1c21"
  night-surface-2: "#232429"
  night-ink: "#ebe9e2"
  night-muted: "#a1a4b0"
  night-faint: "#868b9b"
  night-hairline: "rgba(255, 255, 255, 0.1)"
  night-hairline-strong: "rgba(255, 255, 255, 0.2)"
  night-blued-steel: "#8fa6ff"
  night-gilt: "#c9ad6c"
  night-bad: "#e2667c"
  night-warn: "#e0a84a"
typography:
  display:
    fontFamily: "Bodoni Moda, Didot, Bodoni 72, Georgia, serif"
    fontSize: "48px"
    fontWeight: 400
    lineHeight: 0.95
    letterSpacing: "-0.01em"
    fontFeature: "lnum, tnum"
  headline:
    fontFamily: "Source Serif 4, Iowan Old Style, Palatino Linotype, Georgia, serif"
    fontSize: "36px"
    fontWeight: 500
    lineHeight: 1.1
    letterSpacing: "-0.012em"
    fontFeature: "kern, liga"
  title:
    fontFamily: "Source Serif 4, Iowan Old Style, Palatino Linotype, Georgia, serif"
    fontSize: "18px"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-0.012em"
  body:
    fontFamily: "Albert Sans, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    letterSpacing: "0.002em"
  meta:
    fontFamily: "Albert Sans, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
  label:
    fontFamily: "Albert Sans, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "11px"
    fontWeight: 500
    letterSpacing: "0.14em"
  stage:
    fontFamily: "Albert Sans, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "10.5px"
    fontWeight: 500
    letterSpacing: "0.1em"
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "12.5px"
    fontWeight: 400
rounded:
  hairline: "1px"
  xs: "2px"
  pill: "999px"
  round: "50%"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  2xl: "28px"
  gutter: "32px"
  3xl: "48px"
components:
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
    padding: "0 16px"
    height: "38px"
  button-ghost-hover:
    backgroundColor: "{colors.ink-wash}"
    textColor: "{colors.ink}"
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ground}"
    rounded: "{rounded.xs}"
    padding: "0 16px"
    height: "38px"
  button-primary-hover:
    backgroundColor: "{colors.ink-hover}"
    textColor: "{colors.ground}"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.bad}"
    rounded: "{rounded.xs}"
    padding: "0 16px"
    height: "38px"
  row-action:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.xs}"
    height: "34px"
  row-action-hover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ground}"
  cancel-run:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.xs}"
    height: "34px"
    width: "140px"
  cancel-run-armed:
    backgroundColor: "transparent"
    textColor: "{colors.bad}"
    width: "140px"
  pill:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.hairline}"
    padding: "3px 9px"
  pill-bad:
    textColor: "{colors.bad}"
  pill-warn:
    textColor: "{colors.warn}"
  pill-steel:
    textColor: "{colors.blued-steel}"
  pill-grey:
    textColor: "{colors.muted}"
  stage-chip:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    typography: "{typography.stage}"
    padding: "0"
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.hairline}"
    padding: "8px 10px"
    height: "44px"
  nav-item-hover:
    backgroundColor: "{colors.ink-wash}"
    textColor: "{colors.ink}"
  nav-item-active:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
  nav-item-primary:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    height: "58px"
  nav-count:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.display}"
    rounded: "{rounded.round}"
    size: "26px"
  nav-count-new:
    backgroundColor: "{colors.gilt}"
    textColor: "#ffffff"
  table-row:
    backgroundColor: "transparent"
    padding: "12px 32px"
    height: "72px"
  table-row-hover:
    backgroundColor: "{colors.ink-wash}"
  table-row-selected:
    backgroundColor: "{colors.selection-wash}"
  table-head:
    textColor: "{colors.muted}"
    typography: "{typography.label}"
    padding: "18px 32px 12px"
  card:
    backgroundColor: "transparent"
    rounded: "{rounded.xs}"
    padding: "24px 26px"
  dag-node:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
    height: "76px"
  dag-node-hover:
    backgroundColor: "{colors.ink-wash}"
  dag-node-selected:
    backgroundColor: "{colors.blued-steel-wash}"
  filter:
    backgroundColor: "transparent"
    rounded: "{rounded.xs}"
    height: "40px"
    width: "440px"
  tab:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    padding: "12px 0"
  tab-active:
    textColor: "{colors.ink}"
  metric:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    padding: "6px 0"
  log:
    backgroundColor: "{colors.log-ground}"
    textColor: "{colors.log-ink}"
    typography: "{typography.mono}"
  brand-mark:
    backgroundColor: "transparent"
    rounded: "{rounded.round}"
    size: "40px"
    padding: "4px"
---

# Design System: MaC · Migration as Code

## Overview

**Creative North Star: "The Haute-Horlogerie Dial"**

The console is a fine instrument you glance at and trust. A plain silvered ground carries
graphite ink, hairline rules at one device pixel, and nothing else: no filled panels, no shadows,
no texture. One blued-steel accent does every job that means "live" (the running hand, the
selected row, the link, the focused field), and a trace of gilt sits on the single primary action,
the brand ring and the active mark on the rail. The dark theme is the same ink logic inverted onto
a graphite ground (the night dial); gilt and steel lighten, nothing else changes.

Type divides by job. A Didone (Bodoni Moda) sets figures only: metric values, counts, tallies. A
sturdy serif (Source Serif 4 at 500) sets every word that is a title. A humanist sans (Albert Sans)
sets everything you operate, and JetBrains Mono sets identifiers. Density is generous: 32px row
gutters, rows of at least 72px (a title line and up to two meta lines), one headline per screen,
and a statement row of figures where a dashboard would have put tiles.

Motion is almost absent on purpose. Every entrance animation the base sheet owned is cancelled.
The one authored moment is the stage gauge: its hand turns in 600ms when the runner moves, and a
thin gilt seconds hand sweeps once every six seconds while a run is active. Hover and colour
changes settle in 180ms.

**Key Characteristics:**
- Hairlines instead of surfaces; panels are transparent on the ground.
- One gilt primary action per screen; everything else is ink on hairline.
- Bodoni Moda for figures only; Source Serif 4 for titles; Albert Sans for UI; JetBrains Mono for ids.
- Stable state colours: blued steel = active/selected/link, ink = succeeded, red = failed, faint = cancelled/undone/skipped, amber = breakpoint/awaiting review.
- One authored motion (the gauge hand and sweep); the rest settles in 180ms or does not move.
- Generous rhythm: 72px rows, 32px gutters, a 288px rail, one headline per screen.

## Colors

A silvered ground, graphite ink, one cool accent and one warm metal, each with a strict job.

### Primary
- **Blued Steel** (`blued-steel`): the one working accent. The gauge hand and its centre dot, the
  current index mark, running and waiting ring tints, selected DAG nodes (with `blued-steel-wash`
  behind), lit graph edges, links, the toggle when on, focus outlines, the caret, and the focused
  border of the filter and composer. The `tone-green` pill borrows it: there is no green in the
  system, "ok" is steel. Night value is `night-blued-steel`.

### Secondary
- **Gilt** (`gilt`): a trace of warm metal, never a surface. The 1px ring around the primary button
  and the gilt icon inside it, the inset ring on the brand mark, agent avatars and the gate logo,
  the 1px left rule on the active rail item, the gauge's sweeping seconds hand, the text selection
  highlight (`gilt-wash`), and the AI mark (`gilt-deep` by day, `gilt` by night). The only gilt fill
  anywhere is the `new` nav count. Night value is `night-gilt`.

### Neutral
- **Silvered Ground** (`ground`): the page, the sign-in gate, and the text colour of ink-filled
  buttons. Plain; the earlier sunburst texture is removed.
- **Surface** (`surface`): the gauge ring fill and the few remaining boxed surfaces (toast, menu,
  confirm, banner, search, filter chrome); cards, frames, tables, the inspector and the metrics
  row are transparent.
- **Surface 2** (`surface-2`): the user's chat bubble and the toggle track.
- **Graphite Ink** (`ink`): all primary text, headings, the primary button fill, the active
  segment, succeeded gauge marks and rings, the active tab's underline. `ink-hover` is the primary
  button on hover.
- **Muted** (`muted`): labels, captions, column heads, stage chips, nav items at rest, default
  gauge index marks, metric captions.
- **Faint** (`faint`): rail hints, zero counts, cancelled/undone/skipped states. Raised from the
  base sheet so hints read on the ground.
- **Hairline** (`hairline`) and **Hairline Strong** (`hairline-strong`): the rules. Hairline for
  row separators, card and frame edges, the rail edge, the topbar, column heads, chips and inputs.
  Hairline-strong for the statement's top rule, button and pill borders, DAG node edges, the
  gauge ring and the menu.
- **Ink Wash** (`ink-wash`): the only hover fill, 3.5% ink on rows, nav items, nodes, buttons.
- **Selection Wash** (`selection-wash`): the selected table row.
- **Log Ground / Log Ink** (`log-ground`, `log-ink`): the one dark surface by day, for logs,
  traces and YAML.

### Status
- **Bad** (`bad`): failed and rollback-failed marks (2px, the one thick stroke), failed rings,
  cut edges, danger buttons, the armed cancel, the red pill, the broke column's wash (`bad-wash`).
- **Warn** (`warn`): breakpoint nodes (1px left rule), the review bar awaiting a decision, the
  amber pill.

### Named Rules
**The One Gilt Rule.** Gilt appears on the single primary action, the brand and agent rings, the
active rail mark, the sweep and the selection highlight. It is never a surface and never a fill,
except the `new` count.

**The Stable Meaning Rule.** Blued steel means active, selected or a link; ink means succeeded;
red means failed; faint means cancelled, undone or skipped; amber means a breakpoint or a pending
review. A colour never changes meaning between the gauge, the pill, the node and the edge.

**The Night Inversion Rule.** The dark theme inverts the ink logic onto `night-ground`; steel
lifts to `night-blued-steel`, gilt to `night-gilt`, red to `night-bad`. Hairline alphas move to
white. No other rule changes between themes.

## Typography

**Display Font:** Bodoni Moda (with Didot, Bodoni 72, Georgia) · loaded at opsz 6..96, wght 400 and 500
**Title Font:** Source Serif 4 (with Iowan Old Style, Palatino Linotype, Georgia) · opsz 8..60, wght 500 and 600
**Body Font:** Albert Sans (with system-ui) · wght 400, 500, 600
**Label/Mono Font:** JetBrains Mono (with ui-monospace, Menlo) · wght 400, 500

**Character:** A high-contrast Didone gives the numbers the authority of an engraved dial, but it
was hard to read as words, so the titles moved to a sturdy transitional serif at medium weight.
The sans beneath is quiet and even; the mono marks anything a machine named.

### Hierarchy
- **Display** (400, 48px, 0.95, lining tabular figures): metric values in the statement row.
  The same face at 14px sets nav counts, tab counts and DAG column counts. Never a word.
- **Headline** (500, 36px, 1.1, -0.012em): the one page title per screen (`Pipelines`, `Runs`,
  the gate title at 40px). The run header is 30px / 1.15 with the run id in mono at 0.72em. Drops
  to 32px under 820px.
- **Title** (500, 18px, 1.2): pipeline row titles, card heads, the brand word (19px), the metric
  noun (20px, set on the figure's baseline), inspector and empty-state h2. Row titles drop to
  17px under 820px and clip with an ellipsis at 16px under 1100px.
- **Body** (400, 14px, 0.002em): everything operated. Page intros are 14px / 1.6 at a 64ch max.
  Nav items 14px / 500, primary nav items 15px, node names 15px / 500, row titles outside the
  pipelines table 16px / 500.
- **Meta** (400, 12.5px): row and run meta, metric captions, crumbs (0.02em). Node subtitles 12px.
- **Label** (500, 11px, 0.14em, uppercase): table heads, column heads, nav section names, the
  live-state word, the gate subtitle. Pills are 11.5px at 0.04em; the brand's second line is 9.5px
  at 0.12em; inspector keys are 10.5px at 0.08em uppercase.
- **Stage** (500, 10.5px, 0.1em, uppercase, muted): stage names in rows, bare, no chip chrome.
- **Mono**: ids, commit refs, repository names, logs; chips of the `chip`/`meta-chip` kind.

### Named Rules
**The Figures-Only Didone Rule.** Bodoni Moda sets numbers and never a word. If a string contains
letters it is set in Source Serif 4 or Albert Sans.

**The One Headline Rule.** One 36px headline per screen. Everything else on the page is title
size (18–20px) or smaller.

**The Small-Caps Stage Rule.** Stage names are bare uppercase sans at 10.5px with 0.1em tracking,
muted, with no border, fill or padding. They read as engraving, not as chips.

## Layout

A fixed rail and a wide, quiet content column. The sidebar is 288px (64px collapsed), padded
28px 20px 24px, with a hairline right edge and a transparent background. Rail sections are 11px
tracked labels with 22px above and 10px below; items are at least 44px tall with 8px vertical
padding so their faint hints wrap rather than truncate; the two primary items are at least 58px
and ruled above and below. The theme toggle (44px) sits on a hairline above the footer, which
names the signed-in engineer (an 18px ink circle with their initial and `@login`) or reads "Local
session" with a dot.

The topbar is 56px with a hairline beneath and 12.5px crumbs. Content is padded 8px 48px 72px to
a 1560px maximum; the page head sits 36px below the topbar and 44px above the statement.

The **statement** replaces metric tiles: an `auto-fit` grid of columns at least 240px wide with a
48px column gap, a strong rule above and a hairline below, padded 22px 0 20px. Each metric is a
48px figure and a 20px serif noun on one baseline, 14px apart, with a 12.5px caption on the line
below; no borders, no fills, no dividers between columns.

**Tables** are ruled, not boxed: the table frame is a hairline at 2px radius with no padding;
rows are at least 72px, padded 12px 32px with a 28px column gap and a hairline on top; the header
row is 18px 32px 12px with no rule above. Named column templates: pipelines
`200px / 2fr / 170px / 1fr / auto`; runs `170px / 1fr / 1.3fr / 150px / 100px` (plus an `auto`
actions column on the all-runs list); services `170px / 1fr / 1.4fr / 150px / auto`.

**The pipeline graph** sits in a hairline frame padded 32px 36px, with 272px columns 52px apart,
column heads ruled beneath with 10px padding, 16px between 76px nodes, and 1px 2px 2px 2px of
canvas padding so no card's hairline is clipped. The inspector grid is `1fr / 340px` with a
hairline between; the run header is a flex row with the gauge at the right, 28px gaps, 28px
below and a hairline beneath.

**Breakpoints** (all `max-width`):
- **1400px**: the pipelines table drops its stages column (`190px / 1fr / 170px / auto`).
- **1280px**: the runs table drops its fifth column (`160px / 1fr / 1fr / 110px`).
- **1100px**: the pipelines table drops runs (`170px / 1fr / auto`); row titles clip with an
  ellipsis at 16px.
- **820px**: the statement stacks, with hairlines between rows instead of beside them; content
  gutters fall to 20px with 48px below; the headline is 32px; the pipeline row becomes title plus
  status (`1fr / auto`), hiding runs, stages and the header; the toolbar wraps and the primary
  button loses its left margin.

Spacing steps observed: 4, 8, 12, 14, 16, 20, 24, 28, 32, 48.

## Elevation & Depth

There are no shadows. `--shadow` and `--inset` are `none`, and every `box-shadow` the base sheet
set on cards, nodes, toasts, filters and pills is cancelled. Depth is conveyed by hairlines, by a
3.5% ink wash on hover, by the selection wash on a chosen row, and by the one genuinely dark
surface, the log block. On displays at 2dppx and above, every hairline border is drawn at 0.5px,
the active tab's underline at 0.5px, the gauge ring and default marks at 0.75 (1.25 for the
current or failed mark), and graph edges at 0.75, so a rule is one device pixel wherever it can be.

The only `box-shadow` values that remain are 1px inset rings standing in for borders on circles
(the brand mark, agent avatars, the gate logo, the pending status dot), the 1px inset line under
an active tab, and the 1px gilt ring around the primary button.

### Named Rules
**The Hairline Rule.** A rule is one device pixel: 1px, 0.5px at 2dppx. Nothing is thicker; the
only 2px stroke in the system is a failed gauge mark.

**The Transparent Panel Rule.** Cards, frames, tables, the inspector, the metrics row, the chat
main and the knowledge page have no background. They are hairline outlines on the ground.

## Shapes

Corners are nearly square. Frames, buttons, inputs, nodes, cards and the segmented control sit at
2px; pills, chips, nav items and skeletons at 1px; the active-tab underline and log blocks at 0.
Circles are reserved for marks and counts: the 40px brand mark, agent avatars, the gate logo, the
26px nav count, icon buttons, the footer avatar and the gauge ring. The toggle is a 999px track.
The user's chat bubble is 2px on three corners and 12px at the bottom left.

Status is often drawn as a single 1px left rule rather than a fill: amber on a breakpoint node and
the review bar, steel on an approved review or a passing probe, red on a rejected review or a
failing probe.

## Components

### Buttons
Quiet outlines by default; one ink-and-gilt action per screen.
- **Shape:** near-square (2px), 38px tall, 0 16px padding, 500 weight, 0.01em tracking.
- **Ghost / Secondary / GitHub:** transparent with a `hairline-strong` border and ink text; on
  hover an ink wash fills and the border turns ink.
- **Primary:** ink fill, ground-coloured text, a 1px gilt ring outside a ground-coloured border,
  and any icon inside it set in gilt. Hover darkens to `ink-hover`. In the dark theme the fill is
  the night ink and the text the night ground. The service card's primary action is 44px.
- **Danger:** transparent with red text and a red border.
- **Row action:** 34px, muted text, `hairline` border, inside a row button; when the row is
  hovered the action inverts to an ink fill with ground text.
- **Doors** (route cards): 38px hairline outlines; learn/confirm/review doors in steel.
- **Segmented:** a hairline group; the active segment is an ink fill with ground text.
- **Icon button:** circular, ink wash on hover.
- **Focus:** a 1px steel outline inset 1px on buttons, row buttons, nav items and tabs;
  elsewhere a 1px steel outline 3px outside the element.

### Pills (status)
- **Style:** transparent, 1px radius, `hairline-strong` border, ink text, 11.5px at 0.04em,
  3px 9px padding; the large variant is 12px at 5px 12px. The base sheet's status dot precedes
  the text.
- **Tones:** red border and text for failed; amber for waiting; steel for running, blue and
  violet; the "green" tone is steel-bordered ink; grey is a `hairline` border with muted text.

### Stage chips
- **Style:** no border, no fill, no padding; 10.5px uppercase sans at 0.1em in muted; 4px 14px gaps
  so a row of six wraps onto two lines inside the 72px row.
- **Other chips** (`chip`, `meta-chip`, `chat-chip`): transparent, hairline border, 1px radius,
  muted, 11px; model names are set in steel.

### Tables
- **Frame:** hairline at 2px, no padding, transparent.
- **Rows:** at least 72px, 12px 32px padding, hairline top, 180ms background settle; ink wash on
  hover, selection wash when selected. Row titles 16px / 500 (18px serif in the pipelines table);
  meta 12.5px with 2px 12px gaps and no-wrap spans; a run's reason clamps to two lines.
- **Pipelines row:** a 56px gauge at the left, the status pill beside it, title and meta, three
  runs on one line that wraps rather than truncates, the stage chips, then "Open".
- **Empty row:** 48px 32px, muted.

### Cards / Containers
- **Corner Style:** 2px.
- **Background:** transparent (cards, DAG frame, inspector, report, chat main, knowledge page,
  fix and endpoint cards). Toasts, menus, confirms and banners keep `surface`.
- **Shadow Strategy:** none; see Elevation & Depth.
- **Border:** hairline; menus use `hairline-strong`.
- **Internal Padding:** 24px 26px; 24px between cards; the card foot is ruled above with 16px
  padding and 6px margin; card heads are 18px serif.

### Inputs / Fields
- **Style:** transparent, hairline, 2px radius; the filter is 40px tall and at most 440px wide,
  the search 40px with a hairline `kbd`.
- **Focus:** the border turns steel; no glow. The caret is steel; selected text is gilt-washed.
- **Composer:** the chat composer follows the same hairline-to-steel rule.

### Navigation
- **Rail:** transparent, 288px, hairline right edge. Section labels 11px / 0.14em / muted. Items
  are at least 44px, 1px radius, 14px / 500 muted text with a faint 400 hint that wraps at 1.25
  line height; hover is an ink wash and ink text. The active item is ink text with a 1px gilt rule
  on its left edge, 6px short of top and bottom, on a transparent ground. Primary items are at
  least 58px, 15px, ruled above (and the last one below), ink-washed when active or hovered.
- **Counts:** 26px circles with a `hairline-strong` ring and a 14px Bodoni figure; `new` counts
  fill gilt with white; zero counts are faint.
- **Brand:** a 40px circle with a 1px gilt inset ring and 4px padding around the mark-only logo;
  "MaC" in 19px serif and "MIGRATION AS CODE" at 9.5px / 0.12em.
- **Footer:** the theme toggle (44px, hairline above, ink wash on hover) and the session line at
  12px muted: an 18px ink circle carrying the engineer's initial in ground colour next to
  `@login`, or "Local session" beside a dot.
- **Topbar:** 56px, hairline beneath, crumbs at 12.5px / 0.02em.
- **Tabs:** a hairline rail with 28px gaps; tabs are 13.5px muted at 12px 0 padding, ink on hover,
  and the active tab carries a 1px ink inset underline (1px left line in the vertical variant).
  Tab counts are hairline rings with Bodoni figures.
- **Collapsed:** the rail folds to 64px.

### DAG node cards
- **Node:** transparent, `hairline-strong` border, 2px, 76px tall; name 15px / 500, subtitle 12px
  muted (steel for agent nodes). Hover is an ink wash with an ink border; selected is a steel
  border on a steel wash; running is a steel border; a breakpoint is a 1px amber left rule; broke
  is a red border and the broke column's card sits on a red wash. Border, background and opacity
  settle in 180ms.
- **Columns:** 272px, a ruled 11px tracked head with the count at 11px / 0.1em (red in the broke
  column), 52px between columns.
- **Edges:** `hair` strokes (0.75 at 2dppx); lit edges steel, cut edges red.

### Logs
- **Style:** `log-ground` with `log-ink` text, 0 radius; the one dark block on the day dial.

### The Stage Gauge (signature)
A slim dial whose index marks are the pipeline's stages and whose hand points at the stage the run
is in. Pure SVG, default 56px, with no library.
- **Geometry:** the ring's radius is half the size minus 3; the marks span 300° starting at −150°,
  leaving a gap at the bottom like a power reserve; each mark is 14% of the size long, 20% for
  the current stage. The ring fills `surface` with a `hairline-strong` stroke.
- **Marks:** muted by default. Succeeded and approved marks are ink; failed and rollback-failed
  are red at 2px; running, waiting, blocked and the current stage are steel at 1.5; rolled back,
  skipped and cancelled are faint.
- **Hand:** steel, 1.5 wide, round caps, from 8% below centre to 20% inside the ring, with a
  centre dot at 4.5% of the size. It turns to the current stage in 600ms on
  `cubic-bezier(0.2, 0.8, 0.2, 1)`. The current stage is the first active stage, else the first
  failed one, else the last completed or rolled-back one.
- **Sweep:** while a run is active a 1px gilt seconds hand at 0.9 opacity rotates once every 6s,
  linear, forever; it stops under `prefers-reduced-motion`.
- **Run tint (list rows):** when per-stage states are unknown the marks stay neutral and the ring
  says how the run ended: red for failed or rollback-failed (1.5 wide), steel for running,
  waiting or rolling back, ink for succeeded, faint for undone or cancelled. A failed run whose
  stage is unknown shows no hand.
- **Title:** `<stage> · <status>`, or "not started"; for a failed run the title names the failed
  step. At 2dppx the ring and default marks are 0.75, the current and failed marks 1.25.

### Two-press cancel (row control)
Cancels a run from a list row without leaving it. Because the row is itself a button, the control
is a `span` with `role="button"`, `tabIndex` 0, `aria-pressed` when armed and `aria-disabled` while
busy, answering Enter and Space.
- **Rest:** a 34px ghost row action, muted, 140px wide (fixed so the longer armed label does not
  move the control), an octagon-x icon at 13px and the word "Cancel".
- **Armed:** the danger outline (red text and border) reading "Stop and undo?", disarming itself
  after 5s; the title explains that the runner stops the run and undoes everything it did.
- **Busy:** "Cancelling…" at 0.6 opacity with pointer events off.
- **Error:** the server's message as written, red, right-aligned beneath the control, at most 220px
  wide. Shown only for runs in `running` or `waiting`.

## Do's and Don'ts

### Do:
- **Do** draw every rule as a hairline: 1px, 0.5px at 2dppx, in `hairline` or `hairline-strong`.
- **Do** keep panels transparent on the ground; outline them, never fill them.
- **Do** set figures in Bodoni Moda and words in Source Serif 4 (titles) or Albert Sans (UI).
- **Do** give each screen one primary action: an ink fill with a 1px gilt ring and a gilt icon.
- **Do** keep table rows at 72px or taller, padded 12px 32px, with a title line and up to two meta lines.
- **Do** present page figures as one ruled statement, figure and noun on one baseline, stacked with rules between under 820px.
- **Do** use the stage gauge wherever a run's progress is shown: large in the run header, small in every row.
- **Do** keep state colours stable across gauge, pill, node and edge.

### Don't:
- **Don't** add shadows, glows or entrance animations; nothing moves but the gauge hand and sweep.
- **Don't** fill pills or chips; status is an outline and stages are bare small caps.
- **Don't** set a word in Bodoni Moda or a headline larger than 36px.
- **Don't** thicken a border past a hairline; the only 2px stroke is a failed gauge mark.
- **Don't** reintroduce the sunburst or any ground texture; both themes are plain.
- **Don't** use gilt as a surface or on anything but the primary action, the brand and agent rings, the active rail mark and the sweep.
- **Don't** introduce a green; the "ok" tone is blued steel.
