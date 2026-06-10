Public surface
==============

``taskledger`` supports the task-first workflow:

.. code-block:: text

   task -> plan -> approval -> implement -> validate -> done

Supported CLI entries
---------------------

The command inventory tracks 42 top-level CLI entries. Some are groups and some
are root commands. The normal agent path is intentionally smaller than the full
registered surface.

Core agent path
~~~~~~~~~~~~~~~

Agents should start with this durable lifecycle path:

``plan start -> plan template -> plan upsert -> plan lint -> plan accept`` is
the normal planning/approval path for agents.

- ``actor whoami``
- ``task active``, ``task show``, ``task create``, ``task activate``, ``task follow-up``
- ``next-action``, ``context``, ``can``
- ``plan start``, ``plan template``, ``plan upsert``, ``plan lint``, ``plan accept``
- ``question add``, ``question add-many``, ``question answer``, ``question answer-many``, ``question status``, ``question answers``
- ``todo next``, ``todo show``, ``todo done``, ``todo status``
- ``implement start``, ``implement resume``, ``implement change``, ``implement scan-changes``, ``implement finish``
- ``validate start``, ``validate status``, ``validate check``, ``validate finish``
- ``review record``
- ``handoff create``, ``handoff show``, ``handoff claim``, ``handoff close``

Top-level entry categories
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Primary groups** — core task-first lifecycle:

- ``task``, ``plan``, ``question``, ``implement``, ``validate``, ``review``, ``todo``
- ``context``, ``next-action``, ``init``, ``handoff``

**Support entries** — auxiliary operations:

- ``intro``, ``file``, ``link``, ``require``, ``lock``, ``config``, ``actor``, ``harness``, ``usage``
- ``export``, ``import``, ``snapshot``, ``pipeline``, ``can``, ``commands``

**Advanced entries** — power-user, storage, transfer, and project operations:

- ``ledger``, ``storage``, ``sync``, ``release``, ``migrate``

**Human-oriented entries** — interactive inspection and reporting:

- ``status``, ``view``, ``monitor``, ``tree``, ``search``, ``grep``, ``symbols``, ``deps``

**Repair and migration groups** — exceptional recovery:

- ``doctor``, ``repair``, ``reindex``, ``migrate``

``usage`` is the compact fresh-session startup command. It summarizes actor,
harness, active work, inbox items, and ready tasks without mutating ledger
state.

``monitor`` is the human-oriented, read-only terminal monitor. It replaces the
old browser/TUI surfaces with a dependency-free snapshot view that keeps using
the same underlying taskledger read models.

The supported implementation lifecycle includes ``implement restart --summary
"..."`` when a task is in ``failed_validation`` and ``implement resume --reason
"..."`` when an existing running implementation run has lost its lock.

Small post-completion deltas use ``task follow-up PARENT_REF TITLE`` to create a
new child task instead of reopening a ``done`` task.

Release boundaries are tracked separately from task lifecycle state with
``release tag`` and ``release changelog``.

``release *``, ``storage move``, ``sync git pull/push/sync``, sync hooks,
``ledger fork/switch/adopt``, ``migrate *``, ``repair *``, and
``search``/``grep``/``symbols``/``deps`` are not normal task work. They are
advanced, repair/migration, human-oriented, or beta support surfaces.

question subcommands
--------------------

- ``question add``, ``question list [--status STATUS]``, ``question answers [--format markdown|json]``
- ``question add-many [--text TEXT|--yaml-file PATH] [--required-for-plan]``
- ``question answer``, ``question answer-many``, ``question dismiss``, ``question open``, ``question status``

plan subcommands
----------------

- Normal path: ``plan start`` -> ``plan template`` -> ``plan upsert`` -> ``plan lint`` -> ``plan accept``
- Support reads/records: ``plan show``, ``plan review``, ``plan list``, ``plan diff``, ``plan export``, ``plan command -- ...``
- Advanced or compatibility paths: ``plan approve``, ``plan propose``, ``plan draft``, ``plan regenerate --from-answers``, ``plan materialize-todos``, ``plan revise``, ``plan amend``, ``plan reject``

Prefer ``plan accept`` for explicit chat approval. ``plan approve`` remains for
advanced metadata control and compatibility.

task reporting and transcripts
------------------------------

- ``next-action`` answers what should happen next.
- ``task show`` summarizes current task state.
- ``context`` renders agent continuation context.
- ``handoff create/show/claim/close`` manages durable transfer between sessions or actors.
- ``task report`` supports section control including ``--include command-log``
- ``task export`` writes a full single-file LLM/archive bundle.
- ``task transcript`` renders a per-task command transcript in ``markdown`` or ``json``

``task dossier``, root ``view``, and ``handoff plan-context`` /
``handoff implementation-context`` / ``handoff validation-context`` remain
advanced/compatibility read surfaces; prefer ``context --for ...`` and
``handoff show`` for new agent protocols.

todo subcommands
----------------

- ``todo add``, ``todo list``, ``todo done``, ``todo show``, ``todo status``, ``todo next``
- Todo source is inferred from active lock: ``implementer`` during implementation, ``planner`` during planning, ``user`` otherwise.

file subcommands
----------------

- ``file add``, ``file link``, ``file remove``, ``file list``, ``file status``, ``file refresh``
- ``file link`` records or updates a task-linked file with an optional baseline snapshot.
- ``file status`` reports ``new``, ``modified``, ``deleted``, ``unchanged``, and ``unbaselined`` drift states.

storage and sync subcommands
----------------------------

- ``storage where``, ``storage move --to PATH --mode copy|move [--adopt-existing] [--force]``
- ``sync preflight``, ``sync status``, ``sync commit --message "..."``

Supported Python API modules
----------------------------

- ``taskledger.api.project``
- ``taskledger.api.tasks``
- ``taskledger.api.plans``
- ``taskledger.api.questions``
- ``taskledger.api.task_runs``
- ``taskledger.api.reviews``
- ``taskledger.api.introductions``
- ``taskledger.api.locks``
- ``taskledger.api.handoff``
- ``taskledger.api.releases``
- ``taskledger.api.storage``
- ``taskledger.api.sync``
- ``taskledger.api.search``

``taskledger.api.task_runs`` includes the public lifecycle helpers
``start_implementation``, ``restart_implementation``, ``resume_implementation``,
``start_validation``, and ``finish_validation``. ``taskledger.api.tasks`` also
exposes ``uncancel_task`` for restoring truly cancelled tasks to a safe durable
stage.

Removed legacy surfaces
-----------------------

The old item/memory/repo/run/workflow/context/compose execution surfaces are not
part of the public compatibility contract. The corresponding CLI groups and
Python API modules have been removed rather than migrated.
