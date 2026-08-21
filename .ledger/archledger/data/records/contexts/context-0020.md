---
schema_version: 4
id: context-0020
type: context_interface
title: Agent harnesses
status: accepted
section: context_and_scope
order: 10
context_kind: agent
partner: agent harness (pi, codex, chatgpt)
inputs:
- task create
- plan start
- plan guidance
- plan template
- plan check
- plan upsert
- plan lint
- plan review
- plan accept
- question add
- question answer
- todo add
- todo done
- implement start
- implement change
- implement command
- implement finish
- handoff create
- handoff claim
- handoff close
- context
- next-action
- review record
outputs:
- json_envelopes human_rendering handoff_context next_action context review_evidence
channels:
- CLI subprocess invocations from agent harnesses
- structured stderr/stdout
- deterministic exit codes
- taskledger trace bundles
body_format: markdown
kind: context
version: 8
---

Agent harnesses invoke taskledger CLI commands as subprocesses. They consume `--json` output and rely on exit codes for automation. Key interactions cover the task-first lifecycle (`task create`, `plan start`, `plan guidance`, `plan template`, `plan check`, `plan upsert`, `plan lint`, `plan review`, `plan accept`, `question add`, `question answer`, `todo add`, `todo done`, `implement start`, `implement change`, `implement command`, `implement finish`, `handoff create`, `handoff claim`, `handoff close`, `context`, `next-action`, `review record`). Agents are restricted from user-only actions (plan approval, criterion waivers) by default. Handoff context is the preferred fresh-context continuation surface.
