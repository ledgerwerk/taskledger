---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.7.2
kind: added
summary: Added safe migrated-task allocation repairs with owner preservation and ambiguity
  diagnostics
status: accepted
audience: null
scopes: []
source_refs:
- git:1ad648bb0ae4c2a7bc293c7693ff7165f5fac5e9
paths:
- docs/command_contract.md
- docs/recovery_identity.md
- taskledger/api/repair.py
- taskledger/cli_repair.py
- taskledger/cli_task.py
- taskledger/services/doctor.py
- taskledger/storage/task_identity.py
- tests/test_doctor.py
- tests/test_recovery_repairs.py
- tests/test_service_boundaries.py
- tests/test_task_identity.py
issues: []
prs: []
sources:
- git:1ad648bb0ae4c2a7bc293c7693ff7165f5fac5e9
contributors:
- '@holgern'
breaking: false
internal: false
order: 1
---
