---
schema_version: 4
id: glossary-0072
type: glossary_term
title: Front Matter
status: proposed
section: glossary
order: 120
term: Front Matter
definition: The YAML metadata block at the top of a canonical record file, delimited
  by ---.
body_format: markdown
kind: glossary
version: 1
---

The YAML metadata block at the top of a canonical record file, delimited by `---`. Contains structured fields (ID, type, status, dates, schema version) parsed by `read_markdown_front_matter` in `taskledger/storage/frontmatter.py`. The body after the front matter is Markdown content.
