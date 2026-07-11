---
schema_version: 4
id: content-0008
type: section
section: cross_cutting_concepts
title: Cross-cutting Concepts
order: 80
status: accepted
body_format: markdown
kind: content
version: 2
---

Cross-cutting concerns that span multiple layers:

- **Actor metadata**: Every mutation carries an `ActorRef` (type: agent/user/system, name, role, session, harness). Decisions distinguish user-only actions (approval, waiver) from agent actions.
- **JSON output envelope**: All CLI commands emit a consistent JSON envelope with `ok`, `command`, `result_type`, `result`, `events`, and `warnings` fields when `--json` is passed. Error envelopes add `code`, `message`, `details`, and `remediation`.
- **YAML front matter serialization**: All canonical records use YAML front matter (`---` delimited) for metadata and Markdown for body. Serialization and deserialization live in `taskledger/storage/frontmatter.py`, backed by `ledgercore`.
- **Atomic file writes**: All file writes go through `ledgercore` atomic primitives (temp file, flush, fsync, `os.replace`, directory fsync) to prevent corruption.
- **Action and event logging (default-on)**: Mutations append immutable `TaskEvent` records to the ledger-level `events/` directory under `.taskledger/ledgers/<ledger_ref>/`. Action and event logging is enabled by default; set `[event_logging] enabled = false` to disable new records. Existing records remain readable. Source: `taskledger/storage/events.py`, `taskledger/services/task_events.py`, `taskledger/domain/event.py`.
- **Exit code taxonomy**: Errors map to stable exit codes (0=success, 1=generic, 2=bad input, 3=workflow rejection, 4=lock conflict, 5=missing, 6=storage, 7=validation failed).
- **Opaque cross-ledger references**: Task refs, plan versions, file links, and handoff targets remain opaque strings. Taskledger does not interpret ledgercore global refs, archledger IDs, SpecWeave feature paths, or other external system identifiers.
- **Read-model reuse**: `view`, `status`, `tree`, and `monitor` commands consume service-level read models. These presentations are read-only and do not bypass lifecycle services.
- **Editable plan input**: `taskledger plan check` is a pure preflight parser in `taskledger/services/plan_input.py`. It rejects malformed YAML, normalizes the `description` alias to `text`, and surfaces indexed issues before any plan upsert. `plan lint` runs additional structural checks; `plan review` renders the approval brief.
