---
schema_version: 4
id: concept-0044
type: concept
title: Append-only event log
status: proposed
section: cross_cutting_concepts
order: 50
applies_to: []
body_format: markdown
kind: concept
version: 2
---

Mutations append an immutable `TaskEvent` record to the ledger-level `events/` directory under `.taskledger/ledgers/<ledger_ref>/`. Action and event logging is enabled by default; set `[event_logging] enabled = false` in `taskledger.toml` to disable new event records. Existing records remain readable regardless of the setting. Events are never modified or deleted. Each event has a deterministic ID, name (for example `task.created`, `plan.approved`, `lock.acquired`, `validation.check.logged`, `code_review.recorded`, `implementation.snapshot.refreshed`), timestamp, and actor metadata. Events support audit trails, monitor activity, handoff context, and `task transcript` output. Duplicate event detection prevents re-appending on retry. Source: `taskledger/storage/events.py`, `taskledger/services/task_events.py`, `taskledger/services/agent_logging.py`, `taskledger/services/agent_transcripts.py`, `taskledger/domain/event.py`.
