---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: v0.6.11
kind: changed
summary: Improved task listings and health checks with indexed summaries, path-bound
  reads, and incremental derived-index updates
status: accepted
audience: null
scopes: []
source_refs: []
paths:
- taskledger/services/doctor_checks/artifact_checks.py
- taskledger/services/doctor_checks/task_checks.py
- taskledger/services/planning_flow.py
- taskledger/services/task_lifecycle.py
- taskledger/services/tasks.py
- taskledger/services/usage.py
- taskledger/storage/indexes.py
- taskledger/storage/sidecar_index.py
- taskledger/storage/task_index.py
- taskledger/storage/task_store.py
- taskledger/timing.py
- tests/test_indexes.py
- tests/test_performance_caching.py
issues: []
prs: []
sources:
- git:2ac30782ca367ee550e075db75185f5dd001c25a
contributors:
- '@holgern'
breaking: false
internal: false
order: 2
---
