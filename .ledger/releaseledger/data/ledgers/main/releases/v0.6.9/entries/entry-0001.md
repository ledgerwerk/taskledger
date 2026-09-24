---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.9
kind: added
summary:
  Added active_current_execution lock classification based on harness session
  or host-process identity, not actor name
status: accepted
audience: null
scopes: []
source_refs:
  - git:b3fdec92ed65c2808f2707eceeffa7aa1b35a446
paths:
  - taskledger/services/lock_diagnostics.py
issues: []
prs: []
sources:
  - git:b3fdec92ed65c2808f2707eceeffa7aa1b35a446
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---
