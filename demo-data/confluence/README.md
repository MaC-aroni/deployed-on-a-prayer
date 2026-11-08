# Demo Confluence knowledge base

The internal engineering docs of **Prayerwell Health**, a *fictional* US health plan invented
for the MaC hackathon demo. They are written to match exactly what's built (the runner, the
four demo repos, the approvals), so an LLM that reads them can derive the demo pipeline.

`mise run mac publish-knowledge demo-data/confluence` publishes them to Confluence as one page
tree, keeping the tree from each page's `parent`.

Each file is one page: YAML front matter, then a Markdown body. Use only headings, paragraphs,
bullet or numbered lists, **bold** and `code`, which is what MaC's converter supports.

```
---
id: platform-landing-zone        # stable id; citations and the knowledge graph use it
title: "Platform: AWS Landing Zone Standards"
parent: handbook                 # id of the parent page; omit for the root page
owner: platform-engineering
labels: [platform, aws, standard]
---
```
