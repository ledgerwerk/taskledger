# Service boundary whitelist

This note tracks temporary static-boundary whitelist entries enforced by
`tests/test_service_boundaries.py`.

The whitelist is debt tracking, not a permanent exception list. When an item
drops below budget or is removed, update this note and the related test
constants.

## Module line budget whitelist (>2000 lines)

- `taskledger/services/tasks.py`

  - Current reason: Temporary compatibility facade while workflow services
    are extracted.
  - Target split direction: Continue reducing to a smaller compatibility
    facade and move residual helpers into focused modules.

## Current split status

Implemented in this tranche:

- `taskledger/services/planning_flow.py`
- `taskledger/services/implementation_flow.py`
- `taskledger/services/validation_flow.py`
- `taskledger/services/tasks.py` delegates plan, implement, and validate
  entrypoints to the new modules.

Remaining target: continue reducing `taskledger/services/tasks.py` to a
smaller compatibility facade and move residual helpers into focused modules.

## Function line budget whitelist (>250 lines)

- `taskledger/services/doctor_checks/task_checks.py::_scan_task_integrity_phases`

  - Current reason: Sub-phases of scan_task_integrity with per-task lock, run, and validation checks.

- `taskledger/services/doctor.py::_inspect_v2_project_phases`

  - Current reason: Project doctor phases collect independent corruption-tolerant diagnostics.

- `taskledger/cli_sync.py::register_sync_commands`

  - Current reason: Git-sync and hook commands are registered together in the
    sync group.

- `taskledger/storage/layout_migration.py::_apply_migration_phases`

  - Current reason: Migration apply logic covers file moves, UUID resolution, and config rewriting.

- `taskledger/storage/layout_migration.py::_inspect_migration_phases`

  - Current reason: Migration inspect logic covers candidate discovery, config analysis, and issue assembly.

## CLI→services import whitelist

CLI modules may import from `taskledger.services` only when listed in
`tests/test_service_boundaries.py` under `CLI_SERVICES_IMPORT_WHITELIST`.

Current sanctioned imports:

- `taskledger/cli_monitor.py:taskledger.services.dashboard` — Dashboard and view
  rendering are service-level read models.
- `taskledger/cli.py:taskledger.services.agent_logging` — Root CLI initializes
  recorder and payload/error notes.
- `taskledger/cli_project.py:taskledger.services.tree` — Tree rendering lives in
  services/tree.py.
- `taskledger/cli_monitor.py:taskledger.services.monitor` — Monitor commands
  render the terminal monitor read model.
- `taskledger/cli_navigation.py:taskledger.services.usage` — Navigation commands
  render the fresh-session usage read model.
- `taskledger/cli_actor.py:taskledger.services.actors` — Actor and harness
  resolution lives in services/actors.py.
- `taskledger/cli_common.py:taskledger.services.actors` — CLI common resolves
  actor/harness context for event metadata.
- `taskledger/cli_common.py:taskledger.services.agent_logging` — CLI common
  emits recorder task/payload/error notes.
- `taskledger/cli_implement.py:taskledger.services.agent_logging` — Implement
  command wrapper records managed-shell command failures.
- `taskledger/cli_validate.py:taskledger.services.agent_logging` — Validation
  command wrapper records managed-shell command failures.
- `taskledger/cli_repair.py:taskledger.services.doctor` — Doctor commands
  consume doctor service inspectors directly.
- `taskledger/cli_todo.py:taskledger.services.actors` — Todo updates resolve
  identity for completion metadata.
- `taskledger/cli_pipeline.py:taskledger.services.handoff` — Pipeline context
  rendering reuses handoff service payloads.
- `taskledger/cli_pipeline.py:taskledger.services.worker_pipeline` — Pipeline
  commands read the worker pipeline service overlay directly.
- `taskledger/cli_review.py:taskledger.services.actors` — Review commands resolve
  reviewer/harness context.
- `taskledger/cli_plan.py:taskledger.services.plan_editing` — Plan input path
  validation lives in services/plan_editing.py.
- `taskledger/cli_plan.py:taskledger.services.plan_lint` — Plan lint payload
  model is service-owned.
- `taskledger/cli_question.py:taskledger.services.actors` — Question commands
  resolve actor/harness context.
- `taskledger/cli_plan.py:taskledger.services.workflow_guidance` — Planning
  guidance profile read model is service-owned.
- `taskledger/cli_plan.py:taskledger.services.agent_logging` — Plan command
  wrapper records managed-shell command failures.
- `taskledger/cli_plan.py:taskledger.services.planning_flow` — Plan guidance
  marks guidance viewed via the planning flow service.
- `taskledger/cli_task.py:taskledger.services.actors` — Task record commands
  resolve completed-by actor metadata.
- `taskledger/cli_task.py:taskledger.services.agent_transcripts` — Task
  transcript rendering lives in services.

- `taskledger/cli_task.py:taskledger.services.agent_logging` — Task CLI records direct UUID show diagnostics through the agent logger.
- `taskledger/cli_task.py:taskledger.services.task_reports` — Task report
  rendering and options are service-owned.
- `taskledger/cli_task.py:taskledger.services.task_export` — Task export service
  for compiled LLM-ready Markdown.
- `taskledger/cli_task.py:taskledger.services.tasks` — Task events read model
  and lifecycle mutations.
- `taskledger/cli_trace.py:taskledger.services.trace` — Trace CLI delegates to
  the trace service.
- `taskledger/cli_migrate.py:taskledger.services.storage_migration` — Migration
  CLI delegates to the storage migration service.
- `taskledger/cli_runtime.py:taskledger.services.runtime_info` — Runtime CLI
  delegates provenance collection to the runtime service.
- `taskledger/cli_lock.py:taskledger.services.actors` — Lock commands resolve
  actor and harness context for lock changes.
- `taskledger/cli_navigation.py:taskledger.services.actors` — Navigation
  commands resolve actor/harness context for usage metadata.

## Catch-all exception whitelist (`except Exception`)

Current allowed sites are listed with reasons in
`tests/test_service_boundaries.py` under `EXCEPT_EXCEPTION_WHITELIST`. Each
catch-all key uses the stable form
`path::qualified_function:except-N`, where `N` is the ordinal of the
catch-all handler within that function. It intentionally does not use source
line numbers, so unrelated edits above an approved handler do not create
policy churn.

The reviewed resilience sites include storage validation, migration command
and hook handling, and project-config parsing boundaries listed in the test
constants.

Policy intent:

- Allow catch-all handling only in doctor/repair and resilience wrappers.
- Block new catch-all sites unless explicitly reviewed and justified.
- Require whitelist edits to be intentional and reasoned.
- Fail when a new handler is added, an approved handler disappears, or a
  function gains another catch-all handler.
