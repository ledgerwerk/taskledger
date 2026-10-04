---
schema_version: 4
id: block-0034
type: black_box
title: Storage Layer
status: proposed
section: building_block_view
level: 1
parent: block-0029
order: 50
interfaces: []
location: []
fulfilled_requirements: []
risks: []
tags: []
body_format: markdown
kind: block
version: 3
---

File system persistence for canonical records. Each task lives in the current Ledgercore data mount at `ledgers/<ledger_ref>/tasks/<uuidv7>/`, with `task.md` and independently addressable sidecars including plans, runs, locks, todos, questions, changes, checks, handoffs, links, and code reviews. UUIDv7 is the stable storage identity; `task-####` is a derived user-facing alias resolved through the identity inventory. Layout-5 numeric bundles migrate deterministically to layout 6 before mutation; read-only access does not migrate. Ledger-level collections hold events, introductions, releases, and other shared records. Task and sidecar indexes are derived caches in the configured rebuildable indexes mount. Atomic write primitives, YAML I/O, front matter parsing, and ref parsing are delegated to `ledgercore`. Project configuration edits use structured TOML handling rather than ad hoc text replacement.
