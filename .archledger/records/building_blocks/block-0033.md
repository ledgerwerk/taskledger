---
schema_version: 4
id: block-0033
type: black_box
title: Domain Layer
status: proposed
section: building_block_view
level: 1
parent: block-0029
order: 40
interfaces: []
location: []
fulfilled_requirements: []
risks: []
tags: []
body_format: markdown
kind: block
version: 2
---

Data models, state enums, normalization, and policy decisions without storage I/O. Besides lifecycle and sidecar records, the domain defines append-only code-review records. State transitions remain in `states.py`; policy decisions in `policies.py` return structured `Decision` objects. The canonical storage layout version is `TASKLEDGER_STORAGE_LAYOUT_VERSION` in `taskledger/domain/states.py`.
