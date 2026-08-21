---
schema_version: 4
id: runtime-0076
type: runtime_scenario
title: HTML report and serve dashboard
status: archived
section: runtime_view
order: 70
participants:
- taskledger report html (removed)
- taskledger serve (removed)
trigger: Developer runs taskledger report html or taskledger serve
result: ''
body_format: markdown
archived_reason: HTML report and serve dashboard removed; task-0126 ledger-isolation
archived_from: records/runtime/runtime-0076.md
kind: runtime
version: 1
---

**Trigger**: Developer runs `taskledger report html` or `taskledger serve`.

**Flow**:

1. `report html` → Generates a standalone HTML report file from task data using Jinja2 templates
2. `task report` → Generates a per-task report with configurable sections (summary, plan, changes, command-log)
3. `serve` → Starts a localhost HTTP server with a read-only web dashboard for browsing tasks, plans, and status
4. Dashboard renders task trees, status summaries, and plan details in a browser
5. All report/serve output is read-only — no mutations through the dashboard

**Result**: Human-readable HTML reports and a local dashboard for inspecting task state without the CLI. Agents should continue using JSON output and CLI commands.

**Key source**: `taskledger/services/html_reports.py`, `taskledger/services/web_dashboard.py`, `taskledger/services/task_reports.py`, `taskledger/cli_report.py`.
