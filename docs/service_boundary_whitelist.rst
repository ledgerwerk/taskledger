Service boundary whitelist
==========================

This note tracks temporary static-boundary whitelist entries enforced by
``tests/test_service_boundaries.py``.

The whitelist is debt tracking, not a permanent exception list. When an item
drops below budget or is removed, update this note and the related test
constants.

Module line budget whitelist (>2000 lines)
------------------------------------------

* ``taskledger/services/tasks.py``

  * Current reason: Temporary compatibility facade while workflow services
    are extracted.
  * Target split direction: Continue reducing to a smaller compatibility
    facade and move residual helpers into focused modules.

Current split status
--------------------

Implemented in this tranche:

* ``taskledger/services/planning_flow.py``
* ``taskledger/services/implementation_flow.py``
* ``taskledger/services/validation_flow.py``
* ``taskledger/services/tasks.py`` delegates plan, implement, and validate
  entrypoints to the new modules.

Remaining target: continue reducing ``taskledger/services/tasks.py`` to a
smaller compatibility facade and move residual helpers into focused modules.

Function line budget whitelist (>250 lines)
-------------------------------------------

* ``taskledger/services/doctor_checks/task_checks.py::scan_task_integrity``

  * Current reason: Consolidated per-task integrity scan with change/lock
    validation; further splitting into focused inspectors is planned.

* ``taskledger/cli_sync.py::register_sync_commands``

  * Current reason: Sync command registration currently co-locates legacy
    sync, archive alias, git sync, and hook command wiring.

CLI→services import whitelist
-----------------------------

CLI modules may import from ``taskledger.services`` only when listed in
``tests/test_service_boundaries.py`` under ``CLI_SERVICES_IMPORT_WHITELIST``.

Current sanctioned imports:

* ``taskledger/cli.py:taskledger.services.dashboard`` — Dashboard and view
  rendering are currently service-level read models.
* ``taskledger/cli.py:taskledger.services.agent_logging`` — Root CLI
  initializes recorder and payload/error notes.
* ``taskledger/cli.py:taskledger.services.tree`` — Tree rendering currently
  lives in services/tree.py.
* ``taskledger/cli.py:taskledger.services.doctor`` — Repair command uses
  doctor cleanup helper pending API wrapper.
* ``taskledger/cli.py:taskledger.services.monitor`` — Root monitor command
  renders the terminal monitor read model.
* ``taskledger/cli.py:taskledger.services.usage`` — Root usage command renders
  the fresh-session startup read model.
* ``taskledger/cli_actor.py:taskledger.services.actors`` — Actor and harness
  resolution currently lives in services/actors.py.
* ``taskledger/cli_common.py:taskledger.services.agent_logging`` — CLI common
  emits recorder task/payload/error notes.
* ``taskledger/cli_common.py:taskledger.services.actors`` — CLI common
  resolves actor/harness context for event metadata.
* ``taskledger/cli_implement.py:taskledger.services.actors`` — Implementation
  commands resolve actor/harness context.
* ``taskledger/cli_implement.py:taskledger.services.agent_logging`` —
  Implement command wrapper records managed-shell command failures.
* ``taskledger/cli_misc.py:taskledger.services.doctor`` — Doctor commands
  still consume doctor service inspectors directly.
* ``taskledger/cli_pipeline.py:taskledger.services.handoff`` — Pipeline
  context rendering currently reuses the handoff service payloads.
* ``taskledger/cli_pipeline.py:taskledger.services.worker_pipeline`` —
  Pipeline CLI commands read the worker pipeline service overlay directly.
* ``taskledger/cli_review.py:taskledger.services.actors`` — Review commands
  resolve reviewer/harness context.
* ``taskledger/cli_plan.py:taskledger.services.plan_editing`` — Plan input
  path validation currently lives in services/plan_editing.py.
* ``taskledger/cli_plan.py:taskledger.services.plan_lint`` — Plan lint
  payload model is still service-owned.
* ``taskledger/cli_question.py:taskledger.services.actors`` — Question
  commands resolve actor/harness context.
* ``taskledger/cli_plan.py:taskledger.services.workflow_guidance`` — Planning
  guidance profile read model is service-owned.
* ``taskledger/cli_plan.py:taskledger.services.agent_logging`` — Plan command
  wrapper records managed-shell command failures.
* ``taskledger/cli_plan.py:taskledger.services.planning_flow`` — Plan
  guidance command marks guidance viewed via planning flow service.
* ``taskledger/cli_task.py:taskledger.services.actors`` — Task record command
  resolves completed-by actor metadata.
* ``taskledger/cli_task.py:taskledger.services.agent_transcripts`` — Task
  transcript rendering currently lives in services.
* ``taskledger/cli_task.py:taskledger.services.task_reports`` — Task report
  rendering and options are service-owned.
* ``taskledger/cli_task.py:taskledger.services.task_export`` — Task export
  service for compiled LLM-ready Markdown.
* ``taskledger/cli_task.py:taskledger.services.tasks`` — Task events read
  model and lifecycle mutations.
* ``taskledger/cli_trace.py:taskledger.services.trace`` — Trace CLI delegates
  to the trace service.
* ``taskledger/cli_release.py:taskledger.services.releases`` — Release
  commands delegate to the releases service.


Catch-all exception whitelist (``except Exception``)
----------------------------------------------------

Current allowed sites are listed with reasons in
``tests/test_service_boundaries.py`` under ``EXCEPT_EXCEPTION_WHITELIST``.

Policy intent:

* Allow catch-all handling only in doctor/repair and resilience wrappers.
* Block new catch-all sites unless explicitly reviewed and justified.
* Require whitelist edits to be intentional and reasoned.
