---
schema_version: 4
id: quality-0053
type: quality_requirement
title: CLI exit code contract stability
status: proposed
section: quality_requirements
order: 20
category: reliability
source: ""
measure: ""
scenarios: []
body_format: markdown
kind: quality
version: 2
---

## Requirement

Exit codes must remain stable across versions. Agents and CI pipelines depend on specific codes (0, 2, 3, 4, 5, 6, 7) for automation.

## Measurement

- `tests/test_cli_command_contract.py` verifies exit codes for all command paths.
- `tests/test_json_contracts.py` verifies exit codes alongside JSON output shapes.
- The exit code taxonomy is defined in `taskledger/domain/states.py` and `taskledger/errors.py`.
