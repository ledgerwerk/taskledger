---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.4
kind: added
summary:
  Added separate runtime and log storage mounts and closed uninitialized projects
  against legacy storage creation
status: accepted
audience: null
scopes: []
source_refs:
  - git:6a11769c822b83be5a1a901549ea5e7de8bc8699
paths:
  - taskledger/storage/ledgercore_backend.py
  - taskledger/storage/project_context.py
  - taskledger/storage/paths.py
  - taskledger/storage/task_store.py
  - taskledger/storage/init.py
  - taskledger/api/storage.py
  - taskledger/cli_storage.py
  - tests/test_canonical_project_boundary.py
  - tests/test_taskledger_storage_commands_v3.py
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 1
---
