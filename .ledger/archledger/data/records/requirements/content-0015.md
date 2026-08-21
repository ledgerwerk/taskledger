---
schema_version: 4
id: content-0015
type: requirement
title: Fresh-context handoffs for agent continuation
status: proposed
section: introduction_and_goals
order: 30
source: ""
priority: must
stakeholders: []
quality_goals: []
body_format: markdown
kind: content
version: 1
---

## Requirement

Workers must be able to create self-contained context snapshots that allow a different process, agent, or human to continue work without reading the entire task history.

## Rationale

- Coding agents frequently start fresh sessions. Handoff records capture task state, plan, todos, questions, lock status, and required output so the next worker has everything needed.
- Evidence: `taskledger/domain/handoff.py` (`TaskHandoffRecord`), `taskledger/services/handoff.py` (context generation), `taskledger/services/handoff_lifecycle.py` (claim/close/transfer).
