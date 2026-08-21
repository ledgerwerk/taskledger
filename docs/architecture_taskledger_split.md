# Taskledger architecture

`taskledger` is a task-first CLI and Python package for staged coding work.
The canonical workflow is:

```text
task -> plan -> approval -> implement -> validate -> done
```

## Owning layers

- `taskledger/domain/` owns lifecycle enums, policies, record models, and the
  canonical `TASKLEDGER_STORAGE_LAYOUT_VERSION` constant.
- `taskledger/storage/` owns persisted task bundles, locks, and the
  `task_sidecars.json` summary index. Low-level atomic I/O, JSON I/O, YAML
  I/O, front matter parsing, and cross-ledger ref parsing are delegated to
  `ledgercore`.
- `taskledger/services/` owns task lifecycle orchestration, including
  `plan_input.py`, `plan_lint.py`, `plan_review.py`, `planning_flow.py`,
  `implementation_flow.py`, `workspace_snapshot.py`, `validation_flow.py`,
  `handoff.py`, `doctor.py`, and `navigation.py`.
- `taskledger/api/*` exposes stable public wrappers.
- `taskledger/cli*.py` wires Typer commands only.

## Storage model

Markdown records are canonical. Task, plan, and run reads come from those
records directly. Canonical Taskledger uses four Ledgercore mounts: durable
`data`, checkout-local `runtime`, diagnostic `logs`, and rebuildable cache
`indexes`. The default data mount is external sibling storage; runtime and logs
use user-data and indexes use cache. Local machine overrides live in
`.ledger/ledger.local.toml`.

Active/session state and workspace snapshot manifests are runtime data. Raw event
and agent-command logs are diagnostic logs. Small semantic run summaries and
task records remain in data. Indexes are always derived from data and may be
deleted and rebuilt without task-history loss. The historical `.taskledger/`
layout and root `taskledger.toml` are compatibility and migration inputs only.

## Lifecycle flow

`plan start` opens planning. `plan guidance` reports the active project
planning profile. `plan template` writes a fresh plan skeleton, and
`plan check --file plan.md` runs the preflight parser in
`taskledger/services/plan_input.py` without mutating state. `plan upsert`
persists the plan; `plan lint` surfaces blocking issues; `plan review`
produces the approval brief; `plan accept --note "..."` records the
user-only decision.

`implement start` acquires a lock, starts a run, and captures a workspace
snapshot through `taskledger/services/workspace_snapshot.py`. `validate start`
blocks when the current workspace diverges; `implement snapshot refresh --reason "..."` is the only sanctioned recovery path. Validation checks
gate completion. Code-review records extend traceability as append-only
evidence without creating a new lifecycle stage.

## Command surface

The supported command groups are `task`, `plan`, `question`, `implement`,
`validate`, `todo`, `intro`, `file`, `link`, `require`, `release`, `lock`,
`handoff`, `context`, `actor`, `harness`, `view`, `tree`, `next-action`,
`can`, `search`, `grep`, `symbols`, `deps`, `doctor`, `repair`, `reindex`,
`migrate`, `init`, `status`, `export`, `import`, `snapshot`, `storage`,
`sync`, `ledger`, `pipeline`, `commands`, `review`, `monitor`, `usage`, and
`ref`. The authoritative source for the complete command surface and flags
is `taskledger/command_inventory.py` and `docs/command_contract.md`.

## Architecture records

Arc42 architecture records live under the canonical Archledger data mount
`.ledger/archledger/data/` and are the source of `docs/architecture.md`. Skills
(`skills/taskledger/SKILL.md`) and `docs/architecture_taskledger_split.md` live
outside the Python package and outside the Archledger build output.
