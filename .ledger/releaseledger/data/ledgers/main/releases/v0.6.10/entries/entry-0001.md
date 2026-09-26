---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.10
kind: changed
summary:
  Improved proposed-plan revision safety with preflight checks, non-overwriting
  exports, and run-aware recovery guidance
status: accepted
audience: null
scopes: []
source_refs:
  - git:869a5edc327702408a0f5fe83f30e8b46203b780
paths:
  - README.md
  - docs/command_contract.md
  - docs/usage.md
  - skills/taskledger/SKILL.md
  - taskledger/cli.py
  - taskledger/cli_plan.py
  - taskledger/domain/policies.py
  - taskledger/services/navigation.py
  - taskledger/services/next_action_payload.py
  - taskledger/services/plan_editing.py
  - taskledger/services/plan_review.py
  - taskledger/services/planning_flow.py
  - taskledger/services/run_store.py
  - taskledger/services/task_repair.py
  - taskledger/services/tasks.py
  - tests/test_docs_and_skill.py
  - tests/test_plan_input_cli.py
  - tests/test_plan_revision_workflow.py
  - tests/test_service_boundaries.py
  - tests/test_taskledger_v2_cli.py
issues: []
prs: []
sources:
  - git:869a5edc327702408a0f5fe83f30e8b46203b780
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---
