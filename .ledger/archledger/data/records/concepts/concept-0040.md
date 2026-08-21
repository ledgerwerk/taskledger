---
schema_version: 4
id: concept-0040
type: concept
title: Actor metadata and role semantics
status: proposed
section: cross_cutting_concepts
order: 10
applies_to: []
body_format: markdown
kind: concept
version: 2
---

Every mutation carries an `ActorRef` (type: agent/user/system, name, role, session ID, harness ID) and optionally a `HarnessRef` (harness identity, kind, capabilities). The system distinguishes user-only actions (plan approval, criterion waivers, dependency waivers) from agent actions. Actor metadata is persisted in locks, runs, events, and handoff records for audit trails. Source: `taskledger/domain/actor.py` (`ActorRef`, `HarnessRef`), `taskledger/domain/states.py` (`ActorType`, `ActorRole`, `HarnessKind`).
