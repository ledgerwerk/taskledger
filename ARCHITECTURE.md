---
title: "Architecture Documentation"
version: 1
generator: "archledger 0.3.2.dev1+g505ad5c4c"
arc42_template_version: "9.0-EN"
---

# Architecture Documentation

Generated from archledger records. Do not edit this generated file directly.

# Introduction and Goals

taskledger is a task-first durable state layer for staged coding work. It provides a Python CLI and library that manages the full lifecycle of coding tasks: creation, planning, user approval, implementation, validation, and completion.

The system is designed for use by both human developers and automated coding agents. Its primary goals are:

- **Durable task state**: Every task, plan, run, lock, todo, and validation check is persisted as a Markdown record with YAML front matter in the project `.taskledger/` directory. State survives process restarts, context switches, and handoffs between actors.
- **Explicit lifecycle gates**: Transitions between stages (draft -> planning -> plan_review -> approved -> implementing -> implemented -> validating -> done) are enforced by policy decisions. User approval is required before implementation begins. Validation checks gate completion.
- **Fresh-context handoffs**: Agents and humans can create, claim, and close handoff records that capture enough context (task state, plan, todos, questions, lock status) for a fresh process to continue work without reading the entire history.
- **Machine-readable output**: Every CLI command supports `--json` for structured output with a stable envelope shape (`ok`, `command`, `result_type`, `result`, `events`, `warnings`) and deterministic exit codes.
- **Opaque cross-ledger references**: Task-ledger task, plan, file, and link references remain opaque strings. Taskledger does not interpret ledgercore global refs, archledger IDs, or other external system identifiers.

The canonical workflow is:

```text
task -> plan -> approval -> implement -> validate -> done
```

This workflow is the product contract, not decoration. Deviations from this flow require explicit user decisions or repair commands.

## Requirements Overview

| Title                                         | Priority | Source | Stakeholders | Quality goals |
| --------------------------------------------- | -------- | ------ | ------------ | ------------- |
| Durable task lifecycle state                  | must     |        |              |               |
| Explicit lifecycle gates with user approval   | must     |        |              |               |
| Fresh-context handoffs for agent continuation | must     |        |              |               |

## Quality Goals

<!-- archledger: no accepted records for this section yet -->

## Stakeholders

| Title            | Contact | Expectations                                                                                                                 |
| ---------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Coding agents    |         | deterministic exit codes, stable json envelope, fresh context handoff continuation, task first workflow, human approval gate |
| Human developers |         | human approval workflow, concise human rendering, plan review and acceptance, acceptance criterion waivers, monitor overview |

# Architecture Constraints

taskledger operates under several fixed constraints that shape its architecture:

- **Python 3.10+ with minimal dependencies**: The runtime depends only on `typer`, `click`, `PyYAML`, `tomli` (Python <3.11), and `ledgercore` for atomic I/O, JSON I/O, YAML I/O, front matter parsing, and cross-ledger ref parsing. No database, no network server, no external service is required.
- **File-system canonical storage**: All durable state lives in the project `.taskledger/` directory as Markdown files with YAML front matter. This makes state inspectable, diffable, and version-controllable alongside source code.
- **CLI-first with machine-readable JSON output**: The primary interface is the `taskledger` CLI command. Every command supports `--json` for structured output. The JSON envelope shape and exit codes are part of the public contract.
- **Skills outside the package**: Agent skill files (for example `skills/taskledger/SKILL.md`) live outside the Python package and are never packaged as Python package data. The package provides the CLI and library; skill distribution is separate.
- **Project-local configuration**: Each project has its own `taskledger.toml` and `.taskledger/` directory. There is no global state or central server.
- **Source-first architecture records**: Arc42 architecture records live under `.archledger/` and are the source of truth for `ARCHITECTURE.md`. `docs/architecture_taskledger_split.md` is a concise human-maintained summary. Skills stay outside both the Python package and the archledger build output.

- **Python 3.10+ with minimal ledgercore-backed dependencies**
  - Impact: Limits runtime to Python 3.10+ with three dependencies; no database or native extensions.
  - Notes: Runtime dependencies are limited to `typer`, `click`, `PyYAML`, `tomli` (Python <3.11 only), and `ledgercore` (for atomic I/O, JSON I/O, YAML I/O, front matter parsing, and cross-ledger ref parsing). This constraint ensures easy installation in constrained environments (CI, containers, Termux) and avoids dependency conflicts with host projects. The trade-off is that features like full-text search use pure-Python implementations rather than native libraries.
- **File-system canonical storage with sidecar summary index**
  - Impact: State is file-based; query performance depends on index rebuilds.
  - Notes: All durable state is stored as Markdown files with YAML front matter in `.taskledger/`. This makes state human-readable, diffable in Git, and inspectable without taskledger. The trade-off is that query performance depends on file scanning and `task_sidecars.json` summary index rebuilding rather than a database engine. The sidecar index is maintained in place by per-task sidecar writes and rebuilt from canonical records on miss.
- **CLI-first with machine-readable JSON output**
  - Impact: JSON envelope shape and exit codes are public API contracts; breaking changes require version bumps.
  - Notes: The CLI is the primary interface. Every command supports `--json` for machine-readable output with a stable envelope shape (`ok`, `command`, `result_type`, `result`, `events`, `warnings`) and deterministic exit codes. This enables agent harnesses and CI pipelines to consume output programmatically without parsing human text.
- **Skills must stay outside the Python package**
  - Impact: Skill distribution is separate from package distribution; skill installation is a distinct step.
  - Notes: Agent skill files (e.g., `skills/taskledger/SKILL.md`) live outside the `taskledger` Python package. They are not packaged as package data, not loaded via `importlib.resources`, and not distributed via PyPI. This separates the concerns of tool functionality (the package) from agent integration instructions (the skill).

# Context and Scope

taskledger operates as a self-contained tool within a software development project. It interacts with four categories of external actors:

1. **Agent harnesses** (pi, codex, chatgpt, and similar) invoke taskledger CLI commands to create tasks, propose plans, log implementation changes, run validation checks, and manage handoffs. They consume `--json` output.
2. **Human developers** use the CLI directly in terminals for task creation, plan review, approval, lock management, and inspection (`status`, `context`, `next-action`, `doctor`, `monitor`).
3. **CI systems** may invoke taskledger for status checks, validation, snapshot/export operations, and `taskledger trace` bundles.
4. **Python library consumers** import from `taskledger.api.*` to programmatically manage tasks without the CLI subprocess.

The system boundary is the `.taskledger/` directory and the `taskledger.toml` config file at the project root. Everything inside `.taskledger/` is taskledger-owned state. Everything outside is the host project source code. Taskledger does not depend on any external services, databases, or network endpoints. It reads the host project file system for search/symbol operations but does not modify files outside `.taskledger/`.

