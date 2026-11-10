---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 2
entry_id: entry-0001
release_version: v0.7.7
kind: fixed
summary: Fixed cross-PC initialization to preserve project identity and safely rebuild
  local indexes caches
status: accepted
audience: null
scopes: []
source_refs:
- tl:task-0042
paths:
- taskledger/storage/init.py
- taskledger/storage/index_cache.py
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 1
---
Re-running taskledger init now prepares missing machine-local runtime and log state before recovering the disposable indexes cache. Durable project identity and task numbering are preserved, while persistent and foreign storage bindings remain protected.
