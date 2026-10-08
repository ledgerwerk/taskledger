---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 3
entry_id: entry-0003
release_version: v0.7.3
kind: fixed
summary: Fixed allocation CLI outcomes with truthful summaries, JSON errors, and exit
  codes
status: accepted
audience: null
scopes: []
source_refs: []
paths:
- taskledger/cli_repair.py
issues: []
prs: []
sources:
- tl:task-0036
contributors: []
breaking: false
internal: false
order: 3
---
Apply failures now return nonzero with truthful planned, committed, and failed counts, physical source IDs, ledger health, and rollback or audit diagnostics.