## Business Context

<!-- archledger: no accepted records for this section yet -->

## Technical Context

<!-- archledger: no accepted records for this section yet -->

# Solution Strategy

taskledger uses a layered architecture with clear dependency direction: upper layers depend on lower layers, never the reverse.

1. **CLI Layer** (`taskledger/cli*.py`) — Typer commands that parse arguments, resolve task references, call service functions, and render output (human text or JSON).
2. **API Layer** (`taskledger/api/*.py`) — Stable public wrappers that mirror the CLI surface for programmatic use.
3. **Services Layer** (`taskledger/services/*.py`) — Orchestration logic: lifecycle flows (planning, implementation, validation), handoff rendering, doctor checks, plan input validation, plan review, snapshot capture, dashboard assembly, and navigation.
4. **Domain Layer** (`taskledger/domain/*.py`) — Pure data models, state enums, normalization, and policy decisions. No I/O, no file system access.
5. **Storage Layer** (`taskledger/storage/*.py`) — File system operations: front matter read/write, atomic writes, lock files, sidecar index rebuilds, migrations. Storage delegates low-level primitives to `ledgercore`.

Key architectural choices:

- **Markdown and YAML front matter as canonical format** — Each record (task, plan, run, lock, handoff, code review, etc.) is stored as a `.md` file with YAML front matter metadata and a Markdown body. This makes state human-readable and Git-friendly.
- **Sidecar indexes as derived caches** — A `task_sidecars.json` summary index lives under `.taskledger/ledgers/<ledger_ref>/` and is rebuilt from canonical records. Per-task sidecar writes update the index in place.
- **Policy-based gate decisions** — All lifecycle transitions go through functions in `taskledger/domain/policies.py` that return `Decision` objects with `allowed`, `code`, `message`, and `exit_code`. This keeps gate logic testable and separate from I/O.
- **Atomic file writes** — All writes use `atomic_write_text` (write to temp, fsync, `os.replace`) from `ledgercore`.
- **Editable plan input with preflight** — `taskledger plan check` parses editable plan input through `taskledger/services/plan_input.py`, applies worker-pipeline validation, and returns indexed issues before any plan upsert.
- **Implementation workspace snapshots** — `taskledger/services/workspace_snapshot.py` captures Git and content snapshots when an implementation run starts, and `validate start` blocks when the workspace diverges. `implement snapshot refresh --reason ...` records new snapshots with an audit trail.
- **Opaque cross-ledger references** — Task refs, plan versions, file links, and external handoff targets are stored as opaque strings. Taskledger does not interpret ledgercore global refs, archledger IDs, or other external system identifiers.
- **Read-model reuse** — `view`, `status`, `tree`, and `monitor` consume service-level read models. These presentations are read-only and do not bypass lifecycle services.

## Maintenance

`ARCHITECTURE.md` in the repository root is generated from archledger source records. Do not edit it directly.

- **Edit**: `.archledger/profiles/arc42/sections/*.md` for section content, `.archledger/records/**/*.md` for individual records.
- **Regenerate**: Run `archledger build` to regenerate `ARCHITECTURE.md`.
- **Verify**: Run `archledger check` and `pytest -q tests/test_docs_and_skill.py tests/test_service_boundaries.py` after changes.
- **Authoritative source**: The archledger records under `.archledger/` are the single source of truth for architecture documentation. `docs/architecture_taskledger_split.md` is a concise human-maintained summary.

## Strategy Items

## Layered architecture: CLI → Services → Domain → Storage

**Drivers:**
**Constraints:**
**Related ADRs:**

## Strategy

The codebase is organized into five layers with target dependency direction: CLI (`taskledger/cli*.py`) -> API (`taskledger/api/`) -> Services (`taskledger/services/`) -> Domain (`taskledger/domain/`) + Storage (`taskledger/storage/`). The Domain layer has no I/O dependencies. Storage owns canonical taskledger persistence and atomic record I/O, delegating low-level primitives (atomic writes, JSON I/O, YAML I/O, front matter parsing, cross-ledger ref parsing) to `ledgercore`. Other layers may perform bounded filesystem operations for external inputs and outputs (reports, Git sync, search, CLI file arguments). CLI should prefer API wrappers for public workflows, but current sanctioned exceptions are tracked in `tests/test_service_boundaries.py`.

## Trade-offs

- Clear separation of concerns enables focused testing per layer.
- Service modules can grow large since they orchestrate across domain and storage.
- No formal dependency injection; layer boundaries are enforced by convention and the `test_service_boundaries.py` test.

## Markdown/YAML front matter as canonical records

**Drivers:**
**Constraints:**
**Related ADRs:**

## Strategy

Each persistent record (task, plan, run, lock, handoff, event, etc.) is stored as a `.md` file with YAML front matter for structured metadata and a Markdown body for free-form content. This format is human-readable, Git-diffable, and editable without taskledger. The front matter serialization is handled by `taskledger/storage/frontmatter.py`.

## Trade-offs

- Slower to parse than JSON or SQLite for large datasets.
- State is transparent and version-controllable — a core design goal.
- Schema evolution requires careful front matter validation (`_require_contract`, `_string_value`, etc.).

## JSON indexes as rebuildable derived caches

**Drivers:**
**Constraints:**
**Related ADRs:**

## Strategy

A `task_sidecars.json` summary index under `.taskledger/ledgers/<ledger_ref>/` is a derived cache rebuilt from canonical Markdown records by `taskledger reindex`. Per-task sidecar writes call `update_sidecar_summary` in `taskledger/storage/sidecar_index.py` so the index stays current. The index speeds up list and query operations but is never authoritative. `taskledger doctor indexes` checks for staleness.

## Trade-offs

- Avoids the complexity of a query engine on front matter files.
- Indexes can become stale if writes bypass taskledger (for example manual edits). `taskledger doctor` and `reindex` address this.
- The summary index is a JSON document with a schema version and an `object_type` field; it is rebuildable from canonical records.

## Policy-based lifecycle gate decisions

**Drivers:**
**Constraints:**
**Related ADRs:**

## Strategy

All lifecycle transitions are validated through pure functions in `taskledger/domain/policies.py` that return `Decision` objects (`allowed`, `code`, `message`, `exit_code`). Policies have no I/O — they receive `PolicyContext` (task, lock, run) and return a decision. This makes gate logic fully testable without file system setup.

## Trade-offs

- Policy functions must receive all context explicitly (no lazy loading from storage).
- Very testable: `test_domain_policies.py` and `test_lifecycle_policies.py` cover the full decision surface.
- Services must gather the right context before calling policies.

## Atomic file writes for durability

**Drivers:**
**Constraints:**
**Related ADRs:**

## Strategy

