# Taskledger architecture

`taskledger` is a task-first CLI and Python package for staged coding work.
The canonical workflow is:

```text
task -> plan -> approval -> implement -> validate -> done
```

## Owning layers

- `taskledger/domain/` owns lifecycle enums, policies, and record models.
- `taskledger/storage/task_store.py` and `taskledger/storage/locks.py` own persisted
  task bundles and visible lock files under `.taskledger/`.
- `taskledger/services/tasks.py` owns task lifecycle orchestration.
- `taskledger/services/handoff.py` owns handoff payloads and rendering.
- `taskledger/services/doctor.py` owns integrity checks.
- `taskledger/api/*` exposes public wrappers.
- `taskledger/cli*.py` wires commands only.

## Storage model

Markdown records are canonical. Task, plan, and run reads come from those
records directly. JSON files under `.taskledger/indexes/` are optional derived
caches or registries. Active stages require visible lock files, and stale locks
are reported instead of being cleared silently.

## Command surface

The supported command groups are `task`, `plan`, `question`,
`implement`, `validate`, `review`, `todo`, `intro`, `file`, `link`,
`require`, `release`, `lock`, `handoff`, `context`, `actor`,
`harness`, `view`, `tree`, `next-action`, `can`, `search`,
`grep`, `symbols`, `deps`, `doctor`, `repair`, `reindex`,
`migrate`, `init`, `status`, `export`, `import`, `snapshot`,
`storage`, `sync`, `ledger`, `report`, `serve`, `pipeline`,
`commands`, and `review` (code-review records).
