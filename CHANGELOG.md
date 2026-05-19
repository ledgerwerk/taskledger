# Changelog

## v0.4.0 - 2026-05-18

### Added

- Added storage sync documentation (`docs/sync.rst`) explaining how to keep taskledger state outside the source repo, sync across PCs with a private Git repo, bootstrap a second machine, follow a daily sync protocol, and avoid active multi-writer conflicts.
- Added `taskledger storage where` command reporting resolved project and storage location details in human and JSON output, including whether storage lives inside the workspace, is a Git repo, or has active locks.
- Added `taskledger storage move` for safely migrating storage to a new `taskledger_dir` with atomic config updates, unsafe-target refusal, and follow-up command hints.
- Added `taskledger sync preflight` read-only check combining doctor health, active-lock warnings, tracked in-repo state warnings, and local Git status.
- Added `taskledger sync status` and `taskledger sync commit` local Git helper commands for committing taskledger state without network operations.
- Added `taskledger sync export` and `taskledger sync import` as aliases for the existing archive transfer commands.
- Added `taskledger sync git` command group for live external-state synchronization: `init`, `status`, `commit`, `cd`, `import-local`, `export-local`, `pull`, `push`, `sync`, and `hooks` subcommands with conservative lock/dirty checks.
- Added project-scoped `sync git status` that separates current-project changes from outside-project changes in JSON payloads, safe with dirty sibling directories.
- Added `sync git cd` helper returning the configured sync repo path for shell use.
- Added `sync git commit` for committing only the configured project path while ignoring dirty sibling paths.
- Added `[sync.git]` project config section with strict validation and documented defaults.
- Added `taskledger/services/storage_locations.py` for storage reporting, migration, and sync helper services.
- Added `taskledger/services/git_sync.py` for git sync orchestration.
- Added `taskledger/cli_sync.py` as a dedicated sync CLI group.
- Added `taskledger/api/sync.py` with public sync API wrappers.

### Changed

- Demoted whole-repo `sync git pull`, `push`, `sync`, and unsafe hook installation from recommended workflow to advanced/deprecated status in help, docs, and skill guidance.
- Reframed docs, README, and skill around the project-scoped local helper workflow: `sync git status`, `sync git commit`, then manual Git via `sync git cd`.
- Fixed stale config filename references so docs no longer claim init writes `.taskledger.toml` when `taskledger.toml` is canonical.
- Updated external storage examples to use the current `ledgers/<ledger_ref>/...` layout.

### Documentation

- Added `docs/sync.rst` with cross-PC sync workflow, daily protocol, and multi-writer conflict avoidance guidance.
- Updated README, `docs/usage.rst`, `docs/transfer.rst`, `docs/command_contract.rst`, `docs/public_surface.rst`, `API.md`, and `skills/taskledger/SKILL.md` for the new storage and sync command surface.

### Quality

- Added `tests/test_storage_sync.py` and `tests/test_sync_git.py` covering storage migration, sync commands, git sync workflows, shared dirty state, project-scoped commits, and JSON result kinds.
- Expanded command inventory, CLI contract, and docs/skill tests for the new command surface.
- Full suite: 897 tests passing, ruff and mypy clean.

## v0.3.1 - 2026-05-12

### Added

- Added task-scoped export/import with `--task` positional ref on export, safe ID remapping (`--id-policy preserve|renumber`), counter repair, and artifact path remapping on import. Full-ledger export remains the default; single-task archives filter task-scoped records and clear `active_task`.
- Added `taskledger plan review` command to show the current or specified plan version with structured JSON output and content rendering.
- Added `next-action` routing to recommend `plan review --version N` when a plan is awaiting approval.

### Documentation

- Updated README, command contract, and SKILL.md for task-scoped transfer workflow and `plan review` command.

### Quality

- Added regression coverage for task-scoped export/import ID mapping, conflict policy, counter repair, artifact remap, and plan review end-to-end.
- Full suite: 878 tests passing, ruff and mypy clean.

## v0.3.0 - 2026-05-05

### Added

