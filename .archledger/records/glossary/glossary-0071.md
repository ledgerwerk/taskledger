---
schema_version: 4
id: glossary-0071
type: glossary_term
title: Sidecar
status: proposed
section: glossary
order: 110
term: Sidecar
definition:
  A collection of related records (todos, links, plans, etc.) attached to
  a task.
body_format: markdown
kind: glossary
version: 2
---

A collection of related records attached to a task. Sidecar collections include todos, links, requirements, plans, questions, runs, changes, artifacts, handoffs, code reviews, and audit data. Each collection lives in a subdirectory of the task bundle directory. The `task_sidecars.json` summary index aggregates per-task sidecar counts and lock summaries. Defined in `taskledger/domain/sidecars.py` and `taskledger/storage/sidecar_index.py`.
