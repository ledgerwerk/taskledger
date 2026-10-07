---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.7.1
kind: changed
summary: Improved task identity recovery with transactional repairs and UUID relationship
  diagnostics
status: accepted
audience: null
scopes: []
source_refs:
- git:c9d75c2df1b9bd73c9c2220f76d6de7eb0d5f79a
paths:
- README.md
- docs/command_contract.md
- docs/index.md
- docs/recovery_identity.md
- docs/service_boundary_whitelist.md
- docs/usage.md
- skills/taskledger/SKILL.md
- taskledger/api/repair.py
- taskledger/cli_repair.py
- taskledger/cli_task.py
- taskledger/command_inventory.py
- taskledger/services/doctor.py
- taskledger/services/lock_inventory.py
- taskledger/services/tasks.py
- taskledger/storage/task_directory_migration.py
- taskledger/storage/task_identity.py
- taskledger/storage/task_ids.py
- taskledger/storage/task_store.py
- tests/test_cli_command_contract.py
- tests/test_docs_and_skill.py
- tests/test_doctor.py
- tests/test_recovery_repairs.py
- tests/test_service_boundaries.py
- tests/test_task_directory_migration.py
- tests/test_task_identity.py
- tests/test_uuid_relationships.py
issues: []
prs: []
sources:
- git:c9d75c2df1b9bd73c9c2220f76d6de7eb0d5f79a
contributors:
- '@holgern'
breaking: false
internal: false
order: 1
---
