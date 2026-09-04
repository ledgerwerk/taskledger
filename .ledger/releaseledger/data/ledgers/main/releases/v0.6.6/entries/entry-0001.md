---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.6
kind: added
summary:
  Added managed validation command evidence with durable output capture and
  explicit probe-failure classification
status: accepted
audience: null
scopes: []
source_refs:
  - git:307d68a1cbbcc1639bd18affdeefb69064af3a6e
paths:
  - API.md
  - README.md
  - docs/api.md
  - docs/command_contract.md
  - docs/full_task_cycle.md
  - docs/public_surface.md
  - docs/service_boundary_whitelist.md
  - docs/usage.md
  - skills/taskledger/SKILL.md
  - taskledger/api/task_runs.py
  - taskledger/cli_validate.py
  - taskledger/command_inventory.py
  - taskledger/services/agent_transcripts.py
  - taskledger/services/handoff.py
  - taskledger/services/tasks.py
  - taskledger/services/validation_flow.py
  - taskledger/services/worker_context.py
  - taskledger/services/workflow_guidance.py
  - tests/test_agent_command_logging.py
  - tests/test_command_inventory.py
  - tests/test_docs_and_skill.py
  - tests/test_service_boundaries.py
  - tests/test_validation_command.py
  - tests/test_worker_pipeline_context.py
  - tests/test_workflow_guidance.py
issues: []
prs: []
sources:
  - git:307d68a1cbbcc1639bd18affdeefb69064af3a6e
contributors: []
breaking: false
internal: false
order: 1
---
