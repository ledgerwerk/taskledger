---
schema_version: 4
id: context-0021
type: context_interface
title: Human developers
status: accepted
section: context_and_scope
order: 20
context_kind: user
partner: terminal user
inputs:
  - task create
  - task show
  - task activate
  - plan accept
  - implement finish
  - validate finish
  - lock break
  - doctor
  - status
  - next-action
  - monitor
  - config get
  - config set
  - review record
outputs:
  - human_rendering plan_review_brief doctor_diagnostics monitor_snapshot
channels:
  - terminal_cli human_readable_output optional_actor_overrides
body_format: markdown
kind: context
version: 8
---

Human developers use the CLI directly in terminals. Key interactions: `task create`, `task show`, `task activate`, `plan accept`, `implement finish`, `validate finish`, `lock break`, `doctor`, `status`, `next-action`, `monitor`, `config get`, `config set`, `review record`. Humans render human-readable output (default) and perform user-only actions like plan approval, acceptance criterion waivers, and dependency waivers.
