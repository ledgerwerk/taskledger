---
schema_version: 4
id: constraint-0016
type: constraint
title: Python 3.10+ with minimal ledgercore-backed dependencies
status: proposed
section: architecture_constraints
order: 10
category: technical
impact: Limits runtime to Python 3.10+ with three dependencies; no database or native
  extensions.
body_format: markdown
kind: constraint
version: 3
---

Runtime dependencies are limited to `typer`, `click`, `PyYAML`, `tomli` (Python <3.11 only), and `ledgercore` (for atomic I/O, JSON I/O, YAML I/O, front matter parsing, and cross-ledger ref parsing). This constraint ensures easy installation in constrained environments (CI, containers, Termux) and avoids dependency conflicts with host projects. The trade-off is that features like full-text search use pure-Python implementations rather than native libraries.
