---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.7
kind: added
summary:
  Added configurable artifact limits with UTF-8-safe truncation across command
  evidence, archives, doctor, and Git sync
status: accepted
audience: null
scopes: []
source_refs:
  - git:562fc8796f821e312877f0c5b2aa09f5daddb138
paths:
  - README.md
  - docs/command_contract.md
  - docs/sync.md
  - docs/transfer.md
  - docs/usage.md
  - taskledger/api/config.py
  - taskledger/exchange.py
  - taskledger/services/agent_logging.py
  - taskledger/services/change_tracking.py
  - taskledger/services/doctor.py
  - taskledger/services/doctor_checks/artifact_checks.py
  - taskledger/services/git_sync.py
  - taskledger/services/implementation_flow.py
  - taskledger/services/tasks.py
  - taskledger/services/validation_flow.py
  - taskledger/storage/agent_logs.py
  - taskledger/storage/artifact_policy.py
  - taskledger/storage/project_config.py
  - tests/test_agent_command_logging.py
  - tests/test_artifact_policy.py
  - tests/test_config_cli.py
  - tests/test_doctor.py
  - tests/test_project_root_config.py
  - tests/test_sync_git.py
  - tests/test_taskledger_v2_exchange.py
  - tests/test_validation_command.py
issues: []
prs: []
sources:
  - git:562fc8796f821e312877f0c5b2aa09f5daddb138
contributors: []
breaking: false
internal: false
order: 1
---