All file writes go through the `ledgercore` atomic primitives used by `taskledger/storage/atomic.py`: write to a temp file in the target directory, flush plus fsync, then `os.replace` for atomic rename. Directory fsync follows. Lock creation uses `atomic_create_text` with `O_CREAT | O_EXCL` for exclusive creation. These patterns prevent partial or corrupt writes on crash.

## Trade-offs

- Slightly slower than direct writes due to temp file plus fsync overhead.
- Can be disabled for testing via the `TASKLEDGER_TEST_FAST_IO` environment variable.
- Guarantees that readers always see complete, valid files.

# Building Block View

The top-level building block is the **taskledger system**, decomposed into five black-box components:

1. **CLI Layer** — Handles command parsing, task reference resolution, and output rendering. Command families cover the canonical lifecycle plus `review`, `config`, task archive operations, transfer and sync, diagnostics, the `monitor` observer, and the `pipeline` overlay.
2. **API Layer** — Provides stable Python function wrappers around service operations.
3. **Services Layer** — Orchestrates lifecycle flows, plan input validation, plan review, handoffs, snapshot capture, navigation, doctor checks, worker pipelines, archival, code-review evidence, event logging, exports, dashboard assembly, and ready-work inspection.
4. **Domain Layer** — Defines models, state machines, and policy decisions.
5. **Storage Layer** — Manages file system persistence and layout. Low-level primitives (atomic writes, JSON, YAML, front matter, refs) are delegated to `ledgercore`.

Data flows strictly downward: CLI -> Services -> Domain + Storage. The API layer calls Services directly. The Domain layer has no dependencies on Storage or Services.

Each task is stored as a **task bundle directory** under `.taskledger/ledgers/<ledger_ref>/` containing the task record (Markdown) and sidecar collections for plans, runs, locks, todos, questions, changes, checks, handoffs, links, and code reviews. Mutations append immutable `TaskEvent` records to the ledger-level `events/` directory. Action and event logging is enabled by default; set `[event_logging] enabled = false` in `taskledger.toml` to disable new event records. Existing records remain readable regardless. A `task_sidecars.json` summary index under the same ledger path is maintained as a derived cache of sidecar counts and lock summaries.

## Whitebox taskledger system

## Motivation

taskledger decomposes into core layers with downward dependency flow. This isolates persistence, business rules, orchestration, and public interfaces. Low-level persistence primitives are delegated to `ledgercore`, but the layer boundary above it stays in `taskledger/storage/`.

## Contained building blocks

1. **CLI Layer** (`block-0030`) — Typer commands, argument parsing, output rendering
2. **API Layer** (`block-0031`) — Stable Python function wrappers
3. **Services Layer** (`block-0032`) — Lifecycle orchestration, handoffs, plan input, plan review, snapshots, inspection
4. **Domain Layer** (`block-0033`) — Models, state machines, policies (no I/O)
5. **Storage Layer** (`block-0034`) — File system persistence, atomic writes, sidecar index, layout

## Important interfaces

- CLI -> Services: function calls with `workspace_root` plus task references
- Services -> Domain: policy functions take `PolicyContext`, return `Decision`
- Services -> Storage: record CRUD operations through `task_store.py` functions and the sidecar index
- API -> Services: direct function calls mirroring CLI behavior
- Storage -> ledgercore: atomic I/O, JSON I/O, YAML I/O, front matter parsing, cross-ledger ref parsing

### Level 1

#### CLI Layer

**Parent:** block-0029
**Interfaces:**
**Location:**

Handles command parsing via Typer, task reference resolution (`--task` option, active task default), and output rendering (human text or JSON envelope via `cli_common.py`). Command families include the canonical lifecycle plus `review`, `config`, task archive operations, transfer and sync, diagnostics, the `monitor` observer, the `pipeline` overlay, and `ref` cross-ledger helpers.

Source refs: `taskledger/cli.py`, `taskledger/cli_common.py`, `taskledger/command_inventory.py`, and the focused `taskledger/cli_*.py` registration modules.

#### API Layer

**Parent:** block-0029
**Interfaces:**
**Location:**

Stable Python function wrappers under `taskledger/api/` that mirror the CLI surface for programmatic use. Each module (tasks, plans, handoff, locks, task runs, sync, reviews, search, etc.) exposes functions that accept workspace paths and return dictionaries matching the JSON output shape. The API layer calls Services directly.

#### Services Layer

**Parent:** block-0029
**Interfaces:**
**Location:**

Orchestrates lifecycle flows by coordinating Domain policies and records with Storage. Focused services own planning (`planning_flow.py`, `plan_input.py`, `plan_review.py`, `plan_lint.py`, `plan_materialization.py`), implementation (`implementation_flow.py`, `workspace_snapshot.py`), validation (`validation_flow.py`), handoffs (`handoff.py`, `handoff_lifecycle.py`, `worker_context.py`), doctor checks (`doctor.py`, `doctor_checks/`), navigation (`navigation.py`, `next_action_model.py`, `next_action_payload.py`, `ready_work.py`), worker pipelines (`worker_pipeline.py`, `workflow_guidance.py`), archival (`task_archive.py`, `task_export.py`, `task_reports.py`), code-review evidence (`code_review.py`), event logging (`task_events.py`, `agent_transcripts.py`, `agent_logging.py`, `change_tracking.py`, `check_tracking.py`, `event_logging.py`), exports and dashboard assembly (`dashboard.py`, `tree.py`, `monitor.py`). `tasks.py` remains the compatibility-oriented lifecycle facade while ownership is progressively extracted into focused modules.

#### Domain Layer

**Parent:** block-0029
**Interfaces:**
**Location:**

Data models, state enums, normalization, and policy decisions without storage I/O. Besides lifecycle and sidecar records, the domain defines append-only code-review records. State transitions remain in `states.py`; policy decisions in `policies.py` return structured `Decision` objects. The canonical storage layout version is `TASKLEDGER_STORAGE_LAYOUT_VERSION` in `taskledger/domain/states.py`.

#### Storage Layer

**Parent:** block-0029
**Interfaces:**
**Location:**

File system persistence for canonical records. Storage layout keeps each task in `.taskledger/ledgers/<ledger_ref>/tasks/<task-id>/`, with independently addressable sidecars including plans, runs, locks, todos, questions, changes, checks, handoffs, links, and code reviews. Ledger-level collections hold events, introductions, releases, and rebuildable indexes. A `task_sidecars.json` summary index is maintained as a derived cache; per-task sidecar writes call `update_sidecar_summary` from `taskledger/storage/sidecar_index.py` so the read path does not need a full rescan. Atomic write primitives, YAML I/O, front matter parsing, and ref parsing are delegated to `ledgercore`. Action and event logging is enabled by default and can be disabled in project config. Project config edits use structured TOML handling rather than ad hoc text replacement.

