---
schema_version: 4
id: content-0002
type: section
section: architecture_constraints
title: Architecture Constraints
order: 20
status: accepted
body_format: markdown
kind: content
version: 5
---
Taskledger operates under several fixed constraints that shape its architecture:

- **Python 3.10+ with minimal dependencies**: The runtime depends only on `typer`, `click`, `PyYAML`, `tomli` (Python <3.11), and `ledgercore` for atomic I/O, JSON I/O, YAML I/O, front matter parsing, and cross-ledger ref parsing. No database, no network server, no external service is required.
- **File-system canonical storage**: All durable state lives in the project Ledgercore mounts configured by `.ledger/ledger.toml`, as Markdown files with YAML front matter. This makes state inspectable, diffable, and version-controllable alongside source code.
- **CLI-first with machine-readable JSON output**: The primary interface is the `taskledger` CLI command. Every command supports `--json` for structured output. The JSON envelope shape and exit codes are part of the public contract.
- **Skills outside the package**: Agent skill files (for example `skills/taskledger/SKILL.md`) live outside the Python package and are never packaged as Python package data. The package provides the CLI and library; skill distribution is separate.
- **Project-local configuration**: Each project has its Ledgercore manifest at `.ledger/ledger.toml` and ledger-specific configuration under `.ledger/`. There is no global state or central server.
- **Source-first architecture records**: Arc42 architecture records are stored in `.ledger/archledger/data` and are the source of truth for `docs/architecture.md`. `docs/architecture_taskledger_split.md` is a concise human-maintained summary. Skills stay outside both the Python package and the archledger build output.
