---
schema_version: 4
id: constraint-0017
type: constraint
title: File-system canonical storage with sidecar summary index
status: proposed
section: architecture_constraints
order: 20
category: technical
impact: State is file-based; query performance depends on index rebuilds.
body_format: markdown
kind: constraint
version: 3
---

All durable state is stored as Markdown files with YAML front matter in `.taskledger/`. This makes state human-readable, diffable in Git, and inspectable without taskledger. The trade-off is that query performance depends on file scanning and `task_sidecars.json` summary index rebuilding rather than a database engine. The sidecar index is maintained in place by per-task sidecar writes and rebuilt from canonical records on miss.
