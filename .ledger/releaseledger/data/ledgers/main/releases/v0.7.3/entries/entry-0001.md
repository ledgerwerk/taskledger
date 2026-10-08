---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 2
entry_id: entry-0001
release_version: v0.7.3
kind: fixed
summary: Fixed bulk allocation repair with reviewed transactional rollback and audit
  recovery
status: accepted
audience: null
scopes: []
source_refs:
- tl:task-0036
paths:
- taskledger/services/allocation_recovery.py
- taskledger/api/repair.py
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 1
---
Preflight all selected physical sources together, journal the filesystem transaction, and provide fingerprinted rollback or audit replay after interruption.
