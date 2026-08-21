---
schema_version: 4
id: block-0031
type: black_box
title: API Layer
status: proposed
section: building_block_view
level: 1
parent: block-0029
order: 20
interfaces: []
location: []
fulfilled_requirements: []
risks: []
tags: []
body_format: markdown
kind: block
version: 2
---

Stable Python function wrappers under `taskledger/api/` that mirror the CLI surface for programmatic use. Each module (tasks, plans, handoff, locks, task runs, sync, reviews, search, etc.) exposes functions that accept workspace paths and return dictionaries matching the JSON output shape. The API layer calls Services directly.
