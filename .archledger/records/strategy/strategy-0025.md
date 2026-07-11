---
schema_version: 4
id: strategy-0025
type: strategy_item
title: Markdown/YAML front matter as canonical records
status: proposed
section: solution_strategy
order: 20
drivers: human readable state; git diffable records; no database dependency
constraints:
  strict front matter validation; ledgercore front matter parsing; storage
  layout v3
related_adrs: adr-0046 adr-0050
body_format: markdown
kind: strategy
version: 4
---

## Strategy

Each persistent record (task, plan, run, lock, handoff, event, etc.) is stored as a `.md` file with YAML front matter for structured metadata and a Markdown body for free-form content. This format is human-readable, Git-diffable, and editable without taskledger. The front matter serialization is handled by `taskledger/storage/frontmatter.py`.

## Trade-offs

- Slower to parse than JSON or SQLite for large datasets.
- State is transparent and version-controllable — a core design goal.
- Schema evolution requires careful front matter validation (`_require_contract`, `_string_value`, etc.).
