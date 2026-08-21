---
schema_version: 4
id: glossary-0069
type: glossary_term
title: Harness
status: proposed
section: glossary
order: 90
term: Harness
definition:
  The execution environment running taskledger (agent harness, manual terminal,
  or CI).
body_format: markdown
kind: glossary
version: 1
---

The execution environment running taskledger. Has a kind (agent_harness/manual/ci/unknown), name, session ID, and capabilities. Persisted as `HarnessRef` in `taskledger/domain/actor.py`. Harness metadata is recorded alongside actor metadata in runs and locks.
