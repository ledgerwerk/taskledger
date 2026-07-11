---
schema_version: 4
id: glossary-0073
type: glossary_term
title: Worker Pipeline
status: proposed
section: glossary
order: 130
term: Worker Pipeline
definition:
  An optional advisory overlay that guides fresh-context handoffs through
  sequential worker steps.
body_format: markdown
kind: glossary
version: 3
---

An optional advisory overlay configured in `taskledger.toml` that guides fresh-context handoffs through a sequence of worker steps (for example `planner`, `tester`, `implementer`, `reviewer`). Worker pipelines do not override lifecycle gates; they are advisory workflow guidance. Configured via `taskledger/storage/worker_pipeline_config.py` and surfaced through `taskledger pipeline show` and the `worker_pipeline` block in `taskledger next-action`.
