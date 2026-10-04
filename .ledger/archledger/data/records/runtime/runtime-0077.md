---
schema_version: 4
id: runtime-0077
type: runtime_scenario
title: Migration, reindex, and doctor interaction
status: accepted
section: runtime_view
order: 80
participants:
  - taskledger doctor
  - taskledger migrate
  - taskledger reindex
trigger:
  Developer upgrades taskledger and runs taskledger doctor which reports storage
  version mismatch
result:
  Storage layout is upgraded to TASKLEDGER_STORAGE_LAYOUT_VERSION with audit;
  indexes are rebuilt; doctor passes cleanly.
body_format: markdown
kind: runtime
version: 6
---

**Trigger**: A developer updates a project using layout-5 numeric task bundles and a mutating Taskledger command needs canonical layout 6.

**Flow**:

1. Before mutation, storage checks the project layout and inventories task identities. Read-only commands continue to read without migrating.
2. The migration maps legacy task aliases to deterministic UUIDv7 identities while preserving ordering, ordinal gaps, and reserved or incomplete allocations.
3. The migration verifies that the source is safe to transform; mixed layouts, active locks, and unresolved repository conflicts block automatic migration rather than being guessed through.
4. Canonical task records and sidecars are moved into UUID-named task bundle directories with recovery information retained.
5. Layout metadata is advanced to version 6 and UUID-keyed derived indexes are rebuilt.
6. `doctor` verifies canonical records, indexes, locks, and runs after migration.

**Result**: The first mutation uses UUIDv7 task directories while numeric task aliases remain available to users. Read-only access does not change the legacy layout.

**Key source**: `taskledger/storage/task_directory_migration.py`, `taskledger/storage/task_identity.py`, `taskledger/storage/task_store.py`, `taskledger/services/doctor.py`.
