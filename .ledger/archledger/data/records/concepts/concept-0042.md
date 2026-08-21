---
schema_version: 4
id: concept-0042
type: concept
title: YAML front matter serialization
status: proposed
section: cross_cutting_concepts
order: 30
applies_to: []
body_format: markdown
kind: concept
version: 2
---

All canonical records are `.md` files with YAML front matter (`---` delimited) containing structured metadata and a Markdown body. Read and write are handled by `read_markdown_front_matter` and `write_markdown_front_matter` in `taskledger/storage/frontmatter.py`, backed by `ledgercore.frontmatter`. Models implement `to_dict()` and `from_dict()` for serialization. Schema version and object type fields enforce contract integrity on read.
