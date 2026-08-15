---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 2
entry_id: entry-0002
release_version: v0.6.2
kind: changed
summary:
  Indexes mount is fixed to cache storage; `storage set indexes cache` is now
  an idempotent topology request and non-cache indexes storage is rejected directly
status: accepted
audience: null
scopes: []
source_refs: []
paths:
  - taskledger/api/storage.py
issues: []
prs: []
sources:
  - git:6305f28
contributors: []
breaking: false
internal: false
order: 2
---
