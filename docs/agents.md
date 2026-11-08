# MaC agents

Four agents turn the company's Confluence knowledge base into a reviewed pipeline, a guide, and
code. **Every agent's output is text that a person reviews** (a pull request or a Confluence
page), and the rules that matter are enforced by code, not by the prompt. None of them is in the
runner's execution path. All use Nemotron on NVIDIA NIM (`mac/llm.py`, `NVIDIA_API_KEY`).

| Command | Agent | Output |
|---|---|---|
| `mise run mac ingest` | Knowledge graph (`mac/graph.py`) | `.mac/graph.json` |
| `mise run mac plan "Migrate ClaimsAdjudicationService to AWS" [--pr]` | Planner (`mac/planner.py`) | `migration.yaml`; with `--pr`, a PR into `MaC-aroni/mac-migrations` |
| `mise run mac guide <spec>` | Guide writer (`mac/guide.py`) | A cited page tree in Confluence |
| `mise run mac codegen <spec> <step> [--pr]` | Code writer (`mac/codegen.py`) | The step's code; with `--pr`, a PR into the step's repo |

All of them take `--knowledge demo-data/confluence` (the default). Once
`publish-knowledge` has run, citations link to the Confluence pages.

## Grounding (`mac/sources.py`)

Every section of every knowledge page has a stable id, `<page id>#<heading slug>`, for example
`data-migration#converting-the-data`.

## Knowledge graph

One LLM call per page extracts services, MCP tools, repos, teams, approvers, policies,
standards and their relations, as JSON. Code keeps a fact only if it has a known type and cites
real sections of that page, merges duplicates across pages, and links relations across pages.
Everything dropped is reported.

## Planner

The LLM writes `migration.yaml` from the goal, the relevant part of the graph and the cited
docs. **Code checks it:**
- schema and `mac validate`
- every step and approval has `sources`, and each one is a real section
- only repos and approvers the graph knows are used

Every problem goes back to the LLM to fix, for up to 4 attempts. The PR body lists the
approvals, steps and linked sources, and says how many attempts it took.

## Guide writer

The page tree:
- `Migration guide: <service>` (it links the Tech Risk design page)
- `Approvals`
- one page per stage
- `Setting it up from scratch`

Each page gets numbered sources: `migration.yaml`'s facts plus the most relevant sections,
always including the ones its steps cite. **Code requires a citation on every paragraph and
bullet**, each pointing at a source the page was given. A page that fails is retried twice
with the problems listed; after that, ungrounded text is removed and the page says how much.
Citations render as numbered links, followed by a Sources list. Re-running updates the same
pages.

## Code writer

Only for steps the engineers marked `codegen: llm` in the reviewed spec; anything else is
refused. Code throws out any file:
- outside the step's folder (`run.path` for Terraform, otherwise the step's own entrypoints)
- with a `..` escape, or that's a provider lock file
- that's a test, CI, CODEOWNERS or `.env` file
- over 100 KB, or beyond 10 files

The PR lists what was thrown out. The repo's own CI and review rules still apply.
