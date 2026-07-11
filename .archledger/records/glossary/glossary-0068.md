---
schema_version: 4
id: glossary-0068
type: glossary_term
title: Actor
status: proposed
section: glossary
order: 80
term: Actor
definition: The entity performing an action, classified as agent, user, or system.
body_format: markdown
kind: glossary
version: 1
---

The entity performing an action. Has a type (agent/user/system), name, optional role (planner/implementer/validator/reviewer/operator), session ID, and harness ID. Persisted as `ActorRef` in `taskledger/domain/actor.py`. Actor metadata is recorded in events, locks, runs, and handoffs for audit trails.
