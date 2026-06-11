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
   taskledger review record --task task-0001 --result pass --summary "No blocking issues."
   taskledger validate status --task task-0001

Task-resource commands accept the task as their direct positional resource:

.. code-block:: bash

   taskledger task show task-0001
   taskledger task cancel task-0001 --reason "Duplicate"
   taskledger task archive task-0001 --reason "Hide historical task"
   taskledger task unarchive task-0001 --reason "Restore task"
   taskledger task report task-0001

Fresh-session and monitoring commands are top-level read surfaces:

.. code-block:: bash

   taskledger usage [TASK_REF] [--task TASK_REF] [-q]
   taskledger --json usage
   taskledger monitor [TASK_REF] [--task TASK_REF] [--refresh-seconds 2] [--once] [--max-events 10] [--max-ready 10] [--plain] [--no-clear]

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

Taskledger stores task-local work state and opaque links. Cross-ledger
semantics belong to an organizer such as ledgerdeck.

Relevant commands for external artifact references:

.. code-block:: bash

   taskledger link add --url specs/behavior/features/checkout/payment.feature --label "behavior spec"
   taskledger file link specs/behavior/features/checkout/payment.feature --kind doc --label "behavior spec"
   taskledger validate check --criterion ac-0001 --status pass --evidence "pytest tests/test_checkout_payment.py::test_payment_flow"

Rules:

* Links are opaque. Taskledger does not parse or interpret linked files.
* Validation evidence is recorded through generic ``validate check``.

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
``ledger_ref`` stored in ``taskledger.toml``:

.. code-block:: bash

   taskledger ledger status
   taskledger ledger list
   taskledger ledger fork feature-a
   taskledger ledger switch main
   taskledger ledger adopt --from feature-a task-0030
   taskledger ledger doctor

``ledger fork`` creates a new local namespace under
``.taskledger/ledgers/<ref>/`` and updates only Taskledger-owned ledger keys in
``taskledger.toml``. ``ledger switch`` changes the checked-in pointer to an
existing local ledger. ``ledger adopt`` copies a task from another local ledger
into the current ledger and renumbers on collision.

Storage and sync helper commands
--------------------------------

Taskledger also exposes local storage discovery and sync helpers:

.. code-block:: bash

   taskledger storage where
   taskledger storage move --to ../taskledger-state/project-a --mode copy|move [--adopt-existing] [--force]
   taskledger sync preflight
   taskledger sync status
   taskledger sync commit --message "Sync project-a taskledger state"
   taskledger sync export --output ./taskledger-transfer.tar.gz
   taskledger sync import ./taskledger-transfer.tar.gz --dry-run
   taskledger sync git status
   taskledger sync git init --repo ../taskledger-state --project-path project-a
   taskledger sync git commit --message "Sync project-a taskledger state"
   cd "$(taskledger sync git cd)"
   git pull --ff-only
   git push
   taskledger sync git hooks install
   taskledger sync git hooks status
   taskledger sync git hooks uninstall

Rules:

* ``storage where`` is read-only and reports the resolved workspace root,
  config path, ``taskledger_dir``, project identity, ledger ref, Git detection,
  and active lock count.
* ``storage move`` updates ``taskledger.toml`` atomically after the target has
  been copied or explicitly adopted.
* ``sync preflight`` performs only local checks. It must not perform network
  push/pull operations.
* ``sync status`` and ``sync commit`` operate only on the Git repository that
  contains the resolved ``taskledger_dir``.
* ``sync export`` and ``sync import`` are archive aliases for the root
  ``export``/``import`` commands.
* ``sync git`` commands operate on a private external Git repository that stores
  full project taskledger state under ``<repo>/<project_path>``.

Config commands
---------------

Project config inspection and edits are available under ``config``:

