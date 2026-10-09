---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.7.4
kind: added
summary: Added reviewed recovery for historical task identity conflicts
status: accepted
audience: null
scopes: []
source_refs:
- git:74c46b7e0c1e02d67e09f0dc7dcf42bb7fac162f
paths:
- API.md
- docs/api.md
- docs/command_contract.md
- docs/recovery_identity.md
- skills/taskledger/SKILL.md
- taskledger/api/repair.py
- taskledger/cli_repair.py
- taskledger/command_inventory.py
- taskledger/services/allocation_recovery.py
- taskledger/services/doctor.py
- taskledger/storage/task_identity.py
- tests/test_cli_command_contract.py
- tests/test_command_inventory.py
- tests/test_docs_and_skill.py
- tests/test_recovery_repairs.py
- tests/test_service_boundaries.py
issues: []
prs: []
sources:
- git:74c46b7e0c1e02d67e09f0dc7dcf42bb7fac162f
contributors:
- '@holgern'
breaking: false
internal: false
order: 1
---
Plans fingerprint claimants, quarantine, and live-owner state; apply preserves original tombstone bytes and journals rollback and audit recovery. Unverifiable tombstone retirement requires explicit operator approval.
