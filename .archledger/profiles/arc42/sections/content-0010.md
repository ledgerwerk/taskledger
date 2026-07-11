---
schema_version: 4
id: content-0010
type: section
section: quality_requirements
title: Quality Requirements
order: 100
status: accepted
body_format: markdown
kind: content
version: 2
---

Quality requirements that gate architectural decisions:

- **Data integrity**: Atomic writes and strict front matter validation prevent corrupt state. Partial writes are impossible due to `os.replace` semantics.
- **CLI exit code contract**: Exit codes are stable and tested. Agents and CI pipelines rely on specific codes for automation.
- **JSON envelope stability**: The JSON output shape (`ok`, `command`, `result_type`, `result`) is a public API contract. Breaking changes require explicit versioning.
- **Lifecycle gate correctness**: Every stage transition is validated by policy functions with full test coverage of error paths.
- **Export/import round-trip**: Archives preserve all state. Import into a fresh workspace reproduces the original taskledger state exactly.
- **Editable plan input preflight**: `taskledger plan check` returns a structured payload with `passed`, `summary`, indexed `issues`, and parsed counts. Lint and review are gate layers; preflight catches them earlier.
- **Implementation snapshot fidelity**: `validate start` blocks when the current workspace diverges from the implementation snapshot. `implement snapshot refresh --reason ...` is the only sanctioned recovery path and records an audit trail.