# Runtime View

The runtime view traces the main operational scenarios through the system:

1. **Task lifecycle** — A task is created in `draft`, moves to `planning` (lock acquired, run started), then `plan_review` after a plan is proposed. The user approves -> `approved`. Implementation starts -> `implementing`, finishes -> `implemented`. Validation starts -> `validating`, passes -> `done`.
2. **Plan input flow** — `taskledger plan start` opens planning. `plan guidance` reports the active project planning profile. `plan template` writes a fresh plan skeleton; `plan check --file plan.md` runs the preflight parser in `taskledger/services/plan_input.py` without mutating state. `plan upsert --file plan.md` (or `--from-answers`) persists the plan; `plan lint --version N` surfaces blocking issues; `plan review --version N` produces the approval brief; `plan accept --version N --note ...` records the user-only decision.
3. **Implementation workspace snapshot** — `implement start` captures a Git and content snapshot in `taskledger/services/workspace_snapshot.py`. `validate start` blocks when the current workspace diverges from the implementation snapshot. `implement snapshot refresh --reason ...` records a new snapshot with an audit trail and is the normal recovery path when validation is blocked by snapshot mismatch.
4. **Lock lifecycle** — Starting a stage (planning, implementation, validation) acquires a lock and creates a run. Locks have lease timers and heartbeats. Stale locks require explicit break flow with audit trail.
5. **Handoff flow** — A worker creates a handoff with generated context (task state, plan, todos, questions, lock info). Another worker claims it, optionally transferring the lock. The handoff is closed when the receiving worker completes.
6. **Doctor checks** — Inspects lock/run consistency, front matter integrity, index staleness, and storage layout version. Reports diagnostics with severity, code, and repair hints.
7. **Validation evidence flow** — Acceptance criteria from the accepted plan are checked during the validation stage. Evidence is recorded per criterion with pass/fail/warn status. Latest-check-wins semantics apply; mandatory criteria gate completion.
8. **Code-review evidence** — A reviewer records append-only review evidence against an implementation run, handoff, worker step, working tree, or commit. This is evidence attached to the task, not a new lifecycle stage.

## Task lifecycle: create through done

**Trigger**: User or agent runs `taskledger task create`.

**Flow**:

1. `task create` → TaskRecord persisted in `draft` stage with `task.created` event
2. `plan start` → Lock acquired, planning run started, stage → `planning`
3. `plan propose` → PlanRecord persisted, todos materialized, stage → `plan_review`
4. `plan approve` (user-only) → Stage → `approved`, lock released, run finished
5. `implement start` → Lock acquired, implementation run started, stage → `implementing`
6. `implement log` / `implement finish` → Changes logged, todos completed, stage → `implemented`
7. `validate start` → Lock acquired, validation run started, stage → `validating`
8. `validate check` / `validate finish` → Criteria checked, stage → `done` (or `failed_validation`)

**Result**: Task reaches `done` with all todos complete and all mandatory criteria passed. Events trail the full history.

**Key policy checks**: `can_start_planning`, `plan_propose_decision`, `plan_approve_decision`, implementation requires accepted plan, validation requires finished implementation run.

## Lock acquisition, heartbeat, and release

**Trigger**: Service calls `_start_run` (e.g., `plan start`, `implement start`, `validate start`).

**Flow**:

1. Check no existing active lock for the task
2. Create `TaskLock` record via `atomic_create_text` (exclusive file creation)
3. Create `TaskRunRecord` with status `running`
4. Append `lock.acquired` and `run.started` events
5. Update task stage to active stage (`planning`/`implementing`/`validating`)
6. Heartbeat updates `last_heartbeat_at` on the lock
7. On finish: run status → `finished`, lock removed, `lock.released` event appended

**Stale lock handling**:

- `lock_is_expired` checks lease expiry
- `lock break` requires explicit user action, records `broken_at`, `broken_by`, `broken_reason`
- `doctor` detects lock/run mismatches

**Key source**: `taskledger/services/tasks.py` (`_start_run`), `taskledger/storage/locks.py`, `taskledger/domain/lock.py`.

## Handoff creation and claiming

**Trigger**: Worker runs `taskledger handoff create`.

**Flow**:

1. Generate context body: task state, accepted plan, todos, questions, lock/run status, implementation summary, validation status
2. Create `TaskHandoffRecord` with mode (planning/implementation/validation/review/full), lock policy (none/retain/release/transfer), intended actor and harness
3. Persist handoff record, append `handoff.created` event
4. Another worker runs `handoff claim` → status → `claimed`, optional lock transfer
5. Worker completes work, runs `handoff close` → status → `closed`

**Key source**: `taskledger/services/handoff.py` (context generation), `taskledger/services/handoff_lifecycle.py` (claim/close/transfer), `taskledger/services/worker_context.py` (context assembly).

## Editable plan input preflight

**Trigger**: Agent or user edits a plan file and runs `taskledger plan check` and `taskledger plan upsert`.

**Flow**:

1. `plan check --file plan.md` -> Pure preflight parser in `taskledger/services/plan_input.py` returns a `plan_input_check` payload with `passed`, indexed `issues`, and parsed counts. No state mutation.
2. Worker-pipeline configuration in `taskledger.toml` is consulted to validate `worker_step` todo tags when present.
3. `plan upsert --file plan.md` (or `--from-answers`) runs the same parser, persists the plan as a `PlanRecord`, and materializes todos.
4. `plan lint --version N` runs structural lint over the proposed plan body and front matter.
5. `plan review --version N` renders the approval brief used by the user-only approval command.

**Result**: Plan is persisted with no parse errors, no lint errors, and no stale answers. Approval can proceed.

**Key source**: `taskledger/services/plan_input.py`, `taskledger/services/plan_lint.py`, `taskledger/services/plan_review.py`, `taskledger/cli_plan.py`.

## Doctor integrity check

**Trigger**: User runs `taskledger doctor`.

**Flow**:

1. Resolve project paths and locator
2. Check storage layout version against current version
3. Scan all tasks: verify front matter validity, lock/run consistency, active task state
4. Check index staleness (comparing index contents against canonical records)
5. Check for stale locks (expired leases)
6. Collect structured diagnostics with severity, code, message, and repair hints
7. Report diagnostics to user (human text or JSON)

**Key source**: `taskledger/services/doctor.py`, `taskledger/services/doctor_checks/task_checks.py`, `taskledger/services/doctor_checks/project_scan.py`, `taskledger/services/doctor_checks/migration_checks.py`.

## Branch-scoped ledger selection and fork

**Trigger**: Developer creates a long-lived Git branch and runs `taskledger ledger fork REF`.

**Flow**:

