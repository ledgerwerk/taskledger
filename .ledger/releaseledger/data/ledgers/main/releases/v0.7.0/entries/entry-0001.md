---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 2
entry_id: entry-0001
release_version: v0.7.0
kind: removed
summary: Removed deprecated CLI aliases and legacy option forms in favor of canonical
  task-first commands
status: accepted
audience: null
scopes: []
source_refs:
- tl:task-0032
- git:58cdf45f831f4966d9bafe20f61fdcc5e820e50e
paths:
- taskledger/cli.py
- taskledger/cli_migrate.py
- taskledger/cli_storage.py
- taskledger/cli_sync.py
- taskledger/command_inventory.py
- taskledger/domain/states.py
- taskledger/domain/handoff.py
- docs/command_contract.md
- docs/release_checklist.md
issues: []
prs: []
sources: []
contributors: []
breaking: true
internal: false
order: 1
---
The following CLI spellings were removed in favor of the canonical command forms:

| Removed form | Migration |
| --- | --- |
| Global `--cwd PATH` | Use `--root PATH`. |
| `status --full` | Use `info`. |
| `storage set --root`, `--project`, or `--local` | Use `--storage-root` and `--scope project|local`. |
| `init --taskledger-dir PATH` | Use `init` for new canonical schema-3 projects. Keep existing legacy layouts as explicit migration input with `migrate plan` and `migrate apply`. |
| `lock break` | Use `repair lock`. |
| `reindex` CLI command | Use `repair index`. The Python `reindex` API remains unchanged. |
| `sync git import-local` and `sync git export-local` | Use explicit migration commands for legacy storage and the configured storage mounts for canonical projects. |
| Hidden `sync git sync` | Use the explicit `sync git status`, `cd`, `path`, `commit`, `pull`, and `push` operations. |
| `sync export` and `sync import` | Use the root-level `export` and `import` commands. |
| `handoff plan-context`, `implementation-context`, and `validation-context` | Use `context --for planner`, `implementer`, or `validator` for fresh context; use `handoff create` and `handoff show` for durable handoffs. |
| Context roles `planning`, `implementation`, `validation`, and `review` | Use `planner`, `implementer`, `validator`, and `reviewer`. |
| Migration options `--source-checkout` and `--retire-legacy` | Use `--source-checkout-id` and `--retire-source`. |
| Migration options `--backup` and `--no-backup` | Omit the toggle; migration backups are automatic. Use `--backup-dir` only to choose a backup location. |

These changes narrow new CLI input without removing persisted handoff compatibility or legacy storage migration support.
