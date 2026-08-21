---
schema_version: 4
id: concept-0041
type: concept
title: JSON output envelope contract
status: proposed
section: cross_cutting_concepts
order: 20
applies_to: []
body_format: markdown
kind: concept
version: 2
---

When `--json` is passed, every CLI command emits a JSON envelope: `{"ok": bool, "command": str, "result_type": str, "result": ..., "events": [...], "warnings": [...]}`. On error, the envelope includes an `error` object with `code`, `message`, `details`, and `remediation` fields. This shape is a public API contract tested by `tests/test_json_contracts.py`. Exit codes map deterministically to error categories and are part of the public contract.
