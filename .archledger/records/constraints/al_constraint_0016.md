---
schema_version: 2
id: al_constraint_0016
type: constraint
title: "Python 3.10+ with minimal dependencies"
status: proposed
section: architecture_constraints
order: 10
date: "2026-05-23"
category: technical
impact: "Limits runtime to Python 3.10+ with five dependencies; no database or native extensions."
body_format: markdown
created_at: "2026-05-23T12:29:53Z"
updated_at: "2026-05-23T12:29:53Z"
---

Runtime dependencies are limited to `typer`, `PyYAML`, `Jinja2`, `markdown-it-py`, and `tomli` (Python <3.11 only). This constraint ensures easy installation in constrained environments (CI, containers, Termux) and avoids dependency conflicts with host projects. The trade-off is that features like full-text search use pure-Python implementations rather than native libraries.
