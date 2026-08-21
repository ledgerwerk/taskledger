---
schema_version: 4
id: block-0030
type: black_box
title: CLI Layer
status: accepted
section: building_block_view
level: 1
parent: block-0029
order: 10
interfaces: []
location: []
fulfilled_requirements: []
risks: []
tags: []
body_format: markdown
kind: block
version: 2
---

Handles command parsing via Typer, task reference resolution (`--task` option, active task default), and output rendering (human text or JSON envelope via `cli_common.py`). Command families include the canonical lifecycle plus `review`, `config`, task archive operations, transfer and sync, diagnostics, the `monitor` observer, the `pipeline` overlay, and `ref` cross-ledger helpers.

Source refs: `taskledger/cli.py`, `taskledger/cli_common.py`, `taskledger/command_inventory.py`, and the focused `taskledger/cli_*.py` registration modules.
