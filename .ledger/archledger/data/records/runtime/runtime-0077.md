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
version: 5
---

**Trigger**: Developer upgrades taskledger and runs `taskledger doctor`, which reports a storage version mismatch.

**Flow**:

1. `doctor` → Scans project config, storage layout version, task records, indexes, locks, and runs
2. Detects that storage layout version (e.g., v2) is behind current version (v3)
3. Reports diagnostic with severity, code, and repair hint
4. `migrate` → Applies storage layout migrations to upgrade records to current schema
5. Migration code in `taskledger/storage/migrations.py` handles version-to-version upgrades
6. `reindex` → Rebuilds JSON index caches from migrated canonical records
7. `doctor` → Re-run confirms all checks pass

**Result**: Storage layout is upgraded to the current version. Indexes are rebuilt. Doctor passes cleanly.

**Key source**: `taskledger/storage/migrations.py`, `taskledger/services/doctor.py`, `taskledger/services/doctor_checks/migration_checks.py`, `taskledger/domain/states.py`.