- Added agent command transcript logging: opt-in config, append-only NDJSON storage, CLI stdout/stderr tee capture, managed-shell capture, `task transcript` command, and `task report --include command-log` section. Export/import preserves transcript archives.
- Added planning guidance profiles: `plan guidance` command, `--include-guidance` plan template injection, and `prompt_profiles.planning` config with advisory required-fields rendering.
- Added transcript review mode as the default `task transcript` output, with `--raw` flag for the original table view, duplicate log ID warnings, and logical-row grouping for wrapper/managed-shell pairs.
- Added enriched command metadata: tier, deprecated, replaced_by, ledger_effect, workspace_effect, external_effect, and agent_safe fields on CommandSpec. Added `--tier` and `--include-deprecated` CLI filters. Deprecated `lock break` in favor of `repair lock`.
- Added first-class expired-lock resume path: `implement resume --repair-expired-lock` releases expired implementation locks with audit trail, and `next-action` emits `expired-lock-resume` when applicable.
- Added task-resource positional refs for read-only commands (`task show`, `task view`, etc.) with explicit `--task` required for destructive commands (`task cancel`, `task uncancel`, `task edit`).
- Added JSON usage-error envelopes for workflow positional-ref rejection and CLI parse errors.
- Added soft task archive: `task archive`/`task unarchive` commands, archived-task visibility filtering across list/tree/status, and slug reuse semantics.
- Added export/import project metadata guard, dry-run safety, and include-flag controls.
- Added plan revision workflow: `plan export`, `plan amend`, and `--auto-revise` with safe plan input path guard and plan.amended audit events.
- Added plan approval provenance: approval_source and approved_plan_hash stored on acceptance, with hash-mismatch warnings in reports.
- Added implement finish warning for missing git change scans.

### Changed

- Split run/lock helpers into `services/run_store.py` from the tasks.py monolith; `tasks.py` re-exports for backward compatibility.
- Wrapper commands now mirror inner exit status by default instead of always succeeding.
- Planning guidance recommendation is now integrated into `plan start` and `next-action` with a one-time viewed marker.
- Plan lint human output now renders summary and issue details instead of bare pass/fail.
- Question `answer-many` now validates repeat inputs, aliases, and provenance.
- Doctor mismatch guidance and verbose output improved with actionable repair hints.

### Fixed

- Fixed task report Plans section so non-accepted plans show reviewable details instead of being omitted.
- Fixed pre-commit `--all-files` regressions across test files.

### Documentation

- Documented planning guidance profiles in README, usage, command contract, API, and skill.
- Documented transcript logging, managed command capture, and review mode in usage and skill.
- Documented expired-lock-resume path and `--repair-expired-lock` in SKILL.md.
- Documented command-surface safety guidance, task-resource positional refs, and destructive-target rules in SKILL.md and command contract.
- Documented plan revision workflow commands and safety semantics in SKILL.md and command examples.
- Updated failure-review remediation hints for known mistakes in docs and skill.

### Quality

- Added regression test modules for agent command logging, expired-lock resume, task archive, and plan revision workflow.
- Expanded command inventory, CLI contract, JSON contract, and docs/skill tests for metadata enrichment, deprecation, targeting, and envelope behavior.
- Full suite: 770+ tests passing, ruff and mypy clean.

## v0.2.0 - 2026-05-03

### Added

- Added `taskledger task record` for creating done tasks that represent manually completed work, with change records, evidence, and implementation summaries. Does not acquire locks or activate the task. Recorded tasks are included in release changelogs.
- Added branch-scoped ledger state with `taskledger ledger` command group (`status`, `list`, `fork`, `switch`, `adopt`, `doctor`). Each git branch can maintain its own isolated task ledger, with `adopt` for copying branch-local task history into the current ledger.
- Added `taskledger tree` command to render ledger and task structure with follow-up nesting, subtree filtering, release boundaries, and per-ledger release counts in both human and JSON output.
- Added compressed export/import with a project UUID guard to prevent importing archives into the wrong project, plus archive member-count and manifest/payload size limits for safety.
- Added `taskledger status --check` to run doctor diagnostics alongside status, keeping the default `status` fast by avoiding full record parsing.
- Added structured diagnostics to `taskledger doctor` JSON output with task IDs, change IDs, run IDs, types, relative paths, and actionable repair hints.
- Added explicit `repair` command for existing planning-command change records that were incorrectly persisted as code changes.
- Added a top-level `Makefile` with a `release-check` automation target (compile, test, lint, type-check, build, twine check).
- Added AST-based service boundary guardrail tests with explicit whitelists and documented rationale.

### Changed

- Split core plan/implement/validate service entrypoints from `tasks.py` into dedicated `planning_flow.py`, `implementation_flow.py`, and `validation_flow.py` modules. `tasks.py` remains a compatibility facade.
- Decoupled validation service from private task helpers by extracting shared query logic into a new `task_queries` module.
- Planning commands are now persisted as planning-run evidence (worklog/artifacts/event) instead of creating `CodeChangeRecord` entries.
- Replaced chmod-dependent storage write failure test with a deterministic synthetic `OSError` monkeypatch.
- Sped up test suite with test-only fast fsync bypass, command-runner seam, and reduced subprocess-heavy setup.

### Fixed

- Fixed import replace so it no longer restores stale locks across machines.

### Documentation

- Documented branch-scoped ledger workflow, `task record` usage and warnings, `tree` command, and `make release-check` across README, RST docs, API docs, and the taskledger skill.
- Added `docs/service_boundary_whitelist.md` documenting temporary module/function boundary whitelist entries and split targets.

### Quality

- Expanded regression coverage for branch-scoped ledgers, task record, tree command, compressed export/import, doctor diagnostics, status performance, service boundaries, and planning command persistence. Repo-wide pytest, ruff, and mypy passed.

