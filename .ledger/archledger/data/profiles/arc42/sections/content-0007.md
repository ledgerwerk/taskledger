---
schema_version: 4
id: content-0007
type: section
section: deployment_view
title: Deployment View
order: 70
status: accepted
body_format: markdown
kind: content
version: 3
---
Taskledger is a single-node, file-system-based tool. Deployment consists of:

- **Installation**: `pip install taskledger` (PyPI) or local `pip install -e .`
- **Project initialization**: `taskledger init` creates `taskledger.toml` and `.taskledger/` in the project root
- **Runtime**: The CLI runs as a Python process, reading and writing the project `.taskledger/` directory. No daemon, no server.
- **CI integration**: taskledger commands can be run in CI pipelines for status checks, validation, snapshot and export operations, and `taskledger trace` bundles
- **Agent integration**: Agent harnesses invoke taskledger CLI commands as subprocess calls
