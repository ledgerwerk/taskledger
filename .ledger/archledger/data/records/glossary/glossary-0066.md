---
schema_version: 4
id: glossary-0066
type: glossary_term
title: Todo
status: proposed
section: glossary
order: 60
term: Todo
definition:
  A concrete implementation step materialized from the accepted plan; gates
  implementation completion.
body_format: markdown
kind: glossary
version: 4
---

A concrete implementation step within a task. Todos are materialized from accepted plans and gate implementation completion (all mandatory todos must be done to finish implementation). Status: `open`, `active`, `done`, `blocked`, `skipped`. Persisted as `TaskTodo` in sidecar collections via `taskledger/domain/sidecars.py`. Todo writes update the `task_sidecars.json` summary index in place.
