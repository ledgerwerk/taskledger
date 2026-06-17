# AGENTS.md

This file defines how coding agents should work in the `taskledger` repository.

`taskledger` is a task-first Python CLI and library for durable coding-task state. Its core contract is: create a task, plan it, get explicit user approval, implement against todos, validate against acceptance criteria, and preserve enough state for fresh-context or different-harness continuation.

## 1. Communication

- Assume the user is technically strong.
- Be direct, concrete, and brief.
- Do not explain obvious Python, Typer, YAML, dataclass, pytest, ruff, mypy, or packaging basics.
- Do not narrate trivial edits.
- Push back when a request would weaken lifecycle gates, lock semantics, JSON contracts, storage invariants, or public APIs.
- Ask a clarifying question only when ambiguity is likely to cause the wrong behavior or an irreversible contract change.
- Otherwise, proceed with the smallest correct change.
- Report results as: changed, verified, not verified, risks.

## 2. Operating Principles

### 2.1 Prefer the smallest correct change

Priorities:

1. lifecycle behavior is correct
2. workflow gates are preserved
3. behavior is verified
4. intent is obvious in code
5. changes stay in the owning layer
6. CLI and public API contracts stay stable unless explicitly changed

Avoid:

- speculative abstractions
- broad rewrites during feature work
- unrelated formatting or cleanup
- casual command, flag, status, field, or JSON shape changes
- weakening approval, lock, todo, dependency, or validation gates
- reintroducing removed legacy surfaces
- adding migration code unless requested
- creating commits

### 2.2 Treat taskledger state as product data

Preserve these invariants:

- `.taskledger/` is durable project state.
- Markdown records with YAML front matter are canonical.
- JSON indexes are rebuildable caches.
- Active stages require a matching running run and a visible lock.
- Stale locks require explicit break/repair flow.
- User-only decisions remain user-only.
- Repair commands are exceptional, not normal workflow.

### 2.3 Work as a verifiable loop

For each task:

1. identify the owned layer
2. make the smallest coherent change
3. add or update focused tests
4. run the narrowest useful verification
5. widen verification only when the change crosses layers

Examples:

- lifecycle gate bug -> `taskledger/domain/policies.py` or `taskledger/services/tasks.py` plus lifecycle/policy tests
- task-first CLI bug -> relevant `taskledger/cli_*_v2.py` plus CLI contract tests
- JSON envelope bug -> `taskledger/cli_common.py` plus JSON contract tests
- storage layout bug -> `taskledger/storage/task_store.py` plus storage/layout tests
- lock behavior bug -> policies, task service, or lock storage plus lock tests
- docs or skill drift -> docs, skill files, command example tests, and docs/skill tests

## 3. Project Shape

### 3.1 What taskledger is

`taskledger` provides:

- task-first CLI commands for staged coding work
- Python API wrappers around the task services
- durable Markdown/YAML records
- explicit planning, approval, implementation, and validation gates
- todo lists that gate implementation completion
- acceptance criteria and validation checks that gate validation completion
- locks for active work
- handoffs for fresh-context, human/agent, and harness transitions
- doctor/repair commands for integrity checks and exceptional recovery
- search/context/dossier commands for agent-friendly work continuation

Taskledger stores task-local work state and opaque links. Cross-ledger
semantics belong to an organizer such as ledgerdeck. Use `taskledger link`
or `taskledger file` for references to external artifacts; taskledger does
not interpret those references.

Canonical workflow:

```text
task -> plan -> approval -> implement -> validate -> done
```

This workflow is the product contract, not decoration.

### 3.2 Important code surfaces

Use the owning layer before editing.

- `taskledger/cli.py` — root Typer app, global options, command groups, top-level commands
- `taskledger/cli_common.py` — CLI state, JSON envelopes, human rendering, error/exit-code mapping
- `taskledger/cli_task.py` — `task ...`
- `taskledger/cli_plan.py` — `plan ...`
- `taskledger/cli_question.py` — `question ...`
- `taskledger/cli_implement.py` — `implement ...`
- `taskledger/cli_validate.py` — `validate ...`
- `taskledger/cli_misc.py` — todo, intro, file, link, require, lock, handoff, doctor/repair helpers
- `taskledger/api/*.py` — public API wrappers
- `taskledger/services/tasks.py` — core lifecycle service operations
- `taskledger/services/handoff.py` and `taskledger/services/handoff_lifecycle.py` — handoff rendering and state changes
- `taskledger/services/doctor.py` — integrity inspection
- `taskledger/domain/models.py` — persisted domain records and serialization
- `taskledger/domain/policies.py` — gate decisions and permission checks
- `taskledger/domain/states.py` — status/stage normalization and transitions
- `taskledger/storage/task_store.py` — canonical v2 task bundle layout
- `taskledger/storage/*.py` — storage-specific modules
- `taskledger/errors.py` — public exception taxonomy and exit codes
- `taskledger/command_inventory.py` — registered command metadata
- `skills/taskledger/SKILL.md` — external agent skill protocol
- `docs/command_contract.md` — CLI grammar contract
- `API.md`, `docs/api.md`, `docs/public_surface.md` — public API documentation

