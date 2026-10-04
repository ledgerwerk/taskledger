---
schema_version: 4
id: strategy-0026
type: strategy_item
title: JSON indexes as rebuildable derived caches
status: proposed
section: solution_strategy
order: 30
drivers:
  - fast list and query operations
  - canonical records remain source of truth
constraints:
  - summary index rebuildable on miss
  - reindex after out of band changes
related_adrs:
  - adr-0047
body_format: markdown
kind: strategy
version: 6
---

## Strategy

The task sidecar summary index is a derived cache stored in the configured rebuildable indexes mount, not alongside canonical task data. It is keyed by stable UUID identity and rebuilt from canonical Markdown records by `taskledger reindex`; human-readable task aliases remain available in the read models. Per-task sidecar writes update the summary through `update_sidecar_summary` in `taskledger/storage/sidecar_index.py`. `taskledger doctor indexes` checks for staleness.

## Trade-offs

- Avoids the complexity of a query engine on front matter files.
- Indexes can become stale if writes bypass taskledger (for example manual edits). `taskledger doctor` and `reindex` address this.
- The summary index is a JSON document with a schema version and an `object_type` field; it is rebuildable from canonical records.
