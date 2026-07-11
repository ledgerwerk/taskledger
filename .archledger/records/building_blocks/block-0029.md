---
schema_version: 4
id: block-0029
type: white_box
title: taskledger system
status: proposed
section: building_block_view
level: 1
parent: null
order: 10
diagram: null
quality_characteristics: []
tags: []
body_format: markdown
kind: block
version: 2
---

## Motivation

taskledger decomposes into core layers with downward dependency flow. This isolates persistence, business rules, orchestration, and public interfaces. Low-level persistence primitives are delegated to `ledgercore`, but the layer boundary above it stays in `taskledger/storage/`.

## Contained building blocks

1. **CLI Layer** (`block-0030`) — Typer commands, argument parsing, output rendering
2. **API Layer** (`block-0031`) — Stable Python function wrappers
3. **Services Layer** (`block-0032`) — Lifecycle orchestration, handoffs, plan input, plan review, snapshots, inspection
4. **Domain Layer** (`block-0033`) — Models, state machines, policies (no I/O)
5. **Storage Layer** (`block-0034`) — File system persistence, atomic writes, sidecar index, layout

## Important interfaces

- CLI -> Services: function calls with `workspace_root` plus task references
- Services -> Domain: policy functions take `PolicyContext`, return `Decision`
- Services -> Storage: record CRUD operations through `task_store.py` functions and the sidecar index
- API -> Services: direct function calls mirroring CLI behavior
- Storage -> ledgercore: atomic I/O, JSON I/O, YAML I/O, front matter parsing, cross-ledger ref parsing
