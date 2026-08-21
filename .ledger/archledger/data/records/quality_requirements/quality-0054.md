---
schema_version: 4
id: quality-0054
type: quality_requirement
title: JSON envelope output stability
status: proposed
section: quality_requirements
order: 30
category: reliability
source: ''
measure: ''
scenarios: []
body_format: markdown
kind: quality
version: 2
---

## Requirement

The JSON output shape (`ok`, `command`, `result_type`, `result`, `events`, `warnings`, and the error sub-envelope with `code`, `message`, `details`, `remediation`) must remain stable. Breaking changes to field names, shapes, or semantics require explicit version bumps.

## Measurement

- `tests/test_json_contracts.py` validates envelope shape and field presence for all commands.
- Error envelopes include `code`, `message`, `details`, and `remediation` fields and are exercised through `tests/test_cli_command_contract.py`.
