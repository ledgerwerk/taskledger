---
schema_version: 4
id: glossary-0063
type: glossary_term
title: Run
status: proposed
section: glossary
order: 30
term: Run
definition:
  A record of an active work session (planning, implementation, or validation)
  paired with a lock.
body_format: markdown
kind: glossary
version: 1
---

A record of an active work session. Runs have a type (planning/implementation/validation), status (running/paused/finished/passed/failed/blocked/aborted), and are paired with a lock. Created when a stage starts, finished when the stage completes. Persisted as `TaskRunRecord` in `taskledger/domain/run.py`.
