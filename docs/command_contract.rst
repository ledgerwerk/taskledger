CLI Command Contract
====================

Taskledger uses a task-first command grammar:

.. code-block:: text

   taskledger [--root PATH] [--json] <area> <verb> [RESOURCE_REF] [--task TASK_REF] [options]

Global Options
--------------

* ``--root PATH`` selects the workspace root.
* ``--json`` is root-level only and must appear before the command group.
* Command-local ``--json`` options are not part of the public contract.

``--cwd`` remains accepted as a compatibility root alias, but docs and examples
should prefer ``--root``.

Task Scoping
------------

Task-scoped workflow commands default to the active task. Use
``--task TASK_REF`` when explicitly targeting another task.

.. code-block:: bash

   taskledger plan start
   taskledger plan start --task task-0001
   taskledger implement resume --task task-0001 --reason "Reacquire implementation lock."
   taskledger implement restart --task task-0001 --summary "Fix validation findings."
   taskledger implement finish --task task-0001 --summary "Implemented."
   taskledger validate status --task task-0001

Task-resource commands accept the task as their direct positional resource:

.. code-block:: bash

   taskledger task show task-0001
   taskledger task cancel task-0001 --reason "Duplicate"
   taskledger task archive task-0001 --reason "Hide historical task"
   taskledger task unarchive task-0001 --reason "Restore task"
   taskledger task report task-0001

Optional positional task refs are not supported for workflow commands.

Plan guidance command
---------------------

``taskledger plan guidance`` is a read-only planning helper command:

.. code-block:: bash

   taskledger plan guidance [--task TASK_REF] [--format markdown|json]

Rules:

* defaults to the active task when ``--task`` is omitted;
* ``--format`` accepts only ``markdown`` or ``json``;
* when a planning run is active, it records a one-time guidance-view marker for
  that run and appends a ``plan.guidance.viewed`` event;
* root ``--json`` continues to return the standard CLI success/error envelope.

The command payload shape is:

* ``kind``
* ``task_id``
* ``has_project_guidance``
* ``guidance``
* ``profile``
* ``question_policy``

Plan revision commands
----------------------

``taskledger plan export`` renders an editable plan draft outside durable
storage, and ``taskledger plan amend`` applies structured plan-review edits:

.. code-block:: bash

   taskledger plan export [--task TASK_REF] [--version latest|N] [--file PATH] [--overwrite] [--stdout]
   taskledger plan amend [--task TASK_REF] [--drop-criterion CRITERION_ID ...] [--drop-todo TODO_ID ...] [--remove-file PATH ...] --reason "..."

Plan proposal commands that accept ``--file`` reject file paths under
``.taskledger/`` because that directory is private durable ledger state.

Plan review command
-------------------

``taskledger plan review`` is a read-only approval-facing plan renderer:

.. code-block:: bash

   taskledger plan review [--task TASK_REF] [--version N] [--format markdown|json] [-o PATH]

Rules:

* defaults to the active task when ``--task`` is omitted;
* defaults to the latest proposed plan in ``plan_review`` stage when ``--version`` is omitted;
* renders Markdown by default and can emit JSON-formatted content with ``--format json``;
* when ``-o/--output`` is provided, writes rendered content to a file path.

Archive import lock policy
--------------------------

Archive imports support explicit lock handling:

.. code-block:: bash

   taskledger import ./taskledger-transfer.tar.gz --replace [--lock-policy drop|quarantine|keep]
   taskledger import ./taskledger-task-<project>-<ledger>-task-0040-<ts>.tar.gz [--id-policy preserve|renumber-on-conflict|fail-on-conflict]

The default is ``quarantine`` so imported source-machine runtime locks are not
restored as active ``lock.yaml`` files. ``keep`` is diagnostic-only behavior
for full-fidelity lock restoration.

Transfer archive manifest contract
----------------------------------

Transfer archives include both machine identity and human-readable metadata:
``manifest.project.name`` and ``manifest.project.slug`` are display metadata,
while ``manifest.project.uuid`` remains the safety identity.

.. code-block:: json

   {
     "project": {
       "uuid": "<project_uuid>",
       "name": "<project_name>",
       "slug": "<project_slug>",
       "ledger_ref": "<ledger_ref>"
     }
   }

Import compatibility is backward-safe: older archives that only contain
``project.uuid`` and ``project.ledger_ref`` remain valid. UUID comparison is
still authoritative for import safety.

