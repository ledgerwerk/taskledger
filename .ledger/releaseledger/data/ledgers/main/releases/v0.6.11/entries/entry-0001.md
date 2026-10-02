---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.11
kind: added
summary: Added dry-run garbage collection and repairs for stale artifacts, orphan
  locks, and incomplete task allocations
status: accepted
audience: null
scopes: []
source_refs:
- git:2ac30782ca367ee550e075db75185f5dd001c25a
paths:
- docs/command_contract.md
- taskledger/api/maintenance.py
- taskledger/api/repair.py
- taskledger/cli.py
- taskledger/cli_maintenance.py
- taskledger/command_inventory.py
- taskledger/services/doctor.py
- taskledger/services/lock_inventory.py
- taskledger/services/maintenance.py
- taskledger/storage/task_ids.py
- tests/test_maintenance_gc.py
- tests/test_recovery_repairs.py
issues: []
prs: []
sources:
- git:2ac30782ca367ee550e075db75185f5dd001c25a
contributors:
- '@holgern'
breaking: false
internal: false
order: 1
---
