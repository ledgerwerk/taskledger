---
schema_version: 4
id: content-0005
type: section
section: building_block_view
title: Building Block View
order: 50
status: accepted
body_format: markdown
kind: content
version: 3
---

The top-level building block is the **taskledger system**, decomposed into five black-box components:

1. **CLI Layer** — Handles command parsing, task reference resolution, and output rendering. Command families cover the canonical lifecycle plus `review`, `config`, task archive operations, transfer and sync, diagnostics, the `monitor` observer, and the `pipeline` overlay.
2. **API Layer** — Provides stable Python function wrappers around service operations.
3. **Services Layer** — Orchestrates lifecycle flows, plan input validation, plan review, handoffs, snapshot capture, navigation, doctor checks, worker pipelines, archival, code-review evidence, event logging, exports, dashboard assembly, and ready-work inspection.
4. **Domain Layer** — Defines models, state machines, and policy decisions.
5. **Storage Layer** — Manages file system persistence and layout. Low-level primitives (atomic writes, JSON, YAML, front matter, refs) are delegated to `ledgercore`.

Data flows strictly downward: CLI -> Services -> Domain + Storage. The API layer calls Services directly. The Domain layer has no dependencies on Storage or Services.

Each task is stored as a **task bundle directory** at `<data-root>/ledgers/<ledger_ref>/tasks/<uuidv7>/`, containing `task.md` and its sidecar collections. The UUIDv7 is the stable storage identity; `task-####` remains the derived user-facing task alias. Mutations append immutable `TaskEvent` records to the ledger-level `events/` directory. Action and event logging is enabled by default; set the project event-logging configuration to disable new event records. Existing records remain readable regardless. Task and sidecar indexes are derived caches in the configured rebuildable indexes mount.