``taskledger import --dry-run`` must not mutate taskledger state for either
archive or JSON payload imports.

Export task selection
---------------------

Taskledger export supports full-ledger and task-scoped archives:

.. code-block:: bash

   taskledger export
   taskledger export ./backup.tar.gz
   taskledger export --task task-0040
   taskledger export task-0040
   taskledger export task-0040 -o ./task0040.tar.gz

Positional Resource Refs
------------------------

Positional refs are reserved for the direct resource being changed or shown:

.. code-block:: bash

   taskledger task create TITLE [options]
   taskledger task record TITLE [options]
   taskledger task activate TASK_REF
   taskledger task follow-up PARENT_REF TITLE [options]
   taskledger todo done TODO_ID --task TASK_REF --evidence "pytest -q"
   taskledger question answer QUESTION_ID --task TASK_REF --text "Yes."
   taskledger handoff show HANDOFF_ID --task TASK_REF
   taskledger require add REQUIRED_TASK_REF --task TASK_REF
   taskledger release show 0.4.1

Release commands
----------------

Release boundaries are durable project records, not task lifecycle states:

.. code-block:: bash

   taskledger release tag 0.4.1 --at-task task-0030 --note "0.4.1 released"
   taskledger release list
   taskledger release show 0.4.1
   taskledger release changelog 0.4.2 --since 0.4.1 --until-task task-0035 --output /tmp/taskledger-0.4.2-changelog-source.md

``release tag`` writes a durable release record under the current ledger's
``releases/`` directory.
``release changelog`` is read-oriented: it renders Markdown or JSON changelog
context from done tasks and may write an external output file, but it does not
mutate ledger state.

Ledger commands
---------------

Branch-scoped ledgers isolate ignored local task state by the checked-in
``ledger_ref`` stored in ``.taskledger.toml``:

.. code-block:: bash

   taskledger ledger status
   taskledger ledger list
   taskledger ledger fork feature-a
   taskledger ledger switch main
   taskledger ledger adopt --from feature-a task-0030
   taskledger ledger doctor

``ledger fork`` creates a new local namespace under
``.taskledger/ledgers/<ref>/`` and updates only Taskledger-owned ledger keys in
``.taskledger.toml``. ``ledger switch`` changes the checked-in pointer to an
existing local ledger. ``ledger adopt`` copies a task from another local ledger
into the current ledger and renumbers on collision.
``next-action`` result contract
-------------------------------

``taskledger next-action`` is the preferred fresh-context entrypoint for agents
and operators. It should identify the next concrete question, todo, criterion,
plan, dependency, or repair target instead of only naming a lifecycle bucket.

Human output should stay concise but actionable:

.. code-block:: text

   todo-work: Implementation is in progress; 1 todos remain.
   Next todo: todo-0001 -- Update next-action JSON payload.
   Command: taskledger todo show todo-0001
   Mark todo done after evidence exists: taskledger todo done todo-0001 --evidence "..."
   Progress: 0/1 todos done

JSON output preserves the existing fields:

* ``kind``
* ``task_id``
* ``status_stage``
* ``active_stage``
* ``action``
* ``reason``
* ``blocking``
* ``next_command``

and may also include:

* ``next_item`` for the concrete target
* ``commands`` for ordered command hints with one primary command
* ``progress`` for question, todo, or validation queues
* ``template_command`` plus ``required_plan_fields`` and
  ``recommended_plan_fields`` when the next step is regenerating a plan from
  answered questions
* ``guidance_command`` when planning guidance should be reviewed before drafting
  or regenerating a plan

Agents should inspect ``next_item``, prefer ``next_command`` when it is safe,
avoid inventing question answers, and never mark todos done without evidence.

When a task is in ``failed_validation``, ``next-action`` should direct agents
back to implementation with ``taskledger implement restart --summary SUMMARY``.

When a task persists ``planning``, ``implementing``, or ``validating`` as its
status but ``active_stage`` is missing, ``next-action`` must not report
``The task is cancelled.`` For an orphaned implementation with a still-running
latest implementation run and no active lock, it should direct agents to
``taskledger implement resume --task TASK_REF --reason "..."``.
For an approved task with a non-implementation run still marked running,
``next-action`` must not direct agents to ``taskledger implement start``.
It should report a repair-oriented action and point to ``taskledger doctor``.
Truly cancelled tasks recover through
``taskledger task uncancel --task TASK_REF --reason "..."``

