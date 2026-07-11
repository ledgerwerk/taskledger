---
schema_version: 4
id: content-0006
type: section
section: runtime_view
title: Runtime View
order: 60
status: accepted
body_format: markdown
kind: content
version: 2
---

The runtime view traces the main operational scenarios through the system:

1. **Task lifecycle** — A task is created in `draft`, moves to `planning` (lock acquired, run started), then `plan_review` after a plan is proposed. The user approves -> `approved`. Implementation starts -> `implementing`, finishes -> `implemented`. Validation starts -> `validating`, passes -> `done`.
2. **Plan input flow** — `taskledger plan start` opens planning. `plan guidance` reports the active project planning profile. `plan template` writes a fresh plan skeleton; `plan check --file plan.md` runs the preflight parser in `taskledger/services/plan_input.py` without mutating state. `plan upsert --file plan.md` (or `--from-answers`) persists the plan; `plan lint --version N` surfaces blocking issues; `plan review --version N` produces the approval brief; `plan accept --version N --note ...` records the user-only decision.
3. **Implementation workspace snapshot** — `implement start` captures a Git and content snapshot in `taskledger/services/workspace_snapshot.py`. `validate start` blocks when the current workspace diverges from the implementation snapshot. `implement snapshot refresh --reason ...` records a new snapshot with an audit trail and is the normal recovery path when validation is blocked by snapshot mismatch.
4. **Lock lifecycle** — Starting a stage (planning, implementation, validation) acquires a lock and creates a run. Locks have lease timers and heartbeats. Stale locks require explicit break flow with audit trail.
5. **Handoff flow** — A worker creates a handoff with generated context (task state, plan, todos, questions, lock info). Another worker claims it, optionally transferring the lock. The handoff is closed when the receiving worker completes.
6. **Doctor checks** — Inspects lock/run consistency, front matter integrity, index staleness, and storage layout version. Reports diagnostics with severity, code, and repair hints.
7. **Validation evidence flow** — Acceptance criteria from the accepted plan are checked during the validation stage. Evidence is recorded per criterion with pass/fail/warn status. Latest-check-wins semantics apply; mandatory criteria gate completion.
8. **Code-review evidence** — A reviewer records append-only review evidence against an implementation run, handoff, worker step, working tree, or commit. This is evidence attached to the task, not a new lifecycle stage.
