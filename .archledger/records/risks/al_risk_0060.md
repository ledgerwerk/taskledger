---
schema_version: 2
id: al_risk_0060
type: risk
title: "Growing dependency count"
status: proposed
section: risks_and_technical_debt
order: 40
date: "2026-05-23"
severity: medium
probability: medium
mitigation: "Current set is small (typer, PyYAML, Jinja2, markdown-it-py, tomli); each justified by a specific feature."
body_format: markdown
created_at: "2026-05-23T12:31:20Z"
updated_at: "2026-05-23T12:31:20Z"
---

Jinja2 is used only for HTML report templates (`task report`, `taskledger serve`). `markdown-it-py` renders safe Markdown for those HTML views. The dependency set adds weight for users who only need the CLI. Mitigation: Current dependency set is small (typer, PyYAML, Jinja2, markdown-it-py, tomli); each is justified by a specific feature.
