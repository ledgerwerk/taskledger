---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.5
kind: changed
summary:
  Changed workspace snapshot validation to track added and deleted project
  files and reject unstable snapshot baselines
status: accepted
audience: null
scopes: []
source_refs:
  - git:0c7434861cd0326e498453d3396e4e8cfecf052e
paths:
  - taskledger/services/implementation_flow.py
  - taskledger/services/workspace_snapshot.py
  - tests/test_validation_git_snapshot_recovery.py
  - tests/test_workspace_snapshot.py
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 1
---
