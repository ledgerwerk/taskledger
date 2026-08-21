---
schema_version: 4
id: concept-0082
type: concept
title: Durable code-review evidence
status: proposed
section: cross_cutting_concepts
order: 80
applies_to:
- taskledger review record
body_format: markdown
source_refs:
- path: taskledger/domain/review.py
  role: implements
- path: taskledger/services/code_review.py
  role: implements
test_refs:
- tests/test_code_reviews.py
kind: concept
version: 4
---

Code review is durable evidence attached to a task. A record captures result, summary/body, reviewer and harness, implementation run, worker step, handoff, and optional Git working-tree or commit metadata. Review records are append-only and may be recorded after a task reaches `done`. They do not create a lifecycle stage, reopen completed work, replace acceptance criteria, or weaken validation completion rules. Source: `taskledger/domain/review.py`, `taskledger/services/code_review.py`. Test coverage: `tests/test_code_reviews.py`.
