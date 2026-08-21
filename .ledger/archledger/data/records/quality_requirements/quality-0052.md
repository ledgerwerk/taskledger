---
schema_version: 4
id: quality-0052
type: quality_requirement
title: 'Data integrity: atomic writes and front matter validation'
status: proposed
section: quality_requirements
order: 10
category: reliability
source: ''
measure: ''
scenarios: []
body_format: markdown
kind: quality
version: 2
---

## Requirement

No partial or corrupt records should ever be readable. Atomic writes from `ledgercore` (`os.replace` after temp file and fsync) prevent partial files. Front matter validation (`_require_contract`, `_string_value`, type checks) rejects malformed records on read.

## Measurement

- `tests/test_atomic_fast_io.py` covers atomic write and create semantics.
- `tests/test_storage_bundle_layout.py` covers front matter validation and corruption detection.
- `taskledger doctor` checks detect invalid front matter and lock/run inconsistencies.
