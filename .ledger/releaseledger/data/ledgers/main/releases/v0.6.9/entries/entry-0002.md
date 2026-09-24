---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: v0.6.9
kind: changed
summary:
  Changed implement resume to no-op with unchanged lock and run IDs when the
  current execution owns the active run
status: accepted
audience: null
scopes: []
source_refs: []
paths:
  - taskledger/services/implementation_flow.py
  - taskledger/cli_implement.py
issues: []
prs: []
sources:
  - git:b3fdec92ed65c2808f2707eceeffa7aa1b35a446
contributors:
  - "@holgern"
breaking: false
internal: false
order: 2
---
