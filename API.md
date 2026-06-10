# taskledger API contract

This repository exposes a task-first public API. The supported modules are:

- `taskledger.errors`
- `taskledger.api.project`
- `taskledger.api.tasks`
- `taskledger.api.plans`
- `taskledger.api.questions`
- `taskledger.api.task_runs`
- `taskledger.api.reviews`
- `taskledger.api.introductions`
- `taskledger.api.locks`
- `taskledger.api.handoff`
- `taskledger.api.releases`
- `taskledger.api.storage`
- `taskledger.api.sync`
- `taskledger.api.search`
- `taskledger.api.bdd`

## Import boundary

Consumers must not import from:

- `taskledger.storage`
- `taskledger.storage.*`
- `taskledger.services`
- `taskledger.domain`
- `taskledger.search`

If a capability is missing, add it under `taskledger.api.*`.

## Global rule

All workspace-bound public entrypoints accept `workspace_root: Path` as the first
argument.

## Canonical errors

```python
from taskledger.errors import (
    TaskledgerError,
    LaunchError,
    InvalidPromptError,
    UnsupportedAgentError,
    AgentNotInstalledError,
)
```

## Public modules

### `taskledger.api.project`

- `init_project`
- `project_status`
- `project_status_summary`
- `project_doctor`
- `project_export`
- `project_import`
- `project_export_archive`
- `project_import_archive`
- `project_snapshot`
- `project_tree`

### `taskledger.api.tasks`

- `create_task`
- `record_completed_task`
- `show_active_task`
- `activate_task`
- `deactivate_task`
- `clear_active_task`
- `resolve_active_task`
- `list_task_summaries`
- `show_task`
- `edit_task`
- `cancel_task`
- `uncancel_task`
- `close_task`
- `archive_task`
- `unarchive_task`
- `create_follow_up_task`
- `list_archived_task_summaries`
- `add_requirement`
- `remove_requirement`
- `waive_requirement`
- `add_file_link`
- `file_status`
- `remove_file_link`
- `list_file_links`
- `refresh_file_baseline`
- `add_todo`
- `set_todo_done`
- `show_todo`
- `todo_status`
- `next_todo`
- `task_dossier`
- `render_task_report`
- `TaskReportOptions`
- `export_task_markdown`
- `TaskMarkdownExportOptions`
- `next_action`
- `can_perform`
- `reindex`
- `repair_task_record`
- `repair_orphaned_planning_run`
- `repair_planning_command_changes`

### `taskledger.api.plans`

- `start_planning`
- `propose_plan`
- `plan_template`
- `upsert_plan`
- `PlanReviewOptions`
- `build_plan_review_payload`
- `render_plan_review`
- `export_plan`
- `amend_plan`
- `regenerate_plan_from_answers`
- `materialize_plan_todos`
- `list_plan_versions`
- `show_plan`
- `diff_plan`
- `lint_plan`
- `plan_guidance`
- `approve_plan`
- `reject_plan`
- `revise_plan`
- `run_planning_command`

Planning guidance API example:

```python
from pathlib import Path

from taskledger.api.plans import plan_guidance

payload = plan_guidance(Path.cwd(), "task-0001")
# payload includes: kind, task_id, has_project_guidance, guidance, profile, question_policy
```

### `taskledger.api.questions`

- `add_question`
- `add_questions`
- `list_questions`
- `list_open_questions`
- `answer_question`
- `answer_questions`
- `dismiss_question`
- `question_status`

### `taskledger.api.task_runs`

- `start_implementation`
- `restart_implementation`
- `resume_implementation`
- `log_implementation`
- `add_implementation_deviation`
- `add_implementation_artifact`
- `add_change`
- `scan_changes`
- `run_implementation_command`
- `finish_implementation`
- `show_task_run`
- `start_validation`
- `add_validation_check`
- `validation_status`
- `waive_criterion`
- `finish_validation`
- `list_runs`
- `list_changes`

### `taskledger.api.reviews`

- `record_code_review`
- `list_code_review_records`
- `show_code_review`

### `taskledger.api.introductions`

- `create_introduction`
- `list_introductions`
- `resolve_introduction`
- `link_introduction`

### `taskledger.api.locks`

- `show_lock`
- `break_lock`
- `list_locks`
- `load_active_locks`

### `taskledger.api.handoff`

- `render_handoff`
- `create_handoff`
- `list_all_handoffs`
- `show_handoff`
- `claim_handoff_api`
- `close_handoff_api`
- `cancel_handoff_api`

Current focused-context signatures:

