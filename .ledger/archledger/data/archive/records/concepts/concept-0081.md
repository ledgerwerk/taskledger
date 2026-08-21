---
schema_version: 4
id: concept-0081
type: concept
title: BDD traceability and report evidence
status: archived
section: cross_cutting_concepts
order: 70
applies_to: []
body_format: markdown
source_refs:
- path: taskledger/domain/bdd.py
  role: implements
- path: taskledger/services/bdd_gherkin.py
  role: implements
- path: taskledger/services/bdd_reports.py
  role: implements
test_refs:
- tests/test_bdd_gherkin.py
- tests/test_bdd_report_import.py
- tests/test_bdd_validation_integration.py
archived_reason: BDD traceability removed from taskledger; task-0126 ledger-isolation
archived_from: records/concepts/concept-0081.md
kind: concept
version: 1
---

BDD is an optional traceability overlay on a managed task. Features contain rules and Given/When/Then examples. Examples can reference canonical acceptance-criterion IDs and Archledger record IDs.

Gherkin export is an exchange artifact, not canonical state. Stable tags preserve task, example, criterion, and architecture identities. Imported Cucumber JSON or JUnit XML is matched back to examples and persisted as report evidence that can contribute validation checks. Normal lifecycle and validation gates remain authoritative.
