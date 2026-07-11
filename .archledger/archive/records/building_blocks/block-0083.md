---
schema_version: 4
id: block-0083
type: black_box
title: Human Presentation Layer
status: archived
section: building_block_view
level: 1
parent: block-0029
order: 60
interfaces:
  - Service read models -> terminal TUI
  - Dashboard/report payloads -> HTML or Markdown
location:
  - taskledger/tui/
  - taskledger/services/tui_read_model.py
  - taskledger/services/dashboard.py
  - taskledger/services/task_reports.py
fulfilled_requirements: []
risks: []
tags: []
body_format: markdown
source_refs:
  - path: taskledger/tui/
    role: implements
  - path: taskledger/services/tui_read_model.py
    role: implements
test_refs:
  - tests/test_tui_cli.py
  - tests/test_tui_read_model.py
archived_reason: TUI and HTML dashboard removed from taskledger; task-0126 ledger-isolation
archived_from: records/building_blocks/block-0083.md
kind: block
version: 1
---

Optional human-facing views over the same durable task records used by CLI and API operations. The Textual TUI presents task lists, plan review, todos, implementation, code reviews, validation, files, events, and raw reports. HTML dashboard and Markdown report services provide related inspection and sharing views.

This layer is read-only with respect to lifecycle state. Users invoke explicit CLI commands for mutations, preserving approval, lock, todo, and validation gates.