```python
render_handoff(
    workspace_root: Path,
    task_ref: str,
    *,
    mode: str | None = None,
    context_for: str | None = None,
    worker_step_id: str | None = None,
    scope: str | None = None,
    todo_id: str | None = None,
    focus_run_id: str | None = None,
    format_name: str = "markdown",
) -> str | dict[str, object]

create_handoff(
    workspace_root: Path,
    task_ref: str,
    *,
    mode: str | None = None,
    context_for: str | None = None,
    worker_step_id: str | None = None,
    scope: str | None = None,
    todo_id: str | None = None,
    focus_run_id: str | None = None,
    intended_actor_type: str | None = None,
    intended_actor_name: str | None = None,
    intended_harness: str | None = None,
    summary: str | None = None,
    next_action: str | None = None,
    actor: ActorRef | None = None,
    harness: HarnessRef | None = None,
) -> dict[str, object]
```

Focused handoffs store the generated Markdown context snapshot in the handoff
record body and return compact metadata, including `context_hash` and
`context_path`. When `worker_step_id` is supplied, taskledger derives the
handoff mode and context from the configured worker step, persists
`worker_step_id` in the handoff record, and includes the resolved worker-step
details in JSON context payloads.

### `taskledger.api.releases`

- `build_changelog_context`
- `list_release_records`
- `show_release`
- `tag_release`

### `taskledger.api.storage`

- `storage_where`
- `storage_move`
- `sync_preflight`
- `sync_status`
- `sync_commit`

### `taskledger.api.search`

- `search_workspace`
- `grep_workspace`
- `symbols_workspace`
- `dependencies_for_module`

### `taskledger.api.sync`

- `sync_git_init`
- `sync_git_paths`
- `sync_git_status`
- `sync_git_import_local`
- `sync_git_commit`
- `sync_git_export_local`
- `sync_git_pull`
- `sync_git_push`
- `sync_git_sync`
- `sync_git_hooks_install`
- `sync_git_hooks_status`
- `sync_git_hooks_uninstall`

### `taskledger.api.bdd`

Task-local behavior mapping APIs. These are task-local BDD/example overlay records.
Taskledger is not the canonical spec owner — canonical behavior specs live under
`specs/behavior/features/` (SpecWeave-owned).

- `bdd_init`
- `bdd_status`
- `bdd_rule_add`
- `bdd_rule_list`
- `bdd_rule_show`
- `bdd_example_add`
- `bdd_example_list`
- `bdd_example_show`
- `bdd_example_link_ac`
- `bdd_example_link_archledger`
- `bdd_example_link_automation`
- `bdd_gherkin_export`
- `bdd_export_json`
- `bdd_archledger_candidate`
- `import_bdd_report`

## CLI command groups

The public task-first CLI surface is organized around these command groups:

- `task`
- `plan`
- `question`
- `implement`
- `validate`
- `review`
- `todo`
- `intro`
- `file`
- `link`
- `require`
- `release`
- `lock`
- `storage`
- `sync`
- `config`
- `context`
- `handoff`
- `repair`
- `doctor`

Top-level commands that are part of the supported surface are:

- `init`
- `status`
- `usage`
- `monitor`
- `next-action`
- `can`
- `reindex`
- `export`
- `import`
- `snapshot`
- `search`
- `grep`
- `symbols`
- `deps`

All CLI commands support `--cwd`; task-first workflows also support `--root` as
the preferred workspace alias. JSON mode returns a stable envelope with
`ok`, `command`, `task_id` when applicable, `result`, `events`, and a
structured `error` object on failure.

Workflow additions:

- `task create` creates a task. Use `task activate TASK_REF` to make it active.
- `task follow-up PARENT_REF TITLE` creates a new draft child task linked to a
  completed parent. Use it for small post-completion deltas instead of
  reopening the done task.
- `plan template` and `question add-many` support faster plan drafting and batch
  planning setup.
- `plan draft`, `plan upsert --from-answers`, and
  `plan materialize-todos` support the question-answer-regenerate loop.
- `question status` reports required open questions and whether regeneration is
  needed, including plan-template hints when answered questions require a plan update.
- `implement restart --summary ...` starts a new implementation run from
  `failed_validation` while preserving the prior failed validation history.
- `implement resume --reason ...` reacquires an implementation lock for an
  existing running implementation run after a lock break or other orphaned-lock
  recovery.
- `task uncancel --reason ... [--to STAGE]` restores truly cancelled tasks to a
  safe durable non-active stage; active work still resumes through the normal
  stage-specific commands.
- `todo done` records evidence with `--evidence`, `--artifact`, and `--change`.
- `handoff create|list|show|claim|close|cancel` are available on the main
  task-first handoff command group.
- `usage` is the compact fresh-session read command for agents and scripts.
- `monitor` is the lightweight read-only terminal dashboard for humans.
- `file link`, `file status`, and `file refresh` support baseline-aware linked-file tracking.
