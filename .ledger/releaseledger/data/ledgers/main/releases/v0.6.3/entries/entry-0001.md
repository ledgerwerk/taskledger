---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.3
kind: changed
summary:
  Improved managed commands to preserve child arguments, working directories,
  output, and execution context
status: accepted
audience: null
scopes: []
source_refs:
  - git:713acfa2be8891f88d889121dd769656443947f3
paths:
  - taskledger/cli.py
  - taskledger/cli_common.py
  - taskledger/cli_implement.py
  - taskledger/cli_plan.py
  - taskledger/services/agent_logging.py
  - taskledger/services/command_runner.py
  - taskledger/services/implementation_flow.py
  - tests/test_agent_command_logging.py
  - tests/test_implementation_checks.py
  - docs/command_contract.md
  - docs/full_task_cycle.md
  - docs/usage.md
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 1
---

Planning and implementation command results and managed command logs now expose the child working directory and captured stdout/stderr. Human mode emits captured streams, while JSON mode keeps them in the result envelope.
