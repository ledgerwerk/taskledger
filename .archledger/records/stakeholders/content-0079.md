---
schema_version: 4
id: content-0079
type: stakeholder
title: Coding agents
section: introduction_and_goals
order: 10
status: accepted
body_format: markdown
kind: content
version: 2
expectations:
  - deterministic exit codes
  - stable json envelope
  - fresh context handoff continuation
  - task first workflow
  - human approval gate
---

Automated coding agents (e.g., agents running in harnesses like pi, codex, or opencode) are primary users. They interact exclusively through the CLI with `--json` output, follow the skill protocol, and rely on deterministic exit codes and stable envelope shapes for task lifecycle management.
