---
schema_version: 2
id: al_runtime_0084
type: runtime_scenario
title: "BDD example to validation evidence"
status: proposed
section: runtime_view
order: 100
date: "2026-06-07"
participants:
  - coding agent
  - taskledger CLI
  - BDD services
  - task storage
trigger: "An actor wants executable examples linked to task acceptance criteria."
result: "Plain pytest results or SpecWeave-generated JUnit/Cucumber-compatible evidence are persisted as traceable validation checks."
result: "External automation results are persisted as traceable validation evidence."
body_format: markdown
created_at: "2026-06-07T11:50:18Z"
updated_at: "2026-06-07T11:50:18Z"
source_refs:
  - path: taskledger/cli_bdd.py
    role: implements
  - path: taskledger/services/bdd_gherkin.py
    role: implements
  - path: taskledger/services/bdd_reports.py
    role: implements
test_refs:
  - tests/test_bdd_cli.py
  - tests/test_bdd_validation_integration.py
---

1. An actor initializes task-local BDD/example records for a managed task.
2. Each example links to acceptance-criterion IDs and may link to Archledger records.
3. Canonical behavior specs live outside Taskledger under `specs/behavior/features/<area>/<feature>.feature`, owned by SpecWeave.
4. Plain pytest files under `tests/test_<area>_<feature>.py` enforce the behavior and may emit JUnit XML under `reports/behavior/`.
5. `bdd example link-automation` records metadata that links a task-local example to the external feature file, scenario tag/title, and pytest node id.
6. `validate import-bdd-report` imports JUnit XML or Cucumber-compatible JSON evidence and matches it back to task-local examples.
7. Matched results become validation evidence through normal validation checks; normal latest-check-wins and mandatory-criterion gates still decide completion.
8. `bdd gherkin-export` remains a derived exchange/export command. It must not be presented as the canonical source of executable behavior.
