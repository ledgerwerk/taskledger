---
schema_version: 4
id: glossary-0065
type: glossary_term
title: Handoff
status: proposed
section: glossary
order: 50
term: Handoff
definition:
  A context transfer record enabling a different actor to continue work
  from where the previous actor left off.
body_format: markdown
kind: glossary
version: 1
---

A context transfer record that allows a different actor or process to continue work. Contains a generated context body (task state, plan, todos, questions, lock info) and a lock policy (none/retain/release/transfer). Lifecycle: open → claimed → closed/cancelled. Persisted as `TaskHandoffRecord` in `taskledger/domain/handoff.py`.