1. `ledger fork feature-a` → Creates a new ledger directory under `.taskledger/ledgers/feature-a/`
2. Commits the updated `taskledger.toml` (with new `ledger_ref`) with the branch work
3. Default commands now read/write only the current ledger under `.taskledger/ledgers/<ledger_ref>/`
4. Tasks in different ledgers are isolated; duplicate logical task IDs are expected across ledgers
5. `ledger adopt --from feature-a task-0030` copies a branch-local task into the current ledger when merging

**Result**: Each long-lived branch has its own isolated task ledger. The active ledger is determined by `ledger_ref` in `taskledger.toml`.

**Key source**: `taskledger/cli_ledger.py`, `taskledger/storage/ledger_config.py`, `taskledger/storage/task_store.py`.

## Implementation workspace snapshot lifecycle

**Trigger**: `taskledger implement start` captures a workspace snapshot; `taskledger validate start` enforces it before validation runs.

**Flow**:

1. `implement start` -> Acquires implementation lock, creates an implementation run, calls `capture_workspace_content_snapshot` in `taskledger/services/workspace_snapshot.py`, and persists snapshot metadata on the run.
2. Implementation finishes via `implement finish`. The snapshot is the source of truth for what was implemented.
3. `validate start` -> Calls `compare_implementation_snapshot`. If the current workspace diverges, validation is blocked with a `reason_code` such as `content_snapshot_mismatch` or `legacy_snapshot_mismatch`.
4. `validate start --refresh-implementation-snapshot --reason "..."` -> `refresh_implementation_snapshot` records a new snapshot, appends an `implementation.snapshot.refreshed` event, and resumes the normal validation flow.
5. `implement snapshot refresh --reason "..."` is the same recovery path when called outside `validate start`.

**Result**: Validation only proceeds when the current workspace matches the implementation snapshot; otherwise an explicit refresh with audit trail is required.

**Key source**: `taskledger/services/workspace_snapshot.py`, `taskledger/services/implementation_flow.py`, `taskledger/services/validation_flow.py`, `taskledger/cli_implement.py`.

## Git sync workflow for shared state

**Trigger**: Developer runs `taskledger sync git init` to set up an external sync repo.

**Flow**:

1. `sync git init` → Moves or copies `.taskledger/` content into a dedicated Git repository, updates `taskledger.toml` with `external_dir`
2. `sync preflight` → Checks that no active locks would conflict with a sync operation
3. `sync git commit --message "..."` → Commits current state to the sync repo
4. `sync git export-local` / `sync git import-local` → Exchanges state between the sync repo and the project
5. `sync git status` → Shows working tree status of the sync repo
6. `sync git paths` → Shows resolved paths for the sync repo and project
7. `cd "$(taskledger sync git cd)"` → Opens a shell in the sync repo directory for manual Git operations

**Result**: Taskledger state is stored in a separate Git repository that can be versioned and shared manually. The design intentionally avoids automated push/pull to prevent merge conflicts — users run `git push`/`git pull` directly in the sync repo.

**Key source**: `taskledger/services/git_sync.py`, `taskledger/cli_sync.py`, `taskledger/api/sync.py`.

## Migration, reindex, and doctor interaction

**Trigger**: Developer upgrades taskledger and runs `taskledger doctor`, which reports a storage version mismatch.

**Flow**:

1. `doctor` → Scans project config, storage layout version, task records, indexes, locks, and runs
2. Detects that storage layout version (e.g., v2) is behind current version (v3)
3. Reports diagnostic with severity, code, and repair hint
4. `migrate` → Applies storage layout migrations to upgrade records to current schema
5. Migration code in `taskledger/storage/migrations.py` handles version-to-version upgrades
6. `reindex` → Rebuilds JSON index caches from migrated canonical records
7. `doctor` → Re-run confirms all checks pass

**Result**: Storage layout is upgraded to the current version. Indexes are rebuilt. Doctor passes cleanly.

**Key source**: `taskledger/storage/migrations.py`, `taskledger/services/doctor.py`, `taskledger/services/doctor_checks/migration_checks.py`, `taskledger/domain/states.py`.

## Worker pipeline guided handoff

**Trigger**: Agent runs `taskledger next-action` and receives `worker_pipeline.next_step` in the response.

**Flow**:

1. `next-action` → Returns `worker_pipeline.next_step` with `step_id`, `context_command`, and `handoff_command` hints
2. `pipeline show` → Displays the configured worker pipeline steps and their mapping to lifecycle stages
3. `context --worker spec-reviewer` → Renders a worker-specific context for the spec reviewer step
4. `handoff create --worker code-reviewer` → Creates a handoff with mode and context derived from the worker step configuration
5. Plan todos may be tagged with `worker_step` to associate implementation steps with specific pipeline workers
6. `plan template --with-worker-pipeline` → Generates plan template with worker-tagged todo sections

**Result**: Worker pipeline provides an advisory overlay that guides fresh-context handoffs through sequential worker steps (spec-reviewer, implementer, code-reviewer). It does not add new lifecycle gates — the task lifecycle remains the authoritative workflow.

**Key source**: `taskledger/services/worker_pipeline.py`, `taskledger/cli_pipeline.py`, `taskledger/services/handoff.py`.

# Deployment View

taskledger is a single-node, file-system-based tool. Deployment consists of:

- **Installation**: `pip install taskledger` (PyPI) or local `pip install -e .`
- **Project initialization**: `taskledger init` creates `taskledger.toml` and `.taskledger/` in the project root
- **Runtime**: The CLI runs as a Python process, reading and writing the project `.taskledger/` directory. No daemon, no server.
- **CI integration**: taskledger commands can be run in CI pipelines for status checks, validation, snapshot and export operations, and `taskledger trace` bundles
- **Agent integration**: Agent harnesses invoke taskledger CLI commands as subprocess calls

## Local development deployment

**Node**: Developer workstation or CI runner.

**Software**:

- Python 3.10+
- taskledger (pip installed)
- Host project with `taskledger.toml` config

**Storage**:

- `.taskledger/` directory in project root (Markdown and YAML front matter files)
- `task_sidecars.json` summary index under `.taskledger/ledgers/<ledger_ref>/`
- Project config at `taskledger.toml`

**Network**: None required.

**Installation**: `pip install taskledger` or `pip install -e .` from source. Single entry point: `taskledger` CLI.

# Cross-cutting Concepts

Cross-cutting concerns that span multiple layers:

