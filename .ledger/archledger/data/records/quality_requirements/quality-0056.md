---
schema_version: 4
id: quality-0056
type: quality_requirement
title: Export/import round-trip fidelity
status: proposed
section: quality_requirements
order: 50
category: reliability
source: ''
measure: ''
scenarios: []
body_format: markdown
kind: quality
version: 2
---

## Requirement

Export and import must preserve all taskledger state exactly. Importing an archive into a fresh workspace must reproduce the original state including tasks, plans, runs, locks, events, handoffs, code reviews, the sidecar summary index, and active task selection.

## Measurement

- Export/import tests verify round-trip fidelity, including `tests/test_taskledger_v2_exchange.py`.
- `tests/test_task_markdown_export.py` covers Markdown export round-trip.
- Active task state must survive export/import; the ledger code and active task ref are persisted in the archive manifest.
