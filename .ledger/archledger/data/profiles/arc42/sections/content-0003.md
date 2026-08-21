---
schema_version: 4
id: content-0003
type: section
section: context_and_scope
title: Context and Scope
order: 30
status: accepted
body_format: markdown
kind: content
version: 3
---
Taskledger operates as a self-contained tool within a software development project. It interacts with four categories of external actors:

1. **Agent harnesses** (pi, codex, chatgpt, and similar) invoke taskledger CLI commands to create tasks, propose plans, log implementation changes, run validation checks, and manage handoffs. They consume `--json` output.
2. **Human developers** use the CLI directly in terminals for task creation, plan review, approval, lock management, and inspection (`status`, `context`, `next-action`, `doctor`, `monitor`).
3. **CI systems** may invoke taskledger for status checks, validation, snapshot/export operations, and `taskledger trace` bundles.
4. **Python library consumers** import from `taskledger.api.*` to programmatically manage tasks without the CLI subprocess.

The system boundary is the `.taskledger/` directory and the `taskledger.toml` config file at the project root. Everything inside `.taskledger/` is taskledger-owned state. Everything outside is the host project source code. Taskledger does not depend on any external services, databases, or network endpoints. It reads the host project file system for search/symbol operations but does not modify files outside `.taskledger/`.