- **Actor metadata**: Every mutation carries an `ActorRef` (type: agent/user/system, name, role, session, harness). Decisions distinguish user-only actions (approval, waiver) from agent actions.
- **JSON output envelope**: All CLI commands emit a consistent JSON envelope with `ok`, `command`, `result_type`, `result`, `events`, and `warnings` fields when `--json` is passed. Error envelopes add `code`, `message`, `details`, and `remediation`.
- **YAML front matter serialization**: All canonical records use YAML front matter (`---` delimited) for metadata and Markdown for body. Serialization and deserialization live in `taskledger/storage/frontmatter.py`, backed by `ledgercore`.
- **Atomic file writes**: All file writes go through `ledgercore` atomic primitives (temp file, flush, fsync, `os.replace`, directory fsync) to prevent corruption.
- **Action and event logging (default-on)**: Mutations append immutable `TaskEvent` records to the ledger-level `events/` directory under `.taskledger/ledgers/<ledger_ref>/`. Action and event logging is enabled by default; set `[event_logging] enabled = false` to disable new records. Existing records remain readable. Source: `taskledger/storage/events.py`, `taskledger/services/task_events.py`, `taskledger/domain/event.py`.
- **Exit code taxonomy**: Errors map to stable exit codes (0=success, 1=generic, 2=bad input, 3=workflow rejection, 4=lock conflict, 5=missing, 6=storage, 7=validation failed).
- **Opaque cross-ledger references**: Task refs, plan versions, file links, and handoff targets remain opaque strings. Taskledger does not interpret external system identifiers.
- **Read-model reuse**: `view`, `status`, `tree`, and `monitor` commands consume service-level read models. These presentations are read-only and do not bypass lifecycle services.
- **Editable plan input**: `taskledger plan check` is a pure preflight parser in `taskledger/services/plan_input.py`. It rejects malformed YAML, normalizes the `description` alias to `text`, and surfaces indexed issues before any plan upsert. `plan lint` runs additional structural checks; `plan review` renders the approval brief.

## Actor metadata and role semantics

Every mutation carries an `ActorRef` (type: agent/user/system, name, role, session ID, harness ID) and optionally a `HarnessRef` (harness identity, kind, capabilities). The system distinguishes user-only actions (plan approval, criterion waivers, dependency waivers) from agent actions. Actor metadata is persisted in locks, runs, events, and handoff records for audit trails. Source: `taskledger/domain/actor.py` (`ActorRef`, `HarnessRef`), `taskledger/domain/states.py` (`ActorType`, `ActorRole`, `HarnessKind`).

## JSON output envelope contract

When `--json` is passed, every CLI command emits a JSON envelope: `{"ok": bool, "command": str, "result_type": str, "result": ..., "events": [...], "warnings": [...]}`. On error, the envelope includes an `error` object with `code`, `message`, `details`, and `remediation` fields. This shape is a public API contract tested by `tests/test_json_contracts.py`. Exit codes map deterministically to error categories and are part of the public contract.

## YAML front matter serialization

All canonical records are `.md` files with YAML front matter (`---` delimited) containing structured metadata and a Markdown body. Read and write are handled by `read_markdown_front_matter` and `write_markdown_front_matter` in `taskledger/storage/frontmatter.py`, backed by `ledgercore.frontmatter`. Models implement `to_dict()` and `from_dict()` for serialization. Schema version and object type fields enforce contract integrity on read.

## Atomic file writes

All file writes go through `atomic_write_text` (temp file, flush, fsync, `os.replace`, directory fsync) or `atomic_create_text` (`O_CREAT | O_EXCL` for lock files). These primitives come from `ledgercore.atomic` and are re-exported by `taskledger/storage/atomic.py`. This prevents partial writes on crash. Test environments can disable fsync via `TASKLEDGER_TEST_FAST_IO=1` for speed.

## Append-only event log

Mutations append an immutable `TaskEvent` record to the ledger-level `events/` directory under `.taskledger/ledgers/<ledger_ref>/`. Action and event logging is enabled by default; set `[event_logging] enabled = false` in `taskledger.toml` to disable new event records. Existing records remain readable regardless of the setting. Events are never modified or deleted. Each event has a deterministic ID, name (for example `task.created`, `plan.approved`, `lock.acquired`, `validation.check.logged`, `code_review.recorded`, `implementation.snapshot.refreshed`), timestamp, and actor metadata. Events support audit trails, monitor activity, handoff context, and `task transcript` output. Duplicate event detection prevents re-appending on retry. Source: `taskledger/storage/events.py`, `taskledger/services/task_events.py`, `taskledger/services/agent_logging.py`, `taskledger/services/agent_transcripts.py`, `taskledger/domain/event.py`.

## Exit code taxonomy

Stable exit codes for CLI and error classification: 0 (success), 1 (generic failure), 2 (bad input), 3 (workflow rejection - invalid transition, approval required, dependency blocked), 4 (lock conflict - stale lock requires break), 5 (not found or no active task), 6 (storage error or data integrity), 7 (validation failed). Defined in `taskledger/domain/states.py` and `taskledger/errors.py`. Agents and CI pipelines rely on specific codes for automation.

## Editable plan input preflight

Editable plan input is a preflight parser in `taskledger/services/plan_input.py`. It accepts YAML front matter with `goal`, `files`, `test_commands`, `expected_outputs`, `acceptance_criteria`, and `todos`, plus optional `generation_reason` and waiver reason fields. Criterion `description` is normalized to `text` as a compatibility alias. Worker-pipeline configuration in `taskledger.toml` validates `worker_step` todo tags. `taskledger plan check --file plan.md` returns a `plan_input_check` payload with `passed`, `summary`, indexed `issues`, and parsed counts. `plan upsert` consumes the same parser; `plan lint` runs additional structural checks; `plan review` renders the approval brief.

## Implementation workspace snapshot

When `taskledger implement start` is called, `taskledger/services/workspace_snapshot.py` captures a Git and content snapshot of the implementation workspace. The content snapshot (`worktree-content:v1`) records per-path status, kind, size, and content hash for files outside `.taskledger/`. The implementation run persists `workspace_git_commit`, `workspace_dirty`, `workspace_diff_hash`, `workspace_status_hash`, `workspace_snapshot_at`, `workspace_content_hash`, `workspace_paths_hash`, `workspace_entry_count`, `workspace_snapshot_format`, and `workspace_snapshot_ref`. `taskledger validate start` calls `compare_implementation_snapshot` and blocks validation when the current workspace diverges. The sanctioned recovery path is `taskledger implement snapshot refresh --reason "..."`, which records a new snapshot, appends an `implementation.snapshot.refreshed` event, and returns a structured payload with `old_snapshot` and `new_snapshot` details.

## Durable code-review evidence

Code review is durable evidence attached to a task. A record captures result, summary/body, reviewer and harness, implementation run, worker step, handoff, and optional Git working-tree or commit metadata. Review records are append-only and may be recorded after a task reaches `done`. They do not create a lifecycle stage, reopen completed work, replace acceptance criteria, or weaken validation completion rules. Source: `taskledger/domain/review.py`, `taskledger/services/code_review.py`. Test coverage: `tests/test_code_reviews.py`.

