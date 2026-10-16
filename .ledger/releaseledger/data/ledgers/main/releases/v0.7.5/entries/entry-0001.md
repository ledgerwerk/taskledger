---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 3
entry_id: entry-0001
release_version: v0.7.5
kind: fixed
summary: Prevented task identity conflicts from blocking safe recovery
status: accepted
audience: null
scopes: []
source_refs:
- tl:task-0037
- git:19b9a8423f97d906932eb23a21d232fe8d46f69a
paths:
- taskledger/services/lock_inventory.py
- taskledger/storage/task_store.py
- taskledger/storage/physical_runs.py
- taskledger/services/allocation_recovery.py
- taskledger/services/allocation_protection.py
- taskledger/services/doctor.py
- taskledger/services/doctor_checks/task_checks.py
- taskledger/api/repair.py
- taskledger/cli_repair.py
- tests/test_doctor.py
- tests/test_recovery_repairs.py
- tests/test_service_boundaries.py
- tests/test_taskledger_migration_v3.py
- docs/command_contract.md
- docs/recovery_identity.md
- docs/usage.md
- skills/taskledger/SKILL.md
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 1
---
Separated lock file health, lease state, and identity binding. Doctor now inspects run ownership by physical task bundle, while allocation repair reports active-pointer, lock, and physically owned running-run blockers before apply. Shadowed allocation quarantine remains transactional and requires a fresh reviewed plan after pointer rebinding.