## v0.1.2 - 2026-04-30

### Fixed

- Fixed orphaned planning run lifecycle recovery so plan regeneration safely finishes the latest orphaned planning run with audit evidence, plan approval rejects tasks with any running run, and `implement start` reports structured conflict details including run id, run type, lock match status, and suggested diagnostic command.
- Aligned `next-action` and `can implement` so they never recommend `implement start` when a running run or run/lock mismatch blocks implementation.
- Expanded `taskledger doctor` and `taskledger doctor locks` to report run/lock mismatches with specific repair guidance.

### Added

- Added `taskledger repair run` for guarded, reasoned, audited repair of orphaned running planning runs.

### Documentation

- Updated taskledger skill, command contract, and API docs with running-run conflict protocol and `repair run` usage.

### Quality

- Expanded regression coverage for plan regeneration recovery, approval guards, next-action alignment, doctor diagnostics, and repair lifecycle. Targeted pytest, ruff, format, and mypy passed.

## v0.1.1 - 2026-04-29

### Added

- Added `task follow-up` to create linked post-completion child tasks, preserve closure metadata, and show parent and follow-up relationships in task and handoff views.
- Added durable release records and a new `taskledger release` command group with `tag`, `list`, `show`, and `changelog`, including export/import support and public API coverage.
- Added planning helpers with `question add-many`, `plan template`, richer regeneration hints in `next-action`, and recovery commands for orphaned implementation work with `implement resume`, `task uncancel`, and `can implement-resume`.

### Changed

- Hardened CLI startup so optional command-group import failures no longer block core commands, and launcher failures return structured diagnostics.

### Fixed

- Fixed recovery guidance for uncancelled tasks with orphaned implementation runs so `next-action` and `can implement` recommend `implement resume` instead of a fresh start.

### Documentation

- Documented release tagging, changelog generation, planning helpers, follow-up task workflow, and recovery semantics across README, RST docs, API docs, and the taskledger skill.

### Quality

- Expanded regression coverage for follow-up tasks, release workflow, CLI import resilience, planning helpers, and implementation recovery. Repo-wide pytest, ruff, and mypy passed.

## v0.1.0 - 2026-04-29

### Added

- Added initial unit test coverage for `storage/common`, `storage/init`, `storage/repos`, `domain/policies`, and `services/doctor_v2`, raising overall coverage from 62% to 65%.
- Added a second coverage pass for storage memories, items, contexts, validation, and dashboard services, raising overall coverage to 73%.
- Added question status filtering plus `taskledger question answers` with markdown and JSON output.
- Added `taskledger plan lint`, stricter executable-plan linting, and approval gating for lint failures.
- Added focused worker contexts and durable handoff snapshots for implementer and reviewer workflows.
- Added richer `next-action` output with next item, command hints, and progress details.
- Added project-root config discovery and external storage roots via `taskledger.toml`.
- Added the localhost-only read-only `taskledger serve` dashboard.
- Added an explicit failed-validation recovery path with `taskledger implement restart`.
- Added compact single-agent workflow guidance and richer `todo next` and `todo show` hints.

### Changed

- Hardened agent guardrails by requiring reasons for approval escape hatches, blocking empty-todo approvals by default, and adding durable `plan command` execution.
- Finished agent-protocol hardening with stronger typed normalization, safer plan todo materialization, and automatic todo source inference from the active lock.
- Removed redundant derived task, plan-version, and latest-run indexes so Markdown bundles remain canonical and JSON indexes remain rebuildable caches.
- Completed the broader pre-release cleanup pass from `todo.md`, including public API export cleanup, stricter storage diagnostics, canonical module paths, normalized JSON command naming, and packaging cleanup.
- Extended the serve dashboard with a dedicated read model, recent-event tail loading, route caching, and non-overlapping partial refreshes for better hot-path performance.
- Redesigned the serve dashboard into a more human-focused layout with richer sidebar metadata, accessibility coverage, and updated docs.
- Improved dashboard review ergonomics and refresh stability with pause and resume controls, diffed rerenders, preserved details state, and lazy raw-payload rendering.
- Finished release-readiness cleanup by consolidating maintained docs under RST and keeping `skills/taskledger/SKILL.md` as the single canonical skill file.

### Fixed

- Fixed `taskledger view` so todo counts and item lists reflect persisted todos instead of always showing `0/0`.
- Fixed orphan slug-directory creation under `.taskledger/tasks/` and added repair support for existing bad directories.
- Fixed repo-wide pre-commit and mypy failures across more than twenty files.
- Fixed serve response handling so client disconnects no longer produce `BrokenPipeError` tracebacks.
- Fixed the serve dashboard todo-renderer JavaScript regression that broke refresh parsing.

### Quality

- Improved testing depth across storage, dashboard, lifecycle, and documentation surfaces to support release readiness and regression protection.