.. code-block:: bash

   taskledger config list
   taskledger config show
   taskledger config keys
   taskledger config get prompt_profiles.planning.max_required_questions
   taskledger config describe prompt_profiles.planning.plan_body_detail
   taskledger config set prompt_profiles.planning.max_required_questions 3
   taskledger config set prompt_profiles.planning.question_policy always_before_plan

Rules:

* dotted keys target nested TOML tables (for example
  ``prompt_profiles.planning.max_required_questions``);
* ``config keys`` lists available key names and path patterns;
* ``config describe`` provides key semantics, allowed values, defaults, and
  whether a key is explicitly set;
* ``config set`` accepts TOML literals (numbers, booleans, arrays, inline
  tables); when TOML parsing fails, the value is treated as a plain string;
* invalid values are rejected using standard LaunchError JSON/human envelopes.

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
   Worker step: tester
   Worker context: taskledger pipeline context tester
   Worker handoff: taskledger handoff create --worker tester --summary "..."
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
* ``worker_pipeline`` when an enabled ``guided`` worker pipeline has a pending
  step; this object includes ``enabled``, ``mode``, ``next_step``,
  ``context_command``, and ``handoff_command``
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
``--raw``.

.. code-block:: bash

   taskledger task transcript --task TASK_REF
   taskledger task transcript --task TASK_REF --raw
   taskledger task transcript --task TASK_REF --failures

``--review`` is the default (no flag needed). ``--raw`` shows every record
without collapsing. ``--failures`` renders only failed command rows and retry
detection. ``--raw``, ``--review``, and ``--failures`` are mutually exclusive.


``task export`` writes a Markdown file with a deterministic body combining a curated
archive report, raw task-bundle record files, and optional source-file snapshots.
It is the recommended command for handing a task to an LLM/coding agent.

.. code-block:: bash

   taskledger task export TASK_REF -o task.llm.md
   taskledger task export --task TASK_REF --no-source-files -o task.records.md
   taskledger --json task export TASK_REF -o task.llm.md

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

``taskledger usage`` is the compact fresh-session startup command:

.. code-block:: bash

   taskledger usage [TASK_REF] [--task TASK_REF] [-q]
   taskledger --json usage

Rules:

* it is read-only and must not claim handoffs, repair locks, or mutate task
  state;
* root ``--json`` returns the standard CLI envelope with ``result.kind ==
  "usage"``;
* it summarizes actor, harness, active work, inbox items, and ready tasks;
* agents should continue to use ``next-action``, ``todo next``, and other JSON
  commands as the canonical same-session automation interface.

``taskledger monitor`` is the dependency-free human-oriented terminal monitor:

.. code-block:: bash

   taskledger monitor [TASK_REF] [--task TASK_REF] [--refresh-seconds 2] [--once] [--max-events 10] [--max-ready 10] [--plain] [--no-clear]

Rules:

* it is read-only and never mutates ``.taskledger/`` state;
* root ``--json`` prints a single ``monitor_snapshot`` payload and exits;
* non-JSON mode refreshes on a timer until interrupted;
* ``--plain`` disables styling and ``--no-clear`` appends snapshots instead of
  clearing the terminal;
* it replaces the removed server/TUI surface; agents should keep using JSON
  commands for automation.

Focused context and handoff options
-----------------------------------

Code review commands
--------------------

``review`` stores optional durable code-review evidence without adding a new
lifecycle stage. Review evidence may be recorded before validation or after a
task has reached ``done``; storing the review remains append-only and does not
reopen the completed task:

.. code-block:: bash

   taskledger review record [--task TASK_REF] --result pass|fail|blocked (--summary TEXT | --summary-file PATH) [--from-git] [--commit COMMIT] [--worker STEP_ID] [--handoff HANDOFF_ID] [--run RUN_ID]
   taskledger review list [--task TASK_REF]
   taskledger review show REVIEW_REF [--task TASK_REF]

