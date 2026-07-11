---
schema_version: 4
id: glossary-0062
type: glossary_term
title: Plan
status: proposed
section: glossary
order: 20
term: Plan
definition:
  A proposed implementation plan with acceptance criteria that gates implementation
  start.
body_format: markdown
kind: glossary
version: 1
---

A proposed implementation plan for a task. Has status (draft → proposed → accepted/superseded/rejected), acceptance criteria, and a body describing the approach. When accepted, todos are materialized from the plan. Persisted as `PlanRecord` in `taskledger/domain/plan.py`.
