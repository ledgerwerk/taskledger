---
schema_version: 4
id: concept-0086
kind: concept
type: concept
title: Implementation workspace snapshot
status: accepted
section: cross_cutting_concepts
order: 75
version: 5
applies_to:
  taskledger implement start; taskledger implement finish; taskledger validate
  start; taskledger implement snapshot refresh
body_format: markdown
source_refs.1: "path: taskledger/services/implementation_flow.py

  role: implements

  reason: Persists snapshot metadata on implementation run

  test_refs: tests/test_implementation_checks.py"
---

When `taskledger implement start` is called, `taskledger/services/workspace_snapshot.py` captures a Git and content snapshot of the implementation workspace. The content snapshot (`worktree-content:v1`) records per-path status, kind, size, and content hash for files outside `.taskledger/`. The implementation run persists `workspace_git_commit`, `workspace_dirty`, `workspace_diff_hash`, `workspace_status_hash`, `workspace_snapshot_at`, `workspace_content_hash`, `workspace_paths_hash`, `workspace_entry_count`, `workspace_snapshot_format`, and `workspace_snapshot_ref`. `taskledger validate start` calls `compare_implementation_snapshot` and blocks validation when the current workspace diverges. The sanctioned recovery path is `taskledger implement snapshot refresh --reason "..."`, which records a new snapshot, appends an `implementation.snapshot.refreshed` event, and returns a structured payload with `old_snapshot` and `new_snapshot` details.