JSON mode returns a stable payload with ``kind = "code_review_recorded"`` for
``review record`` and includes ``review_id``, ``task_id``, ``result``,
``source``, ``implementation_run``, ``worker_step_id``, and compact git
metadata fields when present.

When a user explicitly asks an agent for a review, the agent should persist
the final review with ``taskledger review record`` before answering. A
chat-only review is not durable task evidence. Post-completion review
records are append-only and do not reopen the task.

Focused worker contexts keep lifecycle ``mode`` separate from worker-role
``--for``:

.. code-block:: bash

   taskledger context --for planner|implementer|validator|spec-reviewer|code-reviewer|reviewer|full [--scope task|todo|run] [--todo TODO_ID] [--run RUN_ID] [--format markdown|json|text] [--task TASK_REF]
   taskledger handoff create --mode planning|implementation|validation|review|full [--for planner|implementer|validator|spec-reviewer|code-reviewer|reviewer|full] [--scope task|todo|run] [--todo TODO_ID] [--run RUN_ID] [--task TASK_REF]
   taskledger handoff create --worker STEP_ID [--scope task|todo|run] [--todo TODO_ID] [--run RUN_ID] [--task TASK_REF]
   taskledger pipeline context STEP_ID [--scope task|todo|run] [--todo TODO_ID] [--run RUN_ID] [--format markdown|json|text] [--task TASK_REF]
   taskledger handoff show HANDOFF_ID --format text|markdown|json [--task TASK_REF]

Rules:

* ``--todo`` implies ``--scope todo``.
* ``--run`` implies ``--scope run``.
* ``--scope todo`` requires ``--todo``.
* ``--scope run`` requires ``--run``.
* ``--for implementation|validation|planning|review|full`` remain accepted as
  compatibility aliases.
* ``handoff create --worker`` derives mode and context from the configured
  worker step and stores ``worker_step_id`` in the handoff record.
* ``pipeline context STEP_ID`` is equivalent to ``context --worker STEP_ID``.
* ``spec-reviewer`` and ``code-reviewer`` worker contexts require ``--run`` or
  explicit ``--scope task`` when they are not bound to a validation/review run.
* ``handoff show --format markdown`` prints the stored snapshot body.

Removed Pre-Release Aliases
---------------------------

These aliases are intentionally not registered:

* ``task new``
* ``task clear-active``
* ``implement add-change``
* ``validate add-check``
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

Lock recovery contract
--------------------

Lock diagnostics are exposed through three surfaces:

- ``taskledger lock show --task TASK`` returns a ``diagnostics`` object and
  a structured human block. The ``classification`` field names the lock
  state: ``none``, ``expired``, ``active_dead_local_process``,
  ``active_live_local_process``, ``active_unverifiable_remote_or_unknown_process``,
  ``active_no_pid``, ``active_same_actor``, or ``active_other_actor``.
- ``taskledger --json next-action`` returns ``lock_status`` whenever a lock
  exists, and sets ``action=repair-lock`` with a diagnostics blocker when the
  active implementation lock has a dead local holder PID.
- ``taskledger implement resume --repair-expired-lock`` returns a
  ``LOCK_CONFLICT`` error (exit code 4) with diagnostics and remediation
  commands when the existing lock is non-expired.

``--repair-expired-lock`` is not a general stale-lock takeover flag. It only
applies to locks whose ``expires_at`` is in the past. For non-expired active
locks, follow the classification returned by ``lock show`` or ``next-action``.

For non-expired active locks classified as ``active_dead_local_process``, the
canonical recovery sequence is:

.. code-block:: bash

   taskledger repair lock --task TASK --reason "Holder PID ... is no longer running."
   taskledger implement resume --task TASK --reason "Reacquire implementation lock after stale holder repair."

For ``active_live_local_process`` or ``active_other_actor``, do not repair;
use a handoff or wait for the holder to release. For
``active_unverifiable_remote_or_unknown_process``, do not infer staleness
from local process checks; inspect handoffs or ask the user before repairing.
