---
schema_version: 4
id: strategy-0024
type: strategy_item
title: 'Layered architecture: CLI → Services → Domain → Storage'
status: accepted
section: solution_strategy
order: 10
drivers:
  - decoupled layers
  - testable services
  - fast agent integration
constraints:
  - no domain I/O
  - storage uses ledgercore primitives
  - bounded CLI filesystem use
related_adrs:
  - adr-0046
  - adr-0047
  - adr-0048
  - adr-0049
  - adr-0050
  - adr-0051
body_format: markdown
kind: strategy
version: 5
---

## Strategy

The codebase is organized into five layers with target dependency direction: CLI (`taskledger/cli*.py`) -> API (`taskledger/api/`) -> Services (`taskledger/services/`) -> Domain (`taskledger/domain/`) + Storage (`taskledger/storage/`). The Domain layer has no I/O dependencies. Storage owns canonical taskledger persistence and atomic record I/O, delegating low-level primitives (atomic writes, JSON I/O, YAML I/O, front matter parsing, cross-ledger ref parsing) to `ledgercore`. Other layers may perform bounded filesystem operations for external inputs and outputs (reports, Git sync, search, CLI file arguments). CLI should prefer API wrappers for public workflows, but current sanctioned exceptions are tracked in `tests/test_service_boundaries.py`.

## Trade-offs

- Clear separation of concerns enables focused testing per layer.
- Service modules can grow large since they orchestrate across domain and storage.
- No formal dependency injection; layer boundaries are enforced by convention and the `test_service_boundaries.py` test.
