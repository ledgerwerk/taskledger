---
schema_version: 4
id: glossary-0067
type: glossary_term
title: Acceptance Criterion
status: proposed
section: glossary
order: 70
term: Acceptance Criterion
definition: A testable condition that gates task completion during validation.
body_format: markdown
kind: glossary
version: 1
---

A testable condition that gates task completion. Defined in the accepted plan as part of acceptance criteria. During validation, each criterion is checked (pass/fail/warn/not_run). Mandatory criteria must pass for validation to succeed. Persisted as `AcceptanceCriterion` in `taskledger/domain/sidecars.py`.
