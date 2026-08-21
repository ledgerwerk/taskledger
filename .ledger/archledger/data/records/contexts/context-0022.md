---
schema_version: 4
id: context-0022
type: context_interface
title: CI systems
status: accepted
section: context_and_scope
order: 30
context_kind: ci
partner: CI runner
inputs:
- status
- doctor
- validate
- validate status
- export
- snapshot
- trace
- next-action
outputs:
- json_envelopes exit_codes archive_files snapshot_directories
channels:
- ci_pipeline_invocations deterministic_exit_codes
body_format: markdown
kind: context
version: 7
---

CI runners invoke taskledger commands in automated pipelines. Key interactions: `status --json`, `doctor`, `validate`, `validate status`, `export`, `snapshot`, `trace`, `next-action`. CI relies on deterministic exit codes to gate pipeline stages.