# Architecture Decisions

Key architecture decisions documented as ADR records:

- **ADR-1**: Markdown and YAML front matter as canonical format (not JSON, not SQLite)
- **ADR-2**: Sidecar summary index as derived rebuildable cache (not authoritative)
- **ADR-3**: Explicit lifecycle gates with policy decisions (not free-form state)
- **ADR-4**: Typer CLI framework (not argparse, not Click directly)
- **ADR-5**: Task bundle directory layout (not single-file index)
- **ADR-6**: External skill packaging (skills outside the Python package)

## Markdown/YAML front matter as canonical format

**Document version:** 1

## Context

Need a storage format for task state that is durable, human-readable, and version-controllable. Agents and humans need to inspect state without running taskledger.

## Decision

Store all records as Markdown files with YAML front matter (`---` delimited). Metadata (ID, type, status, dates) goes in YAML; free-form content goes in Markdown body.

## Consequences

- Positive: State is Git-diffable, human-readable, and editable in any text editor.
- Positive: No database dependency.
- Negative: Parsing is slower than binary formats for large datasets.
- Negative: Schema evolution requires careful validation on read.

## Alternatives considered

- SQLite: Faster queries but opaque binary format, harder to version-control and inspect.
- Pure JSON: Easier parsing but not human-friendly for long-form content (plan bodies, handoff contexts).
- Single JSON index file: Rejected due to merge conflicts and scalability concerns.

## Sidecar summary index as derived rebuildable cache

**Document version:** 1

## Context

Listing tasks, locks, and dependencies requires scanning many front matter files. Need a way to speed up queries without adding a database.

## Decision

Maintain JSON index files under `.taskledger/indexes/` as derived caches. They are rebuilt from canonical records by `taskledger reindex` and checked by `doctor indexes`. They are never the source of truth.

## Consequences

- Positive: Fast list/query operations without parsing all front matter files.
- Positive: Indexes can always be rebuilt from canonical source.
- Negative: Indexes can become stale after manual edits or crashes.
- Negative: `reindex` must be run after out-of-band changes.

## Alternatives considered

- No indexes (always scan files): Simpler but too slow for large projects.
- SQLite index: More robust but adds complexity and dependency.
- In-memory cache: Lost on process restart, not durable.

## Explicit lifecycle gates with policy decisions

**Document version:** 1

## Context

Without lifecycle gates, agents could skip review and implement without approval. Need enforceable transitions between task stages.

## Decision

Implement lifecycle gates as pure policy functions in `taskledger/domain/policies.py`. Each gate function takes a `PolicyContext` (task, lock, run) and returns a `Decision` (allowed, code, message, exit_code). The state machine in `states.py` defines `ALLOWED_STAGE_TRANSITIONS`. Services call policies before mutating state.

## Consequences

- Positive: Gate logic is fully testable without I/O setup.
- Positive: User-only actions (approval, waivers) are enforced at the policy level.
- Negative: Services must gather full context before calling policies.

## Alternatives considered

- Free-form state changes: Rejected — agents could bypass review.
- Database triggers: Rejected — adds database dependency and complexity.
- CLI-only validation: Rejected — API and programmatic users would bypass gates.

## Typer CLI framework

**Document version:** 1

## Context

Need a CLI framework that supports subcommand groups, type-annotated parameters, and integrates with Click ecosystem extensions.

## Decision

Use Typer (built on Click) for the CLI. Typer provides type-annotated parameters, subcommand groups, and automatic help generation. The root app in `cli.py` registers nested Typer apps for each command family: `task`, `plan`, `question`, `implement`, `validate`, `todo`, `intro`, `file`, `link`, `require`, `lock`, `handoff`, `release`, `storage`, `sync`, `doctor`, `repair`, `migrate`, `actor`, `harness`, `ledger`, `pipeline`, `review`, `config`, and `ref`.

## Consequences

- Positive: Clean type-annotated parameter definitions with `Annotated` types.
- Positive: Click ecosystem compatibility (middleware, testing).
- Negative: Typer and Click are both runtime dependencies.

## Alternatives considered

- Pure Click: More verbose parameter definitions, no type annotation inference.
- Argparse: Standard library but lacks subcommand ergonomics and type inference.
- Docopt: Declarative but harder to compose nested subcommands.

## Task bundle directory layout

**Document version:** 1

## Context

Need a storage layout that scales to many sidecar collections per task (plans, runs, locks, todos, questions, changes, checks, handoffs, links, code reviews) while keeping each record individually addressable. Events are stored at ledger level, not per-task, and are enabled by default.

## Decision

Use a directory-per-task layout (v2 bundle) under `.taskledger/ledgers/<ledger_ref>/`. Each task gets a directory containing the task record (Markdown) and subdirectories for sidecar collections. JSON indexes, including the `task_sidecars.json` summary, are derived caches at the ledger level. Event records are stored in the ledger-level `events/` directory (not per-task) and are written by default; set `[event_logging] enabled = false` to disable. The current storage layout version is `TASKLEDGER_STORAGE_LAYOUT_VERSION = 3`.

## Consequences

- Positive: Each record is a single file - easy to read, edit, and version-control.
- Positive: Sidecar collections are independently addressable.
- Positive: The sidecar summary index keeps common read paths fast.
- Negative: Many small files create directory overhead on very large projects.

## Alternatives considered

- Single JSON index file: Merge conflicts, scalability, not human-readable.
- Database (SQLite): Opaque, harder to inspect and version-control.

## External skill packaging

**Document version:** 1

## Context

Agent skill files (SKILL.md) provide integration instructions for coding agents. Need to decide where they live relative to the Python package.

## Decision

Skills live under `skills/taskledger/` in the repository, outside the `taskledger` Python package. They are not packaged as Python package data, not loaded via `importlib.resources`, and not distributed via PyPI as part of the package.

## Consequences

- Positive: Clean separation between tool functionality and agent integration instructions.
- Positive: Skills can be versioned independently and distributed through different channels.
- Negative: Skill installation is a separate step from package installation.

## Alternatives considered

- Package skills as package data: Coupling skill version to package version, harder to update independently.
- Load skills via importlib.resources: Adds packaging complexity and coupling.

# Quality Requirements

Quality requirements that gate architectural decisions:

