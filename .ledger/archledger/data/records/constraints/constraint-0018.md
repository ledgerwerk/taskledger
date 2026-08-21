---
schema_version: 4
id: constraint-0018
type: constraint
title: CLI-first with machine-readable JSON output
status: proposed
section: architecture_constraints
order: 30
category: technical
impact: JSON envelope shape and exit codes are public API contracts; breaking changes
  require version bumps.
body_format: markdown
kind: constraint
version: 1
---

The CLI is the primary interface. Every command supports `--json` for machine-readable output with a stable envelope shape (`ok`, `command`, `result_type`, `result`, `events`, `warnings`) and deterministic exit codes. This enables agent harnesses and CI pipelines to consume output programmatically without parsing human text.
