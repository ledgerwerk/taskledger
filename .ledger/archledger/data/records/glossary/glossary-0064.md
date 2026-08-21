---
schema_version: 4
id: glossary-0064
type: glossary_term
title: Lock
status: proposed
section: glossary
order: 40
term: Lock
definition: A concurrency control mechanism preventing simultaneous actors on the
  same task stage.
body_format: markdown
kind: glossary
version: 1
---

A concurrency control mechanism that prevents multiple actors from working on the same task stage simultaneously. Locks have a lease timer, holder (`ActorRef`), and optional transfer history. Stale locks require explicit break flow with audit record. Persisted as `TaskLock` in `taskledger/domain/lock.py`.
