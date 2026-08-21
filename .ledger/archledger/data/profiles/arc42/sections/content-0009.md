---
schema_version: 4
id: content-0009
type: section
section: architecture_decisions
title: Architecture Decisions
order: 90
status: accepted
body_format: markdown
kind: content
version: 2
---

Key architecture decisions documented as ADR records:

- **ADR-1**: Markdown and YAML front matter as canonical format (not JSON, not SQLite)
- **ADR-2**: Sidecar summary index as derived rebuildable cache (not authoritative)
- **ADR-3**: Explicit lifecycle gates with policy decisions (not free-form state)
- **ADR-4**: Typer CLI framework (not argparse, not Click directly)
- **ADR-5**: Task bundle directory layout (not single-file index)
- **ADR-6**: External skill packaging (skills outside the Python package)
