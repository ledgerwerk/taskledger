---
schema_version: 4
id: content-0014
type: requirement
title: Explicit lifecycle gates with user approval
status: proposed
section: introduction_and_goals
order: 20
source: ''
priority: must
stakeholders: []
quality_goals: []
body_format: markdown
kind: content
version: 1
---

## Requirement

Transitions between task lifecycle stages must pass through policy gates. Plan approval is a user-only decision. Implementation requires an accepted plan. Validation requires a finished implementation.

## Rationale

- Without gates, agents could skip review and ship unreviewed code. The lifecycle machine in `taskledger/domain/states.py` and policy decisions in `taskledger/domain/policies.py` enforce this contract.
- Evidence: `taskledger/domain/states.py` (`ALLOWED_STAGE_TRANSITIONS`), `taskledger/domain/policies.py` (`Decision`, `can_start_planning`, `plan_approve_decision`).
