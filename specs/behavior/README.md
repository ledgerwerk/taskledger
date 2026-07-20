# Behavior specifications

This directory contains the retained Taskledger behavior corpus. SpecMason is
the specification and traceability tool, and pytest remains the executable
verification layer.

## Workspace

- `features/` contains current Gherkin behavior specifications.
- `mappings/` contains pytest mapping policy.
- `evidence/` contains execution evidence.
- `reports/specmason/` contains generated SpecMason reports.
- `../requirements/manifest.json` is the normative ReqLedger-shaped authority.

Every retained scenario has one `@req-REQ-NNNN` tag and one
`@ac-AC-NNNN` tag. Mapped pytest tests use comments such as:

```python
# specmason: req=REQ-0001 ac=AC-0001
```

Tests that are internal, redundant, obsolete, or outside the retained behavior
boundary are listed with reviewable reasons in
`mappings/intentional-unmapped.json`.

## Verification

Run these checks from the repository root:

```bash
specmason check --config specmason.toml --requirements requirements/manifest.json --json
specmason discover-pytest --config specmason.toml --json
specmason mappings --config specmason.toml --summary --json
specmason coverage --config specmason.toml --requirements requirements/manifest.json --view both --show gaps --json
specmason review --config specmason.toml --requirements requirements/manifest.json --json
pytest -q
```

Install SpecMason from its project distribution before running these commands.
The Taskledger package does not package or import SpecMason.

## Feature inventory

