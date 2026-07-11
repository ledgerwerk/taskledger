---
schema_version: 4
id: block-0034
type: black_box
title: Storage Layer
status: proposed
section: building_block_view
level: 1
parent: block-0029
order: 50
interfaces: []
location: []
fulfilled_requirements: []
risks: []
tags: []
body_format: markdown
kind: block
version: 2
---

File system persistence for canonical records. Storage layout keeps each task in `.taskledger/ledgers/<ledger_ref>/tasks/<task-id>/`, with independently addressable sidecars including plans, runs, locks, todos, questions, changes, checks, handoffs, links, and code reviews. Ledger-level collections hold events, introductions, releases, and rebuildable indexes. A `task_sidecars.json` summary index is maintained as a derived cache; per-task sidecar writes call `update_sidecar_summary` from `taskledger/storage/sidecar_index.py` so the read path does not need a full rescan. Atomic write primitives, YAML I/O, front matter parsing, and ref parsing are delegated to `ledgercore`. Action and event logging is enabled by default and can be disabled in project config. Project config edits use structured TOML handling rather than ad hoc text replacement.
