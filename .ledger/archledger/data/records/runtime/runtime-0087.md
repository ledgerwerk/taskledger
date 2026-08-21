---
schema_version: 4
id: runtime-0087
kind: runtime
type: runtime_scenario
title: Editable plan input preflight
status: accepted
section: runtime_view
order: 35
version: 6
participants:
- taskledger plan check
- taskledger plan upsert
- taskledger plan lint
- taskledger plan review
trigger: Agent or user runs taskledger plan check and plan upsert
result: Plan is upserted with no parse errors, lint findings, or stale answers.
body_format: markdown
---

**Trigger**: Agent or user edits a plan file and runs `taskledger plan check` and `taskledger plan upsert`.

**Flow**:

1. `plan check --file plan.md` -> Pure preflight parser in `taskledger/services/plan_input.py` returns a `plan_input_check` payload with `passed`, indexed `issues`, and parsed counts. No state mutation.
2. Worker-pipeline configuration in `taskledger.toml` is consulted to validate `worker_step` todo tags when present.
3. `plan upsert --file plan.md` (or `--from-answers`) runs the same parser, persists the plan as a `PlanRecord`, and materializes todos.
4. `plan lint --version N` runs structural lint over the proposed plan body and front matter.
5. `plan review --version N` renders the approval brief used by the user-only approval command.

**Result**: Plan is persisted with no parse errors, no lint errors, and no stale answers. Approval can proceed.

**Key source**: `taskledger/services/plan_input.py`, `taskledger/services/plan_lint.py`, `taskledger/services/plan_review.py`, `taskledger/cli_plan.py`.
