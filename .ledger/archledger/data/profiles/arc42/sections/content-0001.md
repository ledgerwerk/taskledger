---
schema_version: 4
id: content-0001
type: section
section: introduction_and_goals
title: Introduction and Goals
order: 10
status: accepted
body_format: markdown
kind: content
version: 4
---
## Current canonical storage boundary

The current canonical design uses the schema-3 Ledgercore project at `.ledger/ledger.toml` with Taskledger configuration at `.ledger/task/config.toml`. Taskledger mounts are separated into authoritative durable `data`, checkout-local `runtime`, diagnostic `logs`, and rebuildable cache `indexes`. Canonical initialization never creates `.taskledger/` or root `taskledger.toml`; those names are legacy migration inputs only.

Taskledger operational state is resolved outside the application source repository by default. `.ledger/ledger.local.toml` is a machine-local override and `.taskledger/` is ignored as legacy residue. The legacy `.taskledger` layout described in older sections remains compatibility and migration material, not the canonical storage design.

Taskledger is a task-first durable state layer for staged coding work. It provides a Python CLI and library that manages the full lifecycle of coding tasks: creation, planning, user approval, implementation, validation, and completion.

The system is designed for use by both human developers and automated coding agents. Its primary goals are:

- **Durable task state**: Every task, plan, run, lock, todo, and validation check is persisted as a Markdown record with YAML front matter in the project Ledgercore data mount. State survives process restarts, context switches, and handoffs between actors.
- **Explicit lifecycle gates**: Transitions between stages (draft -> planning -> plan_review -> approved -> implementing -> implemented -> validating -> done) are enforced by policy decisions. User approval is required before implementation begins. Validation checks gate completion.
- **Fresh-context handoffs**: Agents and humans can create, claim, and close handoff records that capture enough context (task state, plan, todos, questions, lock status) for a fresh process to continue work without reading the entire history.
- **Machine-readable output**: Every CLI command supports `--json` for structured output with a stable envelope shape (`ok`, `command`, `result_type`, `result`, `events`, `warnings`) and deterministic exit codes.
- **Opaque cross-ledger references**: Task-ledger task, plan, file, and link references remain opaque strings. Taskledger does not interpret ledgercore global refs, archledger IDs, or other external system identifiers.

The canonical workflow is:

```text
task -> plan -> approval -> implement -> validate -> done
```

This workflow is the product contract, not decoration. Deviations from this flow require explicit user decisions or repair commands.