- `specs/behavior/features/active_task/active-task.feature`: 8 scenarios
- `specs/behavior/features/actor_harness_state/actor-harness-state.feature`: 29 scenarios
- `specs/behavior/features/actor_resolution/actor-resolution.feature`: 14 scenarios
- `specs/behavior/features/agent_command_logging/agent-command-logging.feature`: 12 scenarios
- `specs/behavior/features/agent_session_protocol/agent-session-protocol.feature`: 18 scenarios
- `specs/behavior/features/atomic_fast_io/atomic-fast-io.feature`: 1 scenarios
- `specs/behavior/features/cli_command_contract/cli-command-contract.feature`: 8 scenarios
- `specs/behavior/features/cli_import_resilience/cli-import-resilience.feature`: 3 scenarios
- `specs/behavior/features/code_reviews/code-reviews.feature`: 8 scenarios
- `specs/behavior/features/command_example_linter/command-example-linter.feature`: 3 scenarios
- `specs/behavior/features/command_inventory/command-inventory.feature`: 12 scenarios
- `specs/behavior/features/command_runner/command-runner.feature`: 2 scenarios
- `specs/behavior/features/compact_mutation_output/compact-mutation-output.feature`: 7 scenarios
- `specs/behavior/features/config_cli/config-cli.feature`: 10 scenarios
- `specs/behavior/features/delta_remaining_contracts/delta-remaining-contracts.feature`: 20 scenarios
- `specs/behavior/features/docs_and_skill/docs-and-skill.feature`: 19 scenarios
- `specs/behavior/features/doctor/doctor.feature`: 30 scenarios
- `specs/behavior/features/domain_policies/domain-policies.feature`: 71 scenarios
- `specs/behavior/features/event_logging_config/event-logging-config.feature`: 6 scenarios
- `specs/behavior/features/events/events.feature`: 3 scenarios
- `specs/behavior/features/file_link_snapshots/file-link-snapshots.feature`: 9 scenarios
- `specs/behavior/features/find_code_clones_script/find-code-clones-script.feature`: 1 scenarios
- `specs/behavior/features/handoff_lifecycle/handoff-lifecycle.feature`: 12 scenarios
- `specs/behavior/features/help_subprocess/help-subprocess.feature`: 3 scenarios
- `specs/behavior/features/implementation_change_scan/implementation-change-scan.feature`: 5 scenarios
- `specs/behavior/features/implementation_checks/implementation-checks.feature`: 8 scenarios
- `specs/behavior/features/json_contracts/json-contracts.feature`: 10 scenarios
- `specs/behavior/features/legacy_cleanup_contracts/legacy-cleanup-contracts.feature`: 3 scenarios
- `specs/behavior/features/lifecycle_policies/lifecycle-policies.feature`: 2 scenarios
- `specs/behavior/features/lock_diagnostics/lock-diagnostics.feature`: 20 scenarios
- `specs/behavior/features/locks_audit/locks-audit.feature`: 2 scenarios
- `specs/behavior/features/models_v1_schema/models-v1-schema.feature`: 3 scenarios
- `specs/behavior/features/monitor/monitor.feature`: 11 scenarios
- `specs/behavior/features/next_action_expired_lock/next-action-expired-lock.feature`: 3 scenarios
- `specs/behavior/features/no_log_feature/no-log-feature.feature`: 24 scenarios
- `specs/behavior/features/plan_approval_contract/plan-approval-contract.feature`: 9 scenarios
- `specs/behavior/features/plan_lint/plan-lint.feature`: 26 scenarios
- `specs/behavior/features/plan_review/plan-review.feature`: 10 scenarios
- `specs/behavior/features/plan_revision_workflow/plan-revision-workflow.feature`: 8 scenarios
- `specs/behavior/features/plan_todo_materialization/plan-todo-materialization.feature`: 1 scenarios
- `specs/behavior/features/project_root_config/project-root-config.feature`: 27 scenarios
- `specs/behavior/features/question_add_many/question-add-many.feature`: 4 scenarios
- `specs/behavior/features/question_filter_answers/question-filter-answers.feature`: 7 scenarios
- `specs/behavior/features/question_plan_regeneration/question-plan-regeneration.feature`: 13 scenarios
- `specs/behavior/features/ready_work/ready-work.feature`: 3 scenarios
- `specs/behavior/features/release_changelog/release-changelog.feature`: 14 scenarios
- `specs/behavior/features/search/search.feature`: 3 scenarios
- `specs/behavior/features/service_boundaries/service-boundaries.feature`: 7 scenarios
- `specs/behavior/features/services_dashboard/services-dashboard.feature`: 10 scenarios
- `specs/behavior/features/sidecar_collections/sidecar-collections.feature`: 1 scenarios
- `specs/behavior/features/storage_bundle_layout/storage-bundle-layout.feature`: 10 scenarios
- `specs/behavior/features/storage_common/storage-common.feature`: 4 scenarios
- `specs/behavior/features/storage_init/storage-init.feature`: 3 scenarios
- `specs/behavior/features/storage_migration/storage-migration.feature`: 34 scenarios
- `specs/behavior/features/storage_repos/storage-repos.feature`: 12 scenarios
- `specs/behavior/features/storage_sync/storage-sync.feature`: 10 scenarios
- `specs/behavior/features/sync_git/sync-git.feature`: 9 scenarios
- `specs/behavior/features/task_archive/archive.feature`: 5 scenarios
- `specs/behavior/features/task_events/events.feature`: 6 scenarios
- `specs/behavior/features/task_markdown_export/markdown-export.feature`: 19 scenarios
- `specs/behavior/features/task_report/report.feature`: 17 scenarios
- `specs/behavior/features/taskledger_branch_scoped_ledgers/taskledger-branch-scoped-ledgers.feature`: 5 scenarios
- `specs/behavior/features/taskledger_cli_api_parity/taskledger-cli-api-parity.feature`: 4 scenarios
- `specs/behavior/features/taskledger_v2_cli/taskledger-v2-cli.feature`: 42 scenarios
- `specs/behavior/features/taskledger_v2_exchange/taskledger-v2-exchange.feature`: 25 scenarios
- `specs/behavior/features/tasks_service_static/tasks-service-static.feature`: 1 scenarios
- `specs/behavior/features/todo_implementation_gate/todo-implementation-gate.feature`: 21 scenarios
- `specs/behavior/features/trace/trace.feature`: 1 scenarios
- `specs/behavior/features/tree_command/tree-command.feature`: 18 scenarios
- `specs/behavior/features/usage_cli/usage-cli.feature`: 5 scenarios
- `specs/behavior/features/worker_pipeline_cli/worker-pipeline-cli.feature`: 11 scenarios
- `specs/behavior/features/worker_pipeline_config/worker-pipeline-config.feature`: 6 scenarios
- `specs/behavior/features/worker_pipeline_context/worker-pipeline-context.feature`: 4 scenarios
- `specs/behavior/features/worker_pipeline_handoff/worker-pipeline-handoff.feature`: 3 scenarios
- `specs/behavior/features/worker_pipeline_plan_template/worker-pipeline-plan-template.feature`: 4 scenarios
- `specs/behavior/features/worker_pipeline_todos/worker-pipeline-todos.feature`: 2 scenarios
- `specs/behavior/features/workflow_guidance/workflow-guidance.feature`: 6 scenarios