Compact mutation output
........................

Mutation commands emit compact acknowledgements instead of full task or run records.
This reduces LLM context consumption during implementation loops.

The following commands produce compact output:

- ``todo add``: emits ``todo_added`` result with new todo, progress, and next command.
- ``todo done`` / ``todo undone``: emits ``todo_update`` result with todo id, status, progress, and next command.
- ``implement finish``: emits ``task_lifecycle`` result with task id, run id, status, and next command.

Human mode shows a one-line summary:

.. code-block:: text

   added todo-0001 on task-0001  (0/3 done)
   done todo-0001 on task-0001  (1/3 done)
   finished implementation run-0001  task task-0001 -> implemented

JSON mode wraps the compact result in the standard success envelope with ``result_type``.

For full task, run, or todo details after a mutation, use:

- ``taskledger task show`` or ``taskledger status`` for task-level detail.
- ``taskledger todo show TODO_ID`` for individual todo detail.
- ``taskledger next-action`` for the next concrete step.
- ``taskledger todo next`` for the next open todo.
to a durable non-active stage rather than directly re-entering an active stage.

Run and lock repair
-------------------

Managed command wrappers
------------------------

``plan command`` and ``implement command`` mirror the inner command exit code by
default.

Use ``--allow-failure`` when you intentionally want to record a non-zero inner
exit code while returning wrapper exit code ``0``:

.. code-block:: bash

   taskledger plan command -- pytest tests/ -q
   taskledger plan command --allow-failure -- pytest tests/ -q
   taskledger implement command -- ruff check --config=.ruff.toml .
   taskledger implement command --allow-failure -- python -c "raise SystemExit(7)"

Transcript review modes
-----------------------

``task transcript`` defaults to review mode, which groups wrapper +
managed-shell pairs, highlights failures and wrapper/managed mismatches, and
flags late lifecycle commands. Raw per-record audit table is available with
``--raw``::

.. code-block:: bash

   taskledger task transcript --task TASK_REF
   taskledger task transcript --task TASK_REF --raw
   taskledger task transcript --task TASK_REF --failures

``--review`` is the default (no flag needed). ``--raw`` shows every record
without collapsing. ``--failures`` renders only failed command rows and retry
detection. ``--raw``, ``--review``, and ``--failures`` are mutually exclusive.

``taskledger doctor`` and ``taskledger doctor locks`` report running runs without
matching active locks. Orphaned running planning runs can be finished only
through an explicit repair command with a reason:

.. code-block:: bash

   taskledger repair run --task TASK_REF --run RUN_ID --reason "Planning was already completed."

The repair command refuses to finish non-planning runs, non-running runs, or
runs that still have a matching active lock.

Post-completion follow-up deltas
--------------------------------

``taskledger task follow-up PARENT_REF TITLE`` is the supported path for small
post-completion changes. It requires a ``done`` parent task, creates a new draft
child task with ``parent_task_id`` and ``parent_relation=follow_up``, and keeps
the parent task terminal.

Human monitoring UI
-------------------

``taskledger serve`` is a top-level human-oriented monitoring command:

.. code-block:: bash

   taskledger serve [--host 127.0.0.1] [--port 8765] [--task TASK_REF] [--refresh-ms 1000] [--open/--no-open]

Rules:

* the MVP binds only to localhost;
* it serves read-only HTML plus read-only JSON endpoints;
* browser actions are not part of the MVP;
* agents should continue to use ``next-action``, ``context``, ``view``, and
  ``--json`` commands as the canonical automation interface.

Focused context and handoff options
-----------------------------------

Focused worker contexts keep lifecycle ``mode`` separate from worker-role
``--for``:

.. code-block:: bash

   taskledger context --for planner|implementer|validator|spec-reviewer|code-reviewer|reviewer|full [--scope task|todo|run] [--todo TODO_ID] [--run RUN_ID] [--format markdown|json|text] [--task TASK_REF]
   taskledger handoff create --mode planning|implementation|validation|review|full [--for planner|implementer|validator|spec-reviewer|code-reviewer|reviewer|full] [--scope task|todo|run] [--todo TODO_ID] [--run RUN_ID] [--task TASK_REF]
   taskledger handoff show HANDOFF_ID --format text|markdown|json [--task TASK_REF]

Rules:

