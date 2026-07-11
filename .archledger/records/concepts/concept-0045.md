---
schema_version: 4
id: concept-0045
type: concept
title: Exit code taxonomy
status: proposed
section: cross_cutting_concepts
order: 60
applies_to: []
body_format: markdown
kind: concept
version: 2
---

Stable exit codes for CLI and error classification: 0 (success), 1 (generic failure), 2 (bad input), 3 (workflow rejection - invalid transition, approval required, dependency blocked), 4 (lock conflict - stale lock requires break), 5 (not found or no active task), 6 (storage error or data integrity), 7 (validation failed). Defined in `taskledger/domain/states.py` and `taskledger/errors.py`. Agents and CI pipelines rely on specific codes for automation.
