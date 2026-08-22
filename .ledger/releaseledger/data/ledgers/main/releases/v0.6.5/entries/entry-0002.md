---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: v0.6.5
kind: added
summary:
  Added run-scoped read-only review handoffs with cross-harness claims, durable
  evidence, and snapshot-drift detection
status: accepted
audience: null
scopes: []
source_refs:
  - git:84066428f775df58774ed86e2fe92b8977165c5d
paths:
  - taskledger/api/handoff.py
  - taskledger/cli_misc.py
  - taskledger/cli_review.py
  - taskledger/domain/handoff.py
  - taskledger/domain/review.py
  - taskledger/services/actors.py
  - taskledger/services/code_review.py
  - taskledger/services/handoff_lifecycle.py
  - taskledger/services/navigation.py
  - README.md
  - skills/taskledger/SKILL.md
  - tests/test_code_reviews.py
  - tests/test_handoff_lifecycle.py
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 2
---
