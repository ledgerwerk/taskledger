---
schema_version: 4
id: deploy-0039
type: infrastructure
title: Local development deployment
status: proposed
section: deployment_view
level: 1
parent: null
order: 10
environment: development
maps_building_blocks: []
body_format: markdown
kind: deploy
version: 2
---

**Node**: Developer workstation or CI runner.

**Software**:

- Python 3.10+
- taskledger (pip installed)
- Host project with `taskledger.toml` config

**Storage**:

- `.taskledger/` directory in project root (Markdown and YAML front matter files)
- `task_sidecars.json` summary index under `.taskledger/ledgers/<ledger_ref>/`
- Project config at `taskledger.toml`

**Network**: None required.

**Installation**: `pip install taskledger` or `pip install -e .` from source. Single entry point: `taskledger` CLI.