## 4. Packaging Rule for Skills

Skills must stay outside the Python package.

Required direction:

- keep the canonical skill under `skills/taskledger/`
- do not mirror skills under `taskledger/skills/`
- do not include skills as Python package data
- do not use `importlib.resources` to expose skills from the `taskledger` package
- remove existing `taskledger/skills/` content as legacy residue when working on packaging cleanup
- update tests/docs so they expect external skills, not packaged skills

The Python package should provide the CLI/library. Skill installation/distribution belongs outside the package artifact.

## 5. CLI Contract

### 5.1 Task-first command grammar

Preserve the task-first command families:

```text
taskledger task ...
taskledger plan ...
taskledger question ...
taskledger implement ...
taskledger validate ...
taskledger todo ...
taskledger intro ...
taskledger file ...
taskledger link ...
taskledger require ...
taskledger lock ...
taskledger handoff ...
taskledger doctor ...
taskledger repair ...
```

Root commands such as `init`, `status`, `view`, `context`, `next-action`, `can`, `reindex`, `export`, `import`, `snapshot`, `search`, `grep`, `symbols`, and `deps` are also intentional.

Do not reintroduce removed legacy groups or aliases.

### 5.2 Active-task defaulting

Task-scoped commands should default to the active task where that is the established contract.

Rules:

- use `--task` for explicit override
- do not add positional task refs to task-scoped subcommands
- no active task should produce a clear structured error where required
- active task state must survive export/import

### 5.3 JSON output

`--json` is a root option and a machine-readable contract.

When touching JSON:

- preserve the success envelope shape
- preserve error envelope shape
- preserve `ok`, `command`, `result_type`, `result`, `events`, `warnings`, and error fields where applicable
- preserve stable exit-code semantics
- test payload shape and exit code together
- do not force consumers to parse human text

### 5.4 Human output

Human output should stay concise and stable. Do not casually change line order, labels, or wording that tests or agents may rely on.

## 6. Lifecycle Contracts

### 6.1 Planning

Planning must start before proposing a plan.

Preserve:

- planning lock/run creation
- plan proposal as a durable record
- acceptance criteria persistence
- structured todo extraction/materialization
- required-question gating
- stale answer detection
- plan regeneration after answers
- agent cannot approve the plan by default

### 6.2 Approval

Approval is a user decision.

Preserve:

- approval metadata
- accepted plan version linkage
- blockers for missing criteria unless explicitly allowed with reason
- blockers for open questions unless explicitly allowed with reason
- blockers for empty todos unless explicitly allowed with reason
- materialization of plan todos only once

### 6.3 Implementation

Implementation requires an accepted plan and valid lifecycle state.

Preserve:

- implementation lock/run creation
- implementation log and change records
- command execution artifacts
- deviation and artifact records
- todo completion gate on finish
- active lock/run remaining active when finish is blocked

### 6.4 Validation

Validation requires a finished implementation.

Preserve:

- validation lock/run creation
- criterion checks by canonical criterion ID
- latest-check-wins semantics
- blocker reporting for unchecked mandatory criteria
- waiver behavior with user actor metadata
- mandatory todo blockers during validation completion

### 6.5 Locks

Locks are part of the lifecycle state, not advisory comments.

Preserve:

- one active stage per task
- matching lock/run/stage semantics
- explicit stale-lock break/repair flow with diagnostics on `lock show` and `next-action`
- audit record for broken locks
- no silent lock removal
- doctor detection for lock/run inconsistencies

## 7. Storage Contracts

### 7.1 Canonical layout

The v2 task bundle layout is canonical. Do not return to one large JSON item index.

Preserve:

