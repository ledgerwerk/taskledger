[![PyPI - Version](https://img.shields.io/pypi/v/taskledger)](https://pypi.org/project/taskledger/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/taskledger)
![PyPI - Downloads](https://img.shields.io/pypi/dm/taskledger)
[![codecov](https://codecov.io/gh/holgern/taskledger/graph/badge.svg?token=6usFHwM5Ul)](https://codecov.io/gh/holgern/taskledger)

# taskledger

`taskledger` is a task-first durable state layer for staged coding work. It keeps
project-local configuration in `taskledger.toml` at the workspace root and stores
plans, approval state, implementation logs, validation results, locks, and
fresh-context handoffs under a configurable `taskledger_dir` (default:
`.taskledger/` beside that config file).

## Canonical workflow

```text
task -> plan -> approval -> implement -> validate -> done
```

The normal agent path is deliberately small:

```text
actor whoami
task active | task show | task create | task activate | task follow-up
next-action | context | can
plan start -> plan template -> plan upsert -> plan lint -> plan accept
question add | question add-many | question answer | question answer-many | question status | question answers
todo next | todo show | todo done | todo status
implement start | implement resume | implement change | implement scan-changes | implement finish
validate start | validate status | validate check | validate finish
review record
handoff create | handoff show | handoff claim | handoff close
```

Everything else is support, human inspection, advanced transfer/storage work,
repair/migration, or beta project search. Those commands remain public, but
they are not part of the baseline lifecycle agents should reach for first.

The broader command surface is organized as:

**Core workflow:**

- `task`, `plan`, `question`, `implement`, `validate`, `todo`

**Context and decision-making:**

- `intro`, `file`, `link`, `require`, `handoff`, `config`

**Operations and advanced overlays:**

- `context`, `pipeline`, `next-action`, `can`, `search`, `grep`, `symbols`, `deps`, `actor`, `view`, `serve`, `storage`, `sync`

**Repair and inspection:**

- `lock`, `doctor`, `repair`, `reindex`

**Project lifecycle:**

- `init`, `status`, `export`, `import`, `snapshot`, `release`

## Non-goals

Taskledger is not a general project-management suite, issue tracker, CI system,
release manager, or source-code intelligence platform. It is a local durable
ledger for staged coding work. Optional reporting, sync, search, and worker
pipeline features must not change the default task-first lifecycle unless a
project explicitly opts in.

### Which read command to use

| Need                       | Command                                             |
| -------------------------- | --------------------------------------------------- |
| Next step                  | `next-action`                                       |
| Next implementation item   | `todo next`                                         |
| Active task summary        | `task show`                                         |
| Specific task summary      | `task show TASK_REF` or `task show --task TASK_REF` |
| Project/ledger overview    | `status`, `tree`                                    |
| Human dashboard            | `serve`                                             |
| Reviewable markdown report | `task report`                                       |
| LLM/agent compiled export  | `task export`                                       |
| Fresh worker context       | `context` or durable `handoff show`                 |
| Command audit              | `task transcript`                                   |

## Planning guidance profiles

Taskledger supports project-local advisory planning guidance under
`[prompt_profiles.planning]` in the active project config file (`taskledger.toml`
or `.taskledger.toml` when legacy config is still present).

```toml
[prompt_profiles.planning]
profile = "strict"
question_policy = "always_before_plan"
max_required_questions = 3
min_acceptance_criteria = 2
todo_granularity = "atomic"
require_files = true
require_test_commands = true
require_expected_outputs = true
require_validation_hints = true
plan_body_detail = "detailed"
required_question_topics = ["scope", "compatibility", "test strategy"]
extra_guidance = "Every plan must mention docs, tests, and rollback or repair behavior."
```

Inspect guidance for the active task:

```bash
taskledger plan guidance
taskledger --json plan guidance
```

This guidance is advisory and cannot override lifecycle gates, user approval,
validation requirements, lock rules, or higher-priority harness instructions.
See `docs/usage.rst` for the full key reference and workflow details.

Quick config inspection/edit examples:

```bash
taskledger config list
taskledger config get prompt_profiles.planning.max_required_questions
taskledger config set prompt_profiles.planning.max_required_questions 3
taskledger config set prompt_profiles.planning.question_policy always_before_plan
```

## Optional worker pipelines

Projects may optionally configure worker pipelines in `taskledger.toml` to guide
fresh-context handoffs. Worker pipelines are advisory overlays on the existing
planning, implementation, and validation lifecycle. They can be three steps,
four steps, five steps, or custom. When no worker pipeline is configured, the
default taskledger behavior is unchanged.

```toml
[worker_pipeline]
enabled = true
name = "tdd-four-context"
mode = "guided"

[[worker_pipeline.steps]]
id = "planner"
lifecycle_stage = "planning"
base_context = "planner"

[[worker_pipeline.steps]]
id = "tester"
label = "Test Writer"
lifecycle_stage = "implementation"
base_context = "implementer"
actor_role = "implementer"
kind = "check"
description = "Add or update failing tests before code changes."
required_output = ["New or updated failing tests with a short summary."]
must_not = ["Do not change production code in this step."]
todo_tag = "tests"
test_command_policy = "may_fail"

[[worker_pipeline.steps]]
id = "coder"
lifecycle_stage = "implementation"
base_context = "implementer"
kind = "todo"
description = "Implement the approved change and make the tests pass."
required_output = ["Code changes plus passing targeted checks."]
must_not = ["Do not skip required validation evidence."]
todo_tag = "implementation"
test_command_policy = "must_pass"

[[worker_pipeline.steps]]
id = "reviewer"
lifecycle_stage = "review"
base_context = "code-reviewer"
kind = "review"
```

Supported top-level keys are `enabled`, `name`, `mode`, and `steps`. Supported
step keys are `id`, `label`, `lifecycle_stage`, `base_context`, `actor_role`,
`kind`, `description`, `required_output`, `must_not`, `todo_tag`, and
`test_command_policy`. `mode = "guided"` does not add lifecycle gates; it adds
worker-step hints to `taskledger next-action`, including the pending step id plus
ready-to-run worker context and handoff commands.

```bash
taskledger pipeline show
taskledger pipeline next
taskledger next-action
taskledger context --worker tester
taskledger pipeline context tester
taskledger handoff create --worker tester --summary "Add failing tests only."
taskledger plan template --with-worker-pipeline --file ./plan.md
```

## Install

```bash
python -m pip install -e .
python -m pip install -e ".[dev]"
```

### Shell completion

After installing `taskledger`, install completion for your current shell:

```bash
taskledger --install-completion
```

To inspect the generated completion script instead of installing it:

```bash
taskledger --show-completion
```

Restart your shell session after installation.

## Quick start

Initialize durable state in the current workspace:

```bash
taskledger init
# or keep storage outside the source repo
taskledger init --taskledger-dir /mnt/cloud/taskledger/my-repo
# or point at another workspace explicitly
taskledger --root /path/to/repo init
```

`init` writes `taskledger.toml` in the workspace root. By default that config
points at `.taskledger/`, but `--taskledger-dir` can move durable state to an
external directory without nesting another `.taskledger` inside it.

Create and activate a task, ask required planning questions, regenerate the
plan from answers, approve it, implement todos with evidence, and validate it:

```bash
taskledger task create "Rewrite V2" --slug rewrite-v2 --description "Migrate to the task-first design."
taskledger task activate rewrite-v2 --reason "Start planning"
taskledger plan start
taskledger question add-many --required-for-plan --text $'Should exports include the new state?\nShould snapshots include implementation artifacts?'
taskledger question answer-many --text $'q-0001: Yes.\nq-0002: No.'
taskledger question status
taskledger plan template --from-answers --file ./plan.md
taskledger plan upsert --from-answers --file ./plan.md
taskledger plan review --version 1
taskledger plan lint --version 1
taskledger plan accept --version 1 --note "Ready."

taskledger next-action
taskledger --json next-action

taskledger context --for implementation --format markdown
taskledger implement start
taskledger implement checklist
taskledger implement change --path taskledger/storage/task_store.py --kind edit --summary "Normalized v2 markdown storage."
taskledger todo done todo-0001 --evidence "Updated taskledger/storage/task_store.py"
taskledger implement finish --summary "Implemented the approved plan."
taskledger review record --result pass --summary "No blocking code-quality issues."

taskledger context --for validation --format markdown
taskledger validate start
taskledger validate status
taskledger validate check --criterion ac-0001 --status pass --evidence "pytest -q tests/test_taskledger_v2_cli.py"
taskledger validate finish --result passed --summary "Validated the rewrite."
```

Review evidence may also be recorded after validation has moved a task to
`done`; this appends a review record without reopening the completed task.

To revise a proposed plan, re-enter planning and edit an exported workspace
copy. Never edit `.taskledger/` files directly:

```bash
taskledger plan revise
taskledger plan export --version latest --file ./plan.md
# edit ./plan.md
taskledger plan upsert --file ./plan.md
```

For manually completed work (e.g., manual testing, operations tasks, or work
completed outside the task-first lifecycle), use `task record` to create a
done task directly without acquiring lifecycle locks. **Note**: `task record`
does not replace the normal task lifecycle; it is for recording work already
completed, not as a shortcut for active task management.

```bash
taskledger task record "Deploy to production" --summary "Deployed v0.4.1 to prod" --change "infra/deploy.sh:run:Updated prod config" --evidence "Monitoring shows no errors"
taskledger task record "Manual API testing" --summary "Tested new endpoints" --allow-empty-record --reason "Exploratory testing, no formal changes tracked"
```

Archive is a visibility operation: it hides tasks from default list/tree/dashboard
views without deleting history. Task ids stay monotonic and are never reused.
Slugs can be reused after archive.

```bash
taskledger task archive task-0030 --reason "Hide historical task"
taskledger task list --archived
taskledger task unarchive task-0030 --reason "Need to continue work" --slug task-0030-reopened
taskledger tree --include-archived
```

If validation finds an implementation bug, keep the accepted plan and restart
implementation explicitly:

```bash
taskledger validate finish --result failed --summary "Parser edge case still fails."
taskledger next-action
taskledger context --for implementation --format markdown
taskledger implement restart --summary "Fix failed validation findings."
```

## Release tagging and changelog context

Release commands are advanced human/project operations, not part of the normal
task -> plan -> approval -> implement -> validate -> done agent path.

Use durable release tags to mark completed task boundaries and generate
provider-neutral changelog source packs from finished tasks:

```bash
taskledger release tag 0.4.1 --at-task task-0030 --note "0.4.1 released"
taskledger release changelog 0.4.2 --since 0.4.1 --until-task task-0035 --output /tmp/taskledger-0.4.2-changelog-source.md
taskledger release show 0.4.1
taskledger release list
```

`release changelog` does not call an LLM API. It renders compact Markdown or JSON
from done tasks, implementation logs, code changes, and validation evidence so a
separate coding harness can draft the final human changelog.

`taskledger next-action` is the preferred fresh-context entrypoint. It stays
read-only and points at the next concrete question, todo, criterion, or repair
step.

Human output example:

```text
todo-work: Implementation is in progress; 1 todos remain.
Next todo: todo-0001 -- Update next-action JSON payload.
Command: taskledger todo show todo-0001
Mark todo done after evidence exists: taskledger todo done todo-0001 --evidence "..."
Progress: 0/1 todos done
```

JSON result example:

```json
{
  "kind": "task_next_action",
  "action": "todo-work",
  "next_command": "taskledger todo show todo-0001",
  "next_item": {
    "kind": "todo",
    "id": "todo-0001",
    "text": "Update next-action JSON payload.",
    "validation_hint": "Run: pytest tests/test_todo_implementation_gate.py -q; Expected: pass",
    "done_command_hint": "taskledger todo done todo-0001 --evidence \"...\""
  },
  "commands": [
    {
      "kind": "inspect",
      "label": "Show next todo",
      "command": "taskledger todo show todo-0001",
      "primary": true
    },
    {
      "kind": "complete",
      "label": "Mark todo done after evidence exists",
      "command": "taskledger todo done todo-0001 --evidence \"...\"",
      "primary": false
    }
  ],
  "progress": {
    "todos": {
      "total": 1,
      "done": 0,
      "open": 1,
      "open_ids": ["todo-0001"]
    }
  },
  "blocking": []
}
```

## Compact implementation loop

For routine same-session implementation, prefer `next-action` and the single next
todo over broad generated context:

```bash
taskledger --json next-action
taskledger --json todo next
taskledger todo show todo-0003
# implement only that todo
pytest tests/...
taskledger todo done todo-0003 --evidence "pytest tests/... passed"
taskledger --json next-action
```

Rules for agents:

- Prefer `next-action` and `todo next` over generated context during normal work.
- Use the todo `validation_hint` before marking a todo done.
- Record concise evidence with `todo done`.
- Do not create handoffs or context bundles unless the user asked to switch harness or session.

## Human monitoring UI

`taskledger serve` starts a read-only local server-rendered HTML dashboard for
human monitoring. It emphasizes the active task, next action, progress, and
task browsing while staying local-only and read-only.

```bash
taskledger report html task-0040 --output task-0040.html
taskledger report html --active --output active-task.html
taskledger report site --output .taskledger-report/

taskledger serve --refresh-seconds 2
taskledger serve --open
taskledger serve --task task-0040 --refresh-seconds 2
```

Agents should keep using `taskledger next-action`, `taskledger todo next`, and
`--json` commands as the canonical automation interface for routine same-session
work. Reach for `context` or handoffs when the task actually needs a broader
fresh-context transfer.

## Storage layout

`taskledger` keeps project-local configuration in the workspace root and durable
records under the configured storage root. The checked-in `taskledger.toml`
stores project identity plus the current branch-scoped ledger pointer and next
task number. Operational task state remains ignored under
`.taskledger/ledgers/<ledger_ref>/`:

```text
taskledger.toml
.taskledger/
  storage.yaml
  ledgers/
    main/
      intros/
      releases/
      tasks/
      events/
      indexes/   # optional derived caches and registries
```

Markdown files are canonical. Task, plan, and run listings scan only the current
ledger by default. JSON files under the current ledger's `indexes/` directory are
optional derived caches or registries and are not required for task correctness.

### Branch-scoped ledgers

`.taskledger/` stays ignored and local. `taskledger.toml` is safe to commit and
contains the current `ledger_ref`, optional parent ref, and the next logical task
number for the checked-out source branch.

When starting long-lived branch-local work, fork the ledger pointer after creating
the Git branch:

```bash
git checkout -b feature-a
taskledger ledger fork feature-a
git add taskledger.toml
```

Returning to a branch whose `taskledger.toml` points back to `main` hides the
feature branch's active task and task list. Two ledgers may both contain a logical
`task-0030`; this is expected because task IDs are scoped by `ledger_ref`. Use
`taskledger ledger adopt --from REF TASK_REF` when branch-local task history
should be copied into the current ledger.

You can also point `taskledger.toml` at an external storage root:

```bash
taskledger init --taskledger-dir /mnt/cloud/taskledger/project-a
```

```text
/home/me/src/project-a/taskledger.toml
/mnt/cloud/taskledger/project-a/storage.yaml
/mnt/cloud/taskledger/project-a/ledgers/main/releases/
/mnt/cloud/taskledger/project-a/ledgers/main/tasks/
/mnt/cloud/taskledger/project-a/ledgers/main/events/
/mnt/cloud/taskledger/project-a/ledgers/main/indexes/
```

Use one `taskledger_dir` per source project. Do not share one storage directory
across unrelated repositories.

### Sync across PCs without committing `.taskledger/`

Use a sibling private Git repository for the external storage root instead of
committing `.taskledger/` into the source repository:

```toml
# /home/me/src/project-a/taskledger.toml
taskledger_dir = "../taskledger-state/project-a"
```

```text
/home/me/src/project-a/                  # source repo
/home/me/src/taskledger-state/           # private state repo
/home/me/src/taskledger-state/project-a/ # taskledger_dir
```

Keep one active writer at a time. Before starting on a PC, pull the private
state repo, then run `taskledger doctor` and `taskledger next-action`. After
stopping at a clean lifecycle boundary, commit and push the state repo. If work
must move mid-run, prefer `taskledger export TASK_REF` / `taskledger import ARCHIVE` because imported runtime locks are quarantined by default.

Helpful local commands:

```bash
taskledger storage where
taskledger sync preflight
taskledger sync status
taskledger sync commit --message "Sync project-a taskledger state"
taskledger sync export --output ./taskledger-transfer.tar.gz
taskledger sync import ./taskledger-transfer.tar.gz --dry-run
taskledger sync git init --repo ../taskledger-state --project-path project-a
taskledger sync git status
taskledger sync git commit --message "Sync project-a taskledger state"
cd "$(taskledger sync git cd)"
git pull --ff-only
git push
```

See `docs/sync.rst` for the full second-PC bootstrap, daily sync protocol, and
Syncthing/rclone caveats.

## JSON output

Use `--json` for machine-readable payloads:

```bash
taskledger --json status --full
taskledger --json task active
taskledger --json task show
taskledger --json task show task-0001
taskledger --json context --for validation --format json
```

Example status payload:

```json
{
  "ok": true,
  "command": "status",
  "result": {
    "kind": "taskledger_status",
    "workspace_root": "/home/me/src/project-a",
    "config_path": "/home/me/src/project-a/taskledger.toml",
    "taskledger_dir": "/home/me/src/project-a/.taskledger",
    "project_dir": "/home/me/src/project-a/.taskledger",
    "counts": {
      "tasks": 1,
      "introductions": 0,
      "plans": 1,
      "questions": 1,
      "runs": 2,
      "changes": 1,
      "locks": 0
    },
    "active_task": null,
    "healthy": true
  },
  "events": []
}
```

## Event logging

Task lifecycle event logging is **disabled by default**. Enable it in
`taskledger.toml` when debugging agent usage or lifecycle behavior:

```toml
[event_logging]
enabled = true
```

When enabled, mutations append immutable `TaskEvent` records viewable with
`taskledger task events`. When disabled (the default), no event records are
written but `task events` still works and returns empty results. Existing event
files remain readable regardless of the setting.

## Handoff-driven work

Fresh-context handoff is a primary feature:

```bash
taskledger context --for planning --format markdown
taskledger context --for implementation --format markdown
taskledger context --for validation --format json
taskledger task report --task task-0030 -o task30.md
taskledger task export task-0030 -o task-0030.llm.md
taskledger report html task-0030 --output task30.html
taskledger handoff create --mode implementation --intended-actor agent --intended-harness codex
taskledger handoff claim handoff-0001
taskledger handoff close handoff-0001 --reason "Implementation started."
```

`task dossier`, root `view`, and the legacy `handoff *-context` renderers remain
advanced/compatibility read surfaces. Prefer `context --for ...` and
`handoff show` for agent continuation.

## Fresh-worker contexts

Use focused contexts when handing one todo or one review run to a fresh worker:

```bash
taskledger context --for implementer --todo todo-0003
taskledger context --for spec-reviewer --run run-0008
taskledger context --for code-reviewer --run run-0008
taskledger handoff create --mode implementation --todo todo-0003
taskledger handoff show handoff-0001 --format markdown
```

`handoff create` now stores the generated Markdown context snapshot in the handoff
record so another harness can continue from the exact same input.

## Multi-Actor Handoff Protocol

The handoff protocol enables safe work transitions between human and agent actors across different harnesses:

### Features

- **Actor Identity**: Track WHO performs each stage (human, agent, system)
- **Harness Tracking**: Record FROM WHERE each stage ran (manual, Codex, OpenCode, etc.)
- **Handoff Records**: Explicitly hand off work with context and intent
- **Claim Protocol**: New actors claim handoffs before starting work
- **Lock Management**: Transfer or release locks during handoffs
- **Event Trail**: Full audit trail recording all state changes
- **Durable Records**: Markdown-first storage with YAML metadata

### Quick Start

```bash
# See your current identity
$ taskledger actor whoami

# Create a handoff
$ taskledger handoff create --task task-0001 --mode implementation --todo todo-0003

# Claim it
$ taskledger handoff claim handoff-0001 --task task-0001

# Show details
$ taskledger handoff show handoff-0001 --task task-0001 --format text

# Close when done
$ taskledger handoff close handoff-0001 --task task-0001 --reason "Continued."
```

See [docs/usage.rst](docs/usage.rst) and
[skills/taskledger/SKILL.md](skills/taskledger/SKILL.md)
for task-first handoff guidance.

## Export, import, and snapshots

```bash
taskledger init --project-name "Taskledger"
taskledger export
taskledger export --task task-0040
taskledger export task-0040
taskledger import ./taskledger-transfer.tar.gz --dry-run
taskledger import ./taskledger-task-planledger-main-task-0040-20260509T101500Z.tar.gz
taskledger import ./taskledger-transfer.tar.gz --replace
taskledger snapshot ./artifacts
```

When no explicit output path is passed, default export archives are written
inside the resolved workspace root with this filename policy:

```text
taskledger-export-{project_slug}-{ledger_ref}-{timestamp}.tar.gz
taskledger-task-{project_slug}-{ledger_ref}-{task_id}-{timestamp}.tar.gz
```

`project_slug` is derived from `project_name` in `taskledger.toml`. If
`project_name` is missing, taskledger falls back to the workspace directory name.
Import safety still relies on `project_uuid`, not the name/slug.

`--include-bodies` and `--include-run-artifacts` now change archive content:

- `--no-include-bodies` strips record body text (`body` / `context_body`) from exported payloads.
- `--include-run-artifacts` embeds task and agent-log artifact files under `artifacts/` in the archive.

Cross-machine imports preserve durable task/run data, but imported runtime locks
are quarantined by default. After importing an in-progress implementation,
run:

```bash
taskledger next-action
taskledger implement resume --reason "Continue imported implementation."
```

Use `--lock-policy keep` only for diagnostic full-fidelity lock restoration.

Single-task transfer from a config-only checkout:

```bash
# fresh checkout on another PC
taskledger init
taskledger task create "Fix import edge case" --slug fix-import-edge-case --description "..."
# ... normal plan / implementation / validation lifecycle ...
taskledger export task-0040

# main dev repo
taskledger import ./taskledger-task-planledger-main-task-0040-20260509T101500Z.tar.gz
taskledger task list
taskledger task show task-0040
```

## Skill packaging

Agent workflows work best when the `taskledger` skill is installed in the
coding harness. The CLI has a task-first lifecycle with explicit planning,
approval, implementation, validation, locks, and handoff gates; without the
skill, an agent may not know the intended command sequence or gate semantics.

The canonical skill file lives at:

```text
skills/taskledger/SKILL.md
```

Keep this skill outside the Python package. No additional
`skills/taskledger/examples/` directory is required.

## Development

```bash
python -m pytest -m "not slow"
python -m pytest -m "not slow" -n auto
python -m pytest -n auto
python -m pytest
ruff check .
```

Full release-readiness sweep:

```bash
make release-check
```
