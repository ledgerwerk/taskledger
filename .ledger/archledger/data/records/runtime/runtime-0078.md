---
schema_version: 4
id: runtime-0078
type: runtime_scenario
title: Worker pipeline guided handoff
status: accepted
section: runtime_view
order: 90
participants:
- taskledger next-action
- taskledger pipeline show
- taskledger context --worker
- taskledger handoff create --worker
trigger: Agent runs taskledger next-action and receives worker_pipeline.next_step
result: Worker pipeline provides advisory hints for fresh-context handoffs through
  sequential worker steps without changing lifecycle gates.
body_format: markdown
kind: runtime
version: 5
---

**Trigger**: Agent runs `taskledger next-action` and receives `worker_pipeline.next_step` in the response.

**Flow**:

1. `next-action` → Returns `worker_pipeline.next_step` with `step_id`, `context_command`, and `handoff_command` hints
2. `pipeline show` → Displays the configured worker pipeline steps and their mapping to lifecycle stages
3. `context --worker spec-reviewer` → Renders a worker-specific context for the spec reviewer step
4. `handoff create --worker code-reviewer` → Creates a handoff with mode and context derived from the worker step configuration
5. Plan todos may be tagged with `worker_step` to associate implementation steps with specific pipeline workers
6. `plan template --with-worker-pipeline` → Generates plan template with worker-tagged todo sections

**Result**: Worker pipeline provides an advisory overlay that guides fresh-context handoffs through sequential worker steps (spec-reviewer, implementer, code-reviewer). It does not add new lifecycle gates — the task lifecycle remains the authoritative workflow.

**Key source**: `taskledger/services/worker_pipeline.py`, `taskledger/cli_pipeline.py`, `taskledger/services/handoff.py`.
