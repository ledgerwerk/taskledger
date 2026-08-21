---
schema_version: 4
id: concept-0085
kind: concept
type: concept
title: Editable plan input preflight
status: accepted
section: cross_cutting_concepts
order: 70
version: 5
applies_to:
  - taskledger plan check
  - taskledger plan upsert
  - taskledger plan lint
  - taskledger plan review
body_format: markdown
---

Editable plan input is a preflight parser in `taskledger/services/plan_input.py`. It accepts YAML front matter with `goal`, `files`, `test_commands`, `expected_outputs`, `acceptance_criteria`, and `todos`, plus optional `generation_reason` and waiver reason fields. Criterion `description` is normalized to `text` as a compatibility alias. Worker-pipeline configuration in `taskledger.toml` validates `worker_step` todo tags. `taskledger plan check --file plan.md` returns a `plan_input_check` payload with `passed`, `summary`, indexed `issues`, and parsed counts. `plan upsert` consumes the same parser; `plan lint` runs additional structural checks; `plan review` renders the approval brief.
