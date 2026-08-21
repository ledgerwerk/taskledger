---
schema_version: 4
id: content-0011
type: section
section: risks_and_technical_debt
title: Risks and Technical Debt
order: 110
status: accepted
body_format: markdown
kind: content
version: 2
---

Known risks and areas of technical debt:

- **Storage scaling with many tasks**: Each task is a directory with multiple sidecar files. Very large projects (hundreds of tasks) may see slowdowns in list and query operations because the `task_sidecars.json` summary index is rebuilt from file scans on miss and updated on writes. The per-task sidecar index keeps the common read path fast but does not eliminate directory overhead.
- **Migration surface between storage versions**: The storage layout is currently v3 (`TASKLEDGER_STORAGE_LAYOUT_VERSION` in `taskledger/domain/states.py`). Migration code in `taskledger/storage/migrations.py` adds complexity. Future format changes must maintain backward compatibility or ship migration steps.
- **Service boundary erosion**: Some service modules (notably `tasks.py` and a few focused modules) have grown large. The service layer has no formal interface contracts; boundaries are enforced by convention and the `tests/test_service_boundaries.py` whitelist in `docs/service_boundary_whitelist.md`.
- **Implementation snapshot drift**: Workspace snapshots are a strong invariant but require explicit refresh after environment changes. `taskledger next-action` and `validate start` surface mismatch diagnostics; the recovery path is `implement snapshot refresh --reason ...`.
- **Editable plan input compatibility**: `description` is accepted as an alias for `text` on acceptance criteria; strict mode promotes unknown-field findings to errors to prevent silent structured-data loss.
- **Growing dependency surface**: The runtime dependency set is small (`typer`, `click`, `PyYAML`, `tomli`, `ledgercore`) but new dependencies must be justified by core features rather than optional presentations.
