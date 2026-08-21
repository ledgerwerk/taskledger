---
schema_version: 4
id: content-0004
type: section
section: solution_strategy
title: Solution Strategy
order: 40
status: accepted
body_format: markdown
kind: content
version: 5
---

Taskledger uses a layered architecture with clear dependency direction: upper layers depend on lower layers, never the reverse.

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

`docs/architecture.md` is generated from Archledger source records. Do not edit it directly.

- **Edit**: `.ledger/archledger/data/profiles/arc42/sections/*.md` for section content and `.ledger/archledger/data/records/**/*.md` for individual records.
- **Regenerate**: Run `archledger build` to regenerate `docs/architecture.md`.
- **Verify**: Run `archledger check` and `pytest -q tests/test_docs_and_skill.py tests/test_service_boundaries.py` after changes.
- **Authoritative source**: The Archledger records under `.ledger/archledger/data` are the single source of truth for architecture documentation. `docs/architecture_taskledger_split.md` is a concise human-maintained summary.
