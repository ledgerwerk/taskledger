---
schema_version: 4
id: runtime-0037
type: runtime_scenario
title: Handoff creation and claiming
status: accepted
section: runtime_view
order: 30
participants:
- taskledger handoff create
- taskledger handoff claim
- taskledger handoff close
trigger: Worker runs taskledger handoff create
result: Receiving worker claims the handoff and closes it after completing the intended
  next action.
body_format: markdown
kind: runtime
version: 5
---

**Trigger**: Worker runs `taskledger handoff create`.

**Flow**:

1. Generate context body: task state, accepted plan, todos, questions, lock/run status, implementation summary, validation status
2. Create `TaskHandoffRecord` with mode (planning/implementation/validation/review/full), lock policy (none/retain/release/transfer), intended actor and harness
3. Persist handoff record, append `handoff.created` event
4. Another worker runs `handoff claim` → status → `claimed`, optional lock transfer
5. Worker completes work, runs `handoff close` → status → `closed`

**Key source**: `taskledger/services/handoff.py` (context generation), `taskledger/services/handoff_lifecycle.py` (claim/close/transfer), `taskledger/services/worker_context.py` (context assembly).
