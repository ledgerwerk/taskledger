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
version: 2
---

The top-level building block is the **taskledger system**, decomposed into five black-box components:

1. **CLI Layer** — Handles command parsing, task reference resolution, and output rendering. Command families cover the canonical lifecycle plus `review`, `config`, task archive operations, transfer and sync, diagnostics, the `monitor` observer, and the `pipeline` overlay.
2. **API Layer** — Provides stable Python function wrappers around service operations.
3. **Services Layer** — Orchestrates lifecycle flows, plan input validation, plan review, handoffs, snapshot capture, navigation, doctor checks, worker pipelines, archival, code-review evidence, event logging, exports, dashboard assembly, and ready-work inspection.
4. **Domain Layer** — Defines models, state machines, and policy decisions.
5. **Storage Layer** — Manages file system persistence and layout. Low-level primitives (atomic writes, JSON, YAML, front matter, refs) are delegated to `ledgercore`.

Data flows strictly downward: CLI -> Services -> Domain + Storage. The API layer calls Services directly. The Domain layer has no dependencies on Storage or Services.

Each task is stored as a **task bundle directory** under `.taskledger/ledgers/<ledger_ref>/` containing the task record (Markdown) and sidecar collections for plans, runs, locks, todos, questions, changes, checks, handoffs, links, and code reviews. Mutations append immutable `TaskEvent` records to the ledger-level `events/` directory. Action and event logging is enabled by default; set `[event_logging] enabled = false` in `taskledger.toml` to disable new event records. Existing records remain readable regardless. A `task_sidecars.json` summary index under the same ledger path is maintained as a derived cache of sidecar counts and lock summaries.
