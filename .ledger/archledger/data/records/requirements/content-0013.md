---
schema_version: 4
id: content-0013
type: requirement
title: Durable task lifecycle state
status: proposed
section: introduction_and_goals
order: 10
source: ''
priority: must
stakeholders: []
quality_goals: []
body_format: markdown
kind: content
version: 1
---

## Requirement

Every task, plan, run, lock, todo, and validation check must be persisted to the file system in a format that survives process crashes, agent context switches, and machine restarts.

## Rationale

- Agents and humans lose in-memory state frequently. Durable persistence is the foundation for all other guarantees.
- Evidence: `taskledger/storage/task_store.py` (canonical v2 bundle layout), `taskledger/storage/atomic.py` (atomic writes), `taskledger/storage/frontmatter.py` (YAML front matter serialization).
