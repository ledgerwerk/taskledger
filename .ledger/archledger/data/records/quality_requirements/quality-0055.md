---
schema_version: 4
id: quality-0055
type: quality_requirement
title: Lifecycle gate correctness
status: proposed
section: quality_requirements
order: 40
category: reliability
source: ''
measure: ''
scenarios: []
body_format: markdown
kind: quality
version: 2
---

## Requirement

Every stage transition must pass through policy gates. Invalid transitions must fail with specific error codes and messages. User-only actions (approval, waivers) must be enforced.

## Measurement

- `tests/test_domain_policies.py` covers all policy decision functions.
- `tests/test_lifecycle_policies.py` covers stage transition rules.
- `tests/test_plan_approval_contract.py` covers user-only approval semantics and gate rejection paths.
- `tests/test_plan_input.py` and `tests/test_plan_input_cli.py` cover the editable plan input preflight parser and CLI surface.