- **Data integrity**: Atomic writes and strict front matter validation prevent corrupt state. Partial writes are impossible due to `os.replace` semantics.
- **CLI exit code contract**: Exit codes are stable and tested. Agents and CI pipelines rely on specific codes for automation.
- **JSON envelope stability**: The JSON output shape (`ok`, `command`, `result_type`, `result`) is a public API contract. Breaking changes require explicit versioning.
- **Lifecycle gate correctness**: Every stage transition is validated by policy functions with full test coverage of error paths.
- **Export/import round-trip**: Archives preserve all state. Import into a fresh workspace reproduces the original taskledger state exactly.
- **Editable plan input preflight**: `taskledger plan check` returns a structured payload with `passed`, `summary`, indexed `issues`, and parsed counts. Lint and review are gate layers; preflight catches them earlier.
- **Implementation snapshot fidelity**: `validate start` blocks when the current workspace diverges from the implementation snapshot. `implement snapshot refresh --reason ...` is the only sanctioned recovery path and records an audit trail.

## Quality Requirements Overview

| Title                                                     | Category    | Measure | Scenarios |
| --------------------------------------------------------- | ----------- | ------- | --------- |
| Data integrity: atomic writes and front matter validation | reliability |         |           |
| CLI exit code contract stability                          | reliability |         |           |
| JSON envelope output stability                            | reliability |         |           |
| Lifecycle gate correctness                                | reliability |         |           |
| Export/import round-trip fidelity                         | reliability |         |           |

## Quality Scenarios

<!-- archledger: no accepted records for this section yet -->

# Risks and Technical Debt

Known risks and areas of technical debt:

- **Storage scaling with many tasks**: Each task is a directory with multiple sidecar files. Very large projects (hundreds of tasks) may see slowdowns in list and query operations because the `task_sidecars.json` summary index is rebuilt from file scans on miss and updated on writes. The per-task sidecar index keeps the common read path fast but does not eliminate directory overhead.
- **Migration surface between storage versions**: The storage layout is currently v3 (`TASKLEDGER_STORAGE_LAYOUT_VERSION` in `taskledger/domain/states.py`). Migration code in `taskledger/storage/migrations.py` adds complexity. Future format changes must maintain backward compatibility or ship migration steps.
- **Service boundary erosion**: Some service modules (notably `tasks.py` and a few focused modules) have grown large. The service layer has no formal interface contracts; boundaries are enforced by convention and the `tests/test_service_boundaries.py` whitelist in `docs/service_boundary_whitelist.md`.
- **Implementation snapshot drift**: Workspace snapshots are a strong invariant but require explicit refresh after environment changes. `taskledger next-action` and `validate start` surface mismatch diagnostics; the recovery path is `implement snapshot refresh --reason ...`.
- **Editable plan input compatibility**: `description` is accepted as an alias for `text` on acceptance criteria; strict mode promotes unknown-field findings to errors to prevent silent structured-data loss.
- **Growing dependency surface**: The runtime dependency set is small (`typer`, `click`, `PyYAML`, `tomli`, `ledgercore`) but new dependencies must be justified by core features rather than optional presentations.

## Risk Overview

| Title                                      | Severity | Probability | Mitigation                                                                                        | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ------------------------------------------ | -------- | ----------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Storage scaling with many tasks            | medium   | medium      | Run reindex after bulk changes; consider task archival for completed work.                        | Each task is a directory with multiple sidecar files. Projects with hundreds of tasks may see slowdowns in list and query operations due to file system scanning. The `task_sidecars.json` summary index is updated in place by per-task sidecar writes and is rebuilt on miss, which keeps the common read path fast. Mitigation: run `taskledger reindex` after bulk changes; consider task archival for completed work; rely on the sidecar summary index for navigation.     |
| Migration surface between storage versions | medium   | medium      | Doctor checks detect version mismatches; migration checks flag incompatible records.              | The storage layout is currently v3 (`TASKLEDGER_STORAGE_LAYOUT_VERSION` in `taskledger/domain/states.py`). Migration code in `taskledger/storage/migrations.py` adds complexity. Future format changes must maintain backward compatibility or provide migration steps. Mitigation: `taskledger doctor` checks detect version mismatches; migration checks in `taskledger/services/doctor_checks/migration_checks.py` flag incompatible records.                                 |
| Service boundary erosion                   | medium   | medium      | test_service_boundaries.py whitelist tracks allowed cross-module imports and fails on violations. | Some service modules (notably `taskledger/services/tasks.py`) have grown large. The current long-function whitelist includes entries such as `taskledger/cli_sync.py::register_sync_commands` and `taskledger/services/doctor_checks/task_checks.py::scan_task_integrity`. The service layer has no formal interface contracts; boundaries are enforced by convention and the whitelist in `docs/service_boundary_whitelist.md` exercised by `tests/test_service_boundaries.py`. |
| Growing dependency count                   | medium   | medium      | Small dependency set (typer, PyYAML, tomli); each justified by a core feature.                    | The runtime dependency set is small (`typer`, `click`, `PyYAML`, `tomli` on Python <3.11, and `ledgercore` for atomic I/O, JSON I/O, YAML I/O, front matter parsing, and cross-ledger ref parsing). Each dependency is justified by a core feature. Risk is low as long as new dependencies are not introduced without explicit justification, and as long as `ledgercore` remains the boundary for low-level primitives.                                                        |

# Glossary

Domain terms used throughout taskledger. The full glossary lives in the per-term `glossary-NNNN` records under `.archledger/records/glossary/`. Each term is stored as a record with `term`, `definition`, and reference metadata rather than in this section body.

| Term                 | Definition                                                                                                    |
| -------------------- | ------------------------------------------------------------------------------------------------------------- |
| Task                 | The primary unit of work with a managed lifecycle through planning, implementation, and validation stages.    |
| Plan                 | A proposed implementation plan with acceptance criteria that gates implementation start.                      |
| Run                  | A record of an active work session (planning, implementation, or validation) paired with a lock.              |
| Lock                 | A concurrency control mechanism preventing simultaneous actors on the same task stage.                        |
| Handoff              | A context transfer record enabling a different actor to continue work from where the previous actor left off. |
| Todo                 | A concrete implementation step materialized from the accepted plan; gates implementation completion.          |
| Acceptance Criterion | A testable condition that gates task completion during validation.                                            |
| Actor                | The entity performing an action, classified as agent, user, or system.                                        |
| Harness              | The execution environment running taskledger (agent harness, manual terminal, or CI).                         |
| Stage                | A position in the task lifecycle state machine (draft, planning, plan_review, approved, etc.).                |
| Sidecar              | A collection of related records (todos, links, plans, etc.) attached to a task.                               |
| Front Matter         | The YAML metadata block at the top of a canonical record file, delimited by ---.                              |
| Worker Pipeline      | An optional advisory overlay that guides fresh-context handoffs through sequential worker steps.              |

## Ledgercore 0.3 storage boundary

Canonical project discovery, project identity, checkout identity, storage-class resolution, scope resolution, and physical mount resolution belong to Ledgercore. Taskledger owns manifest registration mutation, config validation, data state, record layout, migration planning, backup, and verification.
