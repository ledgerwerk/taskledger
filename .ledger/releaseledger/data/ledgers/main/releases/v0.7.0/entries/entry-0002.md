---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: v0.7.0
kind: added
summary: Added UUIDv7 task identities with deterministic migration for legacy bundles
  and relationship-safe import/export
status: accepted
audience: null
scopes: []
source_refs:
- git:1d340258f86769df45d474e7e9139467fe5305a9
paths:
- taskledger/ids.py
- taskledger/storage/task_identity.py
- taskledger/storage/task_directory_migration.py
- taskledger/exchange.py
- taskledger/domain/task.py
- docs/usage.md
- tests/test_task_identity.py
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 2
---
