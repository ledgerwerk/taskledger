---
schema_version: 4
id: glossary-0070
type: glossary_term
title: Stage
status: proposed
section: glossary
order: 100
term: Stage
definition:
  A position in the task lifecycle state machine (draft, planning, plan_review,
  approved, etc.).
body_format: markdown
kind: glossary
version: 1
---

A position in the task lifecycle: draft, planning, plan_review, approved, implementing, implemented, validating, done, failed_validation, cancelled. Active stages (planning, implementing, validating) require a matching running run and a visible lock. Transitions are governed by `ALLOWED_STAGE_TRANSITIONS` in `taskledger/domain/states.py`.
