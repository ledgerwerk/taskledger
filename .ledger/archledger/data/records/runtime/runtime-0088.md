---
schema_version: 4
id: runtime-0088
kind: runtime
type: runtime_scenario
title: Implementation workspace snapshot lifecycle
status: accepted
section: runtime_view
order: 55
version: 6
participants:
- taskledger implement start
- taskledger validate start
- taskledger implement snapshot refresh
trigger: Implementation start captures snapshot and validation start enforces it
result: Validation runs only when the current workspace matches the implementation
  snapshot; mismatches are recovered with implement snapshot refresh.
body_format: markdown
---

**Trigger**: `taskledger implement start` captures a workspace snapshot; `taskledger validate start` enforces it before validation runs.

**Flow**:

1. `implement start` -> Acquires implementation lock, creates an implementation run, calls `capture_workspace_content_snapshot` in `taskledger/services/workspace_snapshot.py`, and persists snapshot metadata on the run.
2. Implementation finishes via `implement finish`. The snapshot is the source of truth for what was implemented.
3. `validate start` -> Calls `compare_implementation_snapshot`. If the current workspace diverges, validation is blocked with a `reason_code` such as `content_snapshot_mismatch` or `legacy_snapshot_mismatch`.
4. `validate start --refresh-implementation-snapshot --reason "..."` -> `refresh_implementation_snapshot` records a new snapshot, appends an `implementation.snapshot.refreshed` event, and resumes the normal validation flow.
5. `implement snapshot refresh --reason "..."` is the same recovery path when called outside `validate start`.

**Result**: Validation only proceeds when the current workspace matches the implementation snapshot; otherwise an explicit refresh with audit trail is required.

**Key source**: `taskledger/services/workspace_snapshot.py`, `taskledger/services/implementation_flow.py`, `taskledger/services/validation_flow.py`, `taskledger/cli_implement.py`.