- task bundle directories
- task Markdown record as canonical task metadata/body
- sidecar collections for todos, links, requirements, plans, questions, runs, changes, artifacts, handoffs, and audit data
- JSON indexes as rebuildable caches only
- deterministic IDs where tests expect them
- schema/file-version validation

### 7.2 Front matter

Markdown/YAML records must remain strict enough to catch corruption.

When changing model fields:

- update serialization and deserialization together
- preserve unknown-version rejection
- preserve required-field validation
- update schema/model tests
- update export/import if persisted state changes

### 7.3 Events

Events are an audit trail.

Preserve:

- append-only behavior
- stable event IDs
- chronological sorting expectations
- duplicate event detection
- event refs in JSON envelopes where applicable

## 8. Public API Contracts

The public API lives mainly under `taskledger/api/*.py` and should remain stable unless explicitly changed.

Preserve:

- function names and parameter meanings
- returned dictionary/list shapes
- domain model serialization semantics
- public exception types from `taskledger/errors.py`
- `taskledger.__init__` exports
- `taskledger.__main__` entrypoint behavior
- `py.typed`

If a task requires breaking an API, call it out explicitly and update API docs/tests in the same change.

## 9. Handoff and Context Contracts

Handoffs exist so work can continue in a fresh context, different harness, or different actor.

Preserve:

- handoff modes: planning, implementation, validation, review/full where supported
- create/list/show/claim/close/cancel lifecycle
- intended actor/harness metadata
- generated context sections for task, plan, todos, questions, locks/runs, implementation summary, validation status, and required output
- lock transfer/release semantics

Do not make handoff content pretty at the cost of losing required state.

## 10. Actor Rules

Actor metadata matters.

Preserve distinctions between:

- user
- agent
- system

Preserve role semantics for:

- planner
- implementer
- validator
- reviewer

Do not allow an agent default to perform user-only approval/waiver decisions unless an explicit escape hatch already exists and is tested.

## 11. Docs and Skill Rules

Docs, examples, command inventory, and skill files must agree.

When changing commands or workflow behavior, update as needed:

- `README.md`
- rst files in `docs/`
- `API.md`
- `skills/taskledger/SKILL.md`
- `taskledger/command_inventory.py`
- tests that lint docs and skill content

Do not document commands that are not registered.
Do not leave examples using removed aliases.
Do not package skills inside `taskledger/`.

## 12. Testing Expectations

### 12.1 Minimum rule

Every non-trivial behavior change needs verification.

Prefer the test closest to the changed logic.

### 12.2 Regression paths to test

Include error paths when relevant:

- no active task
- wrong lifecycle stage
- missing accepted plan
- missing acceptance criteria
- open required questions
- stale answered questions
- open mandatory todos
- unknown criterion refs
- unchecked mandatory validation criteria
- lock conflict
- stale lock requiring explicit break
- invalid actor role
- invalid status/stage values
- corrupt front matter
- export/import preservation
- JSON and human output modes

### 12.3 Verification command progression

Start narrow. Expand only when needed. Try to run specific test files first,
only one example for a single pytest is given, figure it out which test to run.

```bash
pytest tests/test_domain_policies.py
pytest

ruff check --config=.ruff.toml .
ruff format --check .
mypy taskledger
```

Run `ruff check` when touching Python code.
Run `mypy taskledger` when changing typed public or core logic.
Run docs/skill/example tests when touching docs, commands, command inventory, or skills.

## 13. Code Style

- Follow existing style first.
- Keep functions focused.
- Prefer explicit names over clever compression.
- Add type hints for new or changed public functions.
- Keep public exception taxonomy stable.
- Avoid new dependencies unless explicitly requested.
- Do not reformat unrelated files.
- Do not rename public symbols without a strong reason.
- Do not use git commands that create commits or rewrite history.

## 14. Good Agent Work

A strong change usually:

- edits the owning layer
- preserves lifecycle gates
- preserves active-task and task-first command contracts
- preserves JSON envelopes and exit codes
- preserves storage invariants
- keeps skills outside the package
- updates docs/skill/examples when commands change
- adds focused tests
- runs targeted verification first
- states what was not verified

## 15. Avoid

- CLI-only patches for lower-layer bugs
- changing JSON shape without tests
- changing lifecycle status strings casually
- silent lock cleanup
- bypassing user approval semantics
- allowing validation to pass without required evidence
- reintroducing legacy commands
- packaging skills into `taskledger`
- broad style churn
- mixing refactors with behavior changes
