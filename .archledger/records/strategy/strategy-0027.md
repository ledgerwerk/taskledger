---
schema_version: 4
id: strategy-0027
type: strategy_item
title: Policy-based lifecycle gate decisions
status: proposed
section: solution_strategy
order: 40
drivers: testable gate logic; user only actions enforced
constraints: PolicyContext is gathered explicitly; no I/O in policy functions
related_adrs: adr-0048
body_format: markdown
kind: strategy
version: 4
---

## Strategy

All lifecycle transitions are validated through pure functions in `taskledger/domain/policies.py` that return `Decision` objects (`allowed`, `code`, `message`, `exit_code`). Policies have no I/O — they receive `PolicyContext` (task, lock, run) and return a decision. This makes gate logic fully testable without file system setup.

## Trade-offs

- Policy functions must receive all context explicitly (no lazy loading from storage).
- Very testable: `test_domain_policies.py` and `test_lifecycle_policies.py` cover the full decision surface.
- Services must gather the right context before calling policies.
