---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.7.8
kind: added
summary: Added cross-ledger task-directory migration with drift diagnostics and safe
  reconciliation
status: accepted
audience: null
scopes: []
source_refs:
- git:f96f3935070c01542893ab76c012d025dd09d839
paths:
- docs/service_boundary_whitelist.md
- taskledger/errors.py
- taskledger/services/doctor.py
- taskledger/storage/layout_migration.py
- taskledger/storage/migrations.py
- taskledger/storage/project_context.py
- taskledger/storage/task_directory_migration.py
- taskledger/storage/task_identity.py
- taskledger/storage/task_layout.py
- taskledger/storage/task_store.py
- tests/test_canonical_internal_layout_migration.py
- tests/test_canonical_layout_migration.py
- tests/test_service_boundaries.py
- tests/test_task_directory_migration.py
- tests/test_task_identity.py
- tests/test_task_layout.py
issues: []
prs: []
sources:
- git:f96f3935070c01542893ab76c012d025dd09d839
contributors:
- '@holgern'
breaking: false
internal: false
order: 1
---
