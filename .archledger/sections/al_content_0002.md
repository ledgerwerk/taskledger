---
schema_version: 2
id: al_content_0002
type: section
section: architecture_constraints
title: Architecture Constraints
order: 20
status: accepted
date: "2026-05-23"
body_format: markdown
created_at: "2026-05-23T12:24:46Z"
updated_at: "2026-05-23T12:24:46Z"
---

taskledger operates under several fixed constraints that shape its architecture:

- **Python 3.10+ with minimal dependencies**: The runtime depends only on `typer`, `PyYAML`, `Jinja2`, `markdown-it-py`, and `tomli` (for Python <3.11). No database, no network server, no external service is required.
- **File-system canonical storage**: All durable state lives in the project's `.taskledger/` directory as Markdown files with YAML front matter. This makes state inspectable, diffable, and version-controllable alongside source code.
- **CLI-first with machine-readable JSON output**: The primary interface is the `taskledger` CLI command. Every command supports `--json` for structured output. The JSON envelope shape and exit codes are part of the public contract.
- **Skills outside the package**: Agent skill files (e.g., `skills/taskledger/SKILL.md`) live outside the Python package and are never packaged as Python package data. The package provides the CLI/library; skill distribution is separate.
- **Project-local configuration**: Each project has its own `taskledger.toml` and `.taskledger/` directory. There is no global state or central server.
