---
schema_version: 4
id: context-0023
type: context_interface
title: Python library consumers
status: accepted
section: context_and_scope
order: 40
context_kind: library
partner: Python import
inputs:
- taskledger.api.* function calls from host projects
outputs:
- json_envelopes as_python_dictionaries
channels:
- in_process_python_imports
body_format: markdown
kind: context
version: 8
---

Python code imports from `taskledger.api.*` modules to manage tasks programmatically. The API layer (`taskledger/api/tasks.py`, `taskledger/api/plans.py`, `taskledger/api/task_runs.py`, `taskledger/api/locks.py`, `taskledger/api/handoff.py`, `taskledger/api/sync.py`, `taskledger/api/reviews.py`, `taskledger/api/search.py`, `taskledger/api/storage.py`, `taskledger/api/config.py`, `taskledger/api/introductions.py`, `taskledger/api/releases.py`, `taskledger/api/questions.py`, `taskledger/api/project.py`) provides function wrappers that mirror CLI operations without subprocess overhead. Returned dictionaries match the JSON output shape.
