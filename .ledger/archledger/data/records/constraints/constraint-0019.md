---
schema_version: 4
id: constraint-0019
type: constraint
title: Skills must stay outside the Python package
status: proposed
section: architecture_constraints
order: 40
category: technical
impact:
  Skill distribution is separate from package distribution; skill installation
  is a distinct step.
body_format: markdown
kind: constraint
version: 2
---

Agent skill files (e.g., `skills/taskledger/SKILL.md`) live outside the `taskledger` Python package. They are not packaged as package data, not loaded via `importlib.resources`, and not distributed via PyPI. This separates the concerns of tool functionality (the package) from agent integration instructions (the skill).
