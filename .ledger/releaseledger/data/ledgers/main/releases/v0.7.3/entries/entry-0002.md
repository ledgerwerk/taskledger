---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 2
entry_id: entry-0002
release_version: v0.7.3
kind: fixed
summary: Fixed dangling active-task references with explicit reviewed recovery
status: accepted
audience: null
scopes: []
source_refs: []
paths:
- taskledger/services/active_task_recovery.py
- taskledger/services/doctor.py
issues: []
prs: []
sources:
- tl:task-0036
contributors: []
breaking: false
internal: false
order: 2
---
Doctor diagnoses damaged references independently of strict identity scanning; clearing a proven missing pointer or rebinding to a verified UUID preserves backup, history, and audit evidence.