* ``--todo`` implies ``--scope todo``.
* ``--run`` implies ``--scope run``.
* ``--scope todo`` requires ``--todo``.
* ``--scope run`` requires ``--run``.
* ``--for implementation|validation|planning|review|full`` remain accepted as
  compatibility aliases.
* ``handoff show --format markdown`` prints the stored snapshot body.

Removed Pre-Release Aliases
---------------------------

These aliases are intentionally not registered:

* ``task new``
* ``task clear-active``
* ``implement add-change``
* ``validate add-check``
* ``file link``
* ``file unlink``
* ``link link``
* ``link unlink``

Use ``task create``, ``task deactivate``, ``implement change``,
``validate check``, ``file add``, ``file remove``, ``link add``, and
``link remove`` instead.

Approval escape hatches
-----------------------

Plan approval escape hatches require ``--reason`` to prevent silent bypass:

+--------------------------+--------------------------------------------------+------------------------+
| Flag                     | Effect                                           | Requires ``--reason``  |
+==========================+==================================================+========================+
| ``--allow-empty-criteria`` | Skip the acceptance criteria requirement       | Yes                    |
+--------------------------+--------------------------------------------------+------------------------+
| ``--allow-open-questions`` | Approve despite open planning questions        | Yes                    |
+--------------------------+--------------------------------------------------+------------------------+
| ``--allow-empty-todos``    | Approve despite no todos in the plan           | Yes                    |
+--------------------------+--------------------------------------------------+------------------------+
| ``--no-materialize-todos`` | Skip materializing plan todos into the checklist | Yes                  |
+--------------------------+--------------------------------------------------+------------------------+
| ``--allow-agent-approval`` | Allow agent (non-user) approval                | Yes (plus ``--reason``) |
+--------------------------+--------------------------------------------------+------------------------+
| ``--allow-lint-errors``    | Approve despite plan lint errors               | Yes                    |
+--------------------------+--------------------------------------------------+------------------------+

Approval also requires ``--note`` for user approval. Agent approval additionally
requires ``--allow-agent-approval --reason "..."``.

Todo source inference
---------------------

When ``todo add`` is called without an explicit ``--source``, the source is
inferred from the active lock:

+-------------------+-----------------+
| Active lock stage | Inferred source |
+===================+=================+
| ``implementing``  | ``implementer`` |
+-------------------+-----------------+
| ``planning``      | ``planner``     |
+-------------------+-----------------+
| No active lock    | ``user``        |
+-------------------+-----------------+

Plan-materialized todos always use ``source=plan``.

Storage Compatibility
---------------------

Taskledger stores project-local configuration in ``taskledger.toml`` at the
workspace root. ``.taskledger.toml`` is also read as a local override file when
it exists.

The resolved ``taskledger_dir`` defaults to ``.taskledger/`` beside that config
file, but ``taskledger init --taskledger-dir /path/to/state`` may point durable
state elsewhere. Commands resolve config files upward from the starting
directory and keep ``--root`` scoped to the source workspace, not the storage
root.

Taskledger uses:

* a workspace storage layout version in ``taskledger_dir/storage.yaml``
* per-record ``schema_version``
* per-record ``object_type``
* per-file ``file_version`` for durable Markdown/YAML/JSON record files

Storage layout version history:

* Layout 2: Introduced branch-scoped ledgers under ``taskledger_dir/ledgers/<ledger_ref>/``
* Layout 3: Consolidates layout-2 root-level task state into branch-scoped ledgers; migrates legacy root ``tasks/``, ``events/``, ``intros/``, ``releases/``, and ``active-task.yaml`` into the active ledger namespace

Taskledger does not silently rewrite storage during read-only commands.

If the installed taskledger version can read but not write an older workspace,
it reports that migration is required.

To migrate:

.. code-block:: bash

   taskledger migrate status
   taskledger migrate plan
   taskledger migrate apply --backup

After migration to layout 3, verify health with:

.. code-block:: bash

   taskledger doctor
   taskledger ledger doctor

Indexes under ``taskledger_dir/ledgers/<ledger_ref>/indexes/`` are optional derived caches or
registries. Task, plan, and run commands must continue to work from canonical
Markdown/YAML records even when task/run/plan JSON cache files are absent. The
remaining derived caches may be plain JSON arrays with no version metadata and
can be rebuilt with:

.. code-block:: bash

   taskledger reindex

A newer storage version than the installed taskledger supports is rejected with
a clear error.
