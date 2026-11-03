---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.7.6
kind: added
summary: Added recovery for interrupted validation runs while preserving existing
  checks and command evidence
status: accepted
audience: null
scopes: []
source_refs:
- git:072fcf2f66663369540ca4a38026f4027b1aabee
paths:
- taskledger/cli_validate.py
- taskledger/services/validation_flow.py
- taskledger/services/run_recovery.py
- taskledger/services/navigation.py
- tests/test_validation_lock_recovery.py
issues: []
prs: []
sources:
- git:072fcf2f66663369540ca4a38026f4027b1aabee
contributors:
- '@holgern'
breaking: false
internal: false
order: 1
---
