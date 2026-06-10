Usage
=====

Installation
------------

.. code-block:: bash

   python -m pip install -e .
   python -m pip install -e ".[dev]"

Shell completion
----------------

After installing ``taskledger``, install completion for the current shell:

.. code-block:: bash

   taskledger --install-completion

To print the generated completion script without installing it:

.. code-block:: bash

   taskledger --show-completion

Restart your shell session after installation.

Agent workflows work best when the ``taskledger`` skill is installed in the
coding harness. The CLI uses a task-first lifecycle with explicit planning,
approval, implementation, validation, locks, and handoff gates; without the
skill, an agent may not know the intended command sequence or gate semantics.

Initialize state
----------------

.. code-block:: bash

   taskledger init
   taskledger init --taskledger-dir /mnt/cloud/taskledger/project-a

``taskledger init`` writes ``taskledger.toml`` in the workspace root. The
config defaults to ``taskledger_dir = ".taskledger"`` and stores only safe
branch-scoped ledger state such as ``ledger_ref`` and
``ledger_next_task_number``. ``.taskledger/`` remains ignored and stores
operational task state under ``.taskledger/ledgers/<ledger_ref>/``.

Branch-local task work
----------------------

When creating a long-lived Git branch, fork the Taskledger ledger pointer so
active task state, plans, todos, events, indexes, and releases stay isolated
from the parent branch:

.. code-block:: bash

   git checkout -b feature-a
   taskledger ledger fork feature-a
   git add taskledger.toml

When Git later restores the parent branch's ``taskledger.toml``, default
commands read the parent ledger again. Duplicate logical IDs such as
``task-0030`` in two ledgers are expected. Use ``taskledger ledger adopt --from
feature-a task-0030`` to copy branch-local task history into the current ledger.
Task-first workflow
-------------------

.. code-block:: bash

   taskledger task create rewrite-v2 --description "Migrate to the task-first design."
   taskledger task activate rewrite-v2
   taskledger plan start
   taskledger question add --text "Should exports include v2?"
   taskledger question answer-many --text "q-0001: Yes."
   taskledger plan upsert --from-answers --criterion "Accepted workflow is implemented." --file ./plan.md
   taskledger plan review --version 1
   taskledger plan lint --version 1
   taskledger plan accept --version 1 --note "Ready."

Optional behavior-spec overlay
------------------------------

Use behavior specs only when the task benefits from executable examples. Keep
canonical specs and plain pytest enforcement outside Taskledger:

.. code-block:: text

   specs/behavior/features/<area>/<feature>.feature
   tests/test_<area>_<feature>.py
   reports/behavior/<area>-<feature>-junit.xml

Taskledger may store task-local BDD/example records, link them to external
specs and pytest node ids, and export derived JSON exchange data:

.. code-block:: bash

   taskledger bdd example link-automation bdd-0001 --feature-file specs/behavior/features/task-management/plan-gates.feature --scenario @bdd-implementation-blocked-before-plan-acceptance --pytest tests/test_task_management_plan_gates.py::test_agent_cannot_start_implementation_before_plan_approval
   taskledger bdd export-json --out .specweave/mappings/taskledger/task-0001.bdd.json
   taskledger validate import-bdd-report reports/behavior/task-management-plan-gates-junit.xml --format junit-xml --command "pytest tests/test_task_management_plan_gates.py --junitxml=reports/behavior/task-management-plan-gates-junit.xml"

``taskledger bdd gherkin-export`` remains available for derived `.feature`
output, but taskledger should not promote ``tests/bdd/features``,
``specs/bdd/features``, ``tests/behavior/``, or pytest-bdd step modules as the
canonical layout.

Planning guidance profiles
--------------------------

Taskledger supports project-local advisory planning guidance for agents. Configure
it in the active project config file discovered for your workspace. Newer
projects usually use ``taskledger.toml``. Existing projects may still use
``.taskledger.toml``; if both files exist, ``.taskledger.toml`` is discovered
first.

Configure ``[prompt_profiles.planning]`` in that active config:

.. code-block:: toml

   [prompt_profiles.planning]
   profile = "strict"
   question_policy = "always_before_plan"
   max_required_questions = 3
   min_acceptance_criteria = 2
   todo_granularity = "atomic"
   require_files = true
   require_test_commands = true
   require_expected_outputs = true
   require_validation_hints = true
   plan_body_detail = "detailed"
   required_question_topics = ["scope", "compatibility", "test strategy"]
   extra_guidance = "Every plan must mention docs, tests, and rollback or repair behavior."

Accepted values:

* ``profile``: ``compact``, ``balanced``, ``strict``, ``exploratory``
* ``question_policy``: ``ask_when_missing``, ``always_before_plan``, ``minimal``
* ``todo_granularity``: ``minimal``, ``implementation_steps``, ``atomic``
* ``plan_body_detail``: ``terse``, ``normal``, ``detailed``
* ``max_required_questions`` and ``min_acceptance_criteria`` must be positive integers
* ``require_files``, ``require_test_commands``, ``require_expected_outputs``, and
  ``require_validation_hints`` must be booleans
* ``required_question_topics`` must be a list of strings
* ``extra_guidance`` must be a string up to 4000 characters

Inspect guidance for the active task:

.. code-block:: bash

   taskledger plan guidance
   taskledger plan guidance --task task-0001
   taskledger --json plan guidance
   taskledger plan guidance --format json

Planning workflow integration:

.. code-block:: bash

   taskledger plan start
   taskledger plan guidance
   taskledger plan template --include-guidance --file plan.md
   taskledger plan lint --version 1
   taskledger plan upsert --file plan.md

Revising a proposed plan safely:

.. code-block:: bash

   taskledger plan revise
   taskledger plan export --version latest --file ./plan.md
   # edit ./plan.md (never edit .taskledger/ directly)
   taskledger plan upsert --file ./plan.md
   taskledger plan diff --from 1 --to 2

For structured scope trims, use:

.. code-block:: bash

   taskledger plan amend --drop-criterion ac-0007 --drop-todo plan-todo-0010 --reason "User reduced scope."

Guidance output is deterministic and read-only. It is advisory only and does not
enforce plan fields by itself. It cannot override lifecycle gates, plan approval,
validation requirements, lock rules, required user answers, or higher-priority
harness instructions.

Optional worker pipelines
-------------------------

Projects may optionally configure worker pipelines in ``taskledger.toml`` to
guide fresh-context handoffs without changing the underlying task lifecycle.
Worker pipelines are advisory overlays on the existing planning,
implementation, and validation lifecycle. They can be three steps, four steps,
five steps, or custom. When no worker pipeline is configured, taskledger
behavior is unchanged.

Example configuration:

.. code-block:: toml

   [worker_pipeline]
   enabled = true
   name = "api-contract-first"
   mode = "guided"

   [[worker_pipeline.steps]]
   id = "planner"
   lifecycle_stage = "planning"
   base_context = "planner"

   [[worker_pipeline.steps]]
   id = "tester"
   label = "Test Writer"
   lifecycle_stage = "implementation"
   base_context = "implementer"
   actor_role = "implementer"
   kind = "check"
   description = "Add or update failing tests before code changes."
   required_output = ["New or updated failing tests with a short summary."]
   must_not = ["Do not change production code in this step."]
   todo_tag = "tests"
   test_command_policy = "may_fail"

   [[worker_pipeline.steps]]
   id = "coder"
   lifecycle_stage = "implementation"
   base_context = "implementer"
   kind = "todo"
   description = "Implement the approved change and make the tests pass."
   required_output = ["Code changes plus passing targeted checks."]
   must_not = ["Do not skip required validation evidence."]
   todo_tag = "implementation"
   test_command_policy = "must_pass"

   [[worker_pipeline.steps]]
   id = "domain-reviewer"
   lifecycle_stage = "review"
   base_context = "spec-reviewer"
   kind = "review"

Supported top-level keys are ``enabled``, ``name``, ``mode``, and ``steps``.
Supported step keys are ``id``, ``label``, ``lifecycle_stage``,
``base_context``, ``actor_role``, ``kind``, ``description``,
``required_output``, ``must_not``, ``todo_tag``, and
``test_command_policy``. ``guided`` mode remains advisory: it does not add
new planning, implementation, or validation gates. Instead it augments
``taskledger next-action`` with worker-step metadata plus ready-to-run worker
context and handoff commands for the pending step.

Inspect and use the configured overlay explicitly:

.. code-block:: bash

   taskledger pipeline show
   taskledger pipeline list
   taskledger pipeline next
   taskledger next-action
   taskledger pipeline context tester
   taskledger context --worker tester
   taskledger handoff create --worker tester --summary "Add failing tests only."
   taskledger handoff create --worker domain-reviewer --scope task --summary "Review the implementation."

To include worker-step todo hints in a plan template, enable a worker pipeline
with ``mode = "template"`` or ``mode = "guided"`` and opt in per task:

.. code-block:: bash

   taskledger plan template --with-worker-pipeline --file ./plan.md

Use ``worker_step`` only on plan todos for projects that have an enabled worker
pipeline:

.. code-block:: yaml

   todos:
     - id: plan-todo-0001
       text: "Add failing regression tests."
       worker_step: "tester"
       validation_hint: "pytest -q tests/test_parser.py"

Release tagging and changelog context
-------------------------------------

Use durable release tags to mark completed task boundaries and generate
provider-neutral changelog source context from done tasks:

.. code-block:: bash

   taskledger release tag 0.4.1 --at-task task-0030 --note "0.4.1 released"
   taskledger release changelog 0.4.2 --since 0.4.1 --until-task task-0035 --output /tmp/taskledger-0.4.2-changelog-source.md
   taskledger release show 0.4.1
   taskledger release list

``release changelog`` renders Markdown or JSON context for an external LLM or
human changelog drafting step. It does not call a model provider directly.

Recording manually completed work
---------------------------------

For work completed outside the task-first lifecycle (operational tasks,
exploratory work, or manual testing), use ``task record`` to create a done
task directly without acquiring locks or lifecycle gates. **Never use**
``task record`` as a shortcut for active task management.

.. code-block:: bash

   taskledger task record "Deploy v0.4.1" --summary "Deployed to production" --change "deploy.sh:run:Updated config" --evidence "Monitoring shows no errors"
   taskledger task record "Manual testing" --summary "Tested new API endpoints" --allow-empty-record --reason "Exploratory testing"

Archiving tasks
---------------

Archiving hides tasks from default list/tree/dashboard views without deleting
history. It is a visibility operation, not an export archive operation.

.. code-block:: bash

   taskledger task archive task-0030 --reason "Hide historical task"
   taskledger task list --archived
   taskledger task unarchive task-0030 --reason "Reopen historical task" --slug task-0030-reopened
   taskledger tree --include-archived

Post-completion follow-up deltas
--------------------------------

When a task is already ``done`` and the user requests a small later change, do
not reopen the completed task. Create a follow-up task linked to the completed
parent and run the normal lifecycle on that child:

.. code-block:: bash

   taskledger task follow-up rewrite-v2 "Rename submit label" --description "Small post-completion delta." --activate
   taskledger plan start
   taskledger plan upsert --file ./plan.md
   taskledger plan review --version 1
   taskledger plan accept --version 1 --note "Ready."
   taskledger implement start
   taskledger validate start

``task follow-up`` keeps ``done`` terminal on the parent task while preserving a
traceable child record for the new delta.

Fresh-context entrypoint
------------------------

Use ``taskledger next-action`` before a broad ``context`` read when you need the
next concrete work item instead of a generic stage summary.

.. code-block:: bash

   taskledger next-action
   taskledger --json next-action

Human output now names the next question, todo, criterion, or repair step and
includes the primary command hint. JSON output preserves the existing
``task_next_action`` fields and also includes ``next_item``, ``commands``, and
``progress``.

Agents should inspect ``next_item`` first, run ``next_command`` when it is safe,
avoid inventing question answers, and only mark todos done after evidence exists.

If ``next-action`` reports an orphaned implementation state or an active lock
recovery situation, inspect the task and lock first, then choose the recovery
path that matches the lock state:

.. code-block:: bash

   taskledger task show
   taskledger task show task-0001
   taskledger lock show
   taskledger doctor

Lock recovery decision tree:

1. Run ``taskledger lock show --task TASK``. ``lock show`` reports a
   ``classification`` field that names the lock state.
2. If there is no lock, run ``taskledger next-action``.
3. If ``classification`` is ``expired`` and the lock is an implementation lock
   for a running implementation run:
   run
   ``taskledger implement resume --repair-expired-lock --task TASK --reason "..."``.
4. If ``classification`` is ``active_dead_local_process``:
   run
   ``taskledger repair lock --task TASK --reason "Holder PID ... is no longer running."``,
   then ``taskledger implement resume --task TASK --reason "..."``.
5. If ``classification`` is ``active_live_local_process`` or
   ``active_other_actor``:
   do not repair; use a handoff or wait for the holder to release.
6. If ``classification`` is ``active_unverifiable_remote_or_unknown_process``:
   do not infer staleness from local process checks; inspect handoffs or ask
   the user before repairing.
7. ``next-action`` itself returns ``action=repair-lock`` with diagnostics and
   the recommended command sequence when the active implementation lock has
   a dead local holder PID.

``--repair-expired-lock`` is not a general stale-lock takeover flag. It only
handles locks whose ``expires_at`` is in the past. For non-expired active
locks, use the decision tree above.

If the task is actually ``cancelled`` and the user wants to continue, restore it
with ``task uncancel`` first, then run ``next-action`` again. A restored task may
return to a safe durable stage such as ``approved`` while an implementation run
is still ``running``; in that case use ``implement resume`` instead of
``implement start``.

Compact implementation loop
---------------------------

For routine same-session implementation, prefer ``next-action`` and the next todo
over a broad generated context read:

.. code-block:: bash

   taskledger --json next-action
   taskledger --json todo next
   taskledger todo show todo-0003
   # implement only that todo
   pytest tests/...
   taskledger todo done todo-0003 --evidence "pytest tests/... passed"
   taskledger --json next-action

Rules for agents:

* Install the ``taskledger`` skill in the coding harness before relying on agent-driven workflows.
* Prefer ``next-action`` and ``todo next`` over generated context during normal work.
* Use the todo ``validation_hint`` before marking a todo done.
* Record concise evidence with ``todo done``.
* Do not create handoffs or context bundles unless the user asked to switch harness or session.

Fresh-session startup and monitoring
------------------------------------

Use ``taskledger usage`` as the compact startup command for a fresh coding-agent
session:

.. code-block:: bash

   taskledger usage
   taskledger --json usage
   taskledger usage -q
   taskledger usage --task task-0040

``usage`` is read-only. It summarizes actor/harness identity, active work,
claimable handoffs, review-ready items, stale locks, open questions, and ready
tasks. JSON output preserves the existing envelope and returns
``result.kind == "usage"``.

``taskledger monitor`` replaces the removed browser/TUI surfaces with a
dependency-free terminal snapshot:

.. code-block:: bash

   taskledger monitor --once
   taskledger monitor --refresh-seconds 2
   taskledger monitor --task task-0040
   taskledger --json monitor --once

``monitor`` is read-only, works on narrow terminals such as Termux, and keeps
using taskledger's normal read models instead of introducing a separate UI
stack. Agents should continue to use ``next-action``, ``todo next``, and
``--json`` as the canonical machine interface for routine same-session work.

Linked file baselines and drift
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Linked files can now capture a baseline snapshot and later report drift:

.. code-block:: bash

   taskledger file link task-0040 src/foo.py --kind code --snapshot
   taskledger file status task-0040
   taskledger file refresh task-0040 src/foo.py --reason "Rebaseline after accepted implementation"

``file status`` reports ``new``, ``modified``, ``deleted``, ``unchanged``, and
``unbaselined`` states. It also keeps ``context``: canonical fresh continuation
context and ``handoff show`` as the richer advanced/compatibility read
surfaces when broader state transfer is needed.

``task report`` generates a human-readable Markdown report for a single task.
It is for humans who want to review, archive, or share a task outside the terminal.

.. code-block:: bash

   taskledger task report --task task-0030 -o task30.md
   taskledger task report --preset planning --without todos -o plan-review.md
   taskledger task report --task task-0030 --include command-log
   taskledger task report --task task-0030

``context`` is agent-handoff-oriented. ``task report`` and root ``report`` HTML
commands are human-oriented. ``task dossier`` remains available as an
advanced/compatibility full-context dump; prefer ``context --for ...`` for new
agent protocols.

``task transcript`` renders a per-task command transcript from the ledger-level
agent log store:

.. code-block:: bash

   taskledger task transcript --task task-0030 -o task30-transcript.md
   taskledger task transcript --task task-0030 --include-output
   taskledger task transcript --task task-0030 --raw
   taskledger task transcript --task task-0030 --failures
   taskledger --json task transcript --task task-0030

``task export`` writes a single Markdown file containing a curated archive report, raw
record files from the taskledger bundle, and optional source-file snapshots.
Use it when handing a completed task to an LLM or coding agent for review,
documentation updates, or follow-up implementation work.

.. code-block:: bash

   taskledger task export task-0030 -o task-0030.llm.md
   taskledger task export task-0030 --no-source-files -o task-0030.records.md
   taskledger task export task-0030 --source-file README.md -o task-0030.llm.md
   taskledger --json task export task-0030 -o task-0030.llm.md

Distinction:

- ``task report``: human-readable review/archive report.
- ``context``: canonical fresh continuation context for an active agent.
- ``handoff show``: durable transfer context created for another session or actor.
- ``task dossier``: advanced/compatibility full-context dump.
- ``task transcript``: command audit trail.
- ``task export``: single-file LLM handoff/archive of one complete task bundle.


.. code-block:: text

   todo-work: Implementation is in progress; 1 todos remain.
   Next todo: todo-0001 -- Update next-action JSON payload.
   Command: taskledger todo show todo-0001
   Mark todo done after evidence exists: taskledger todo done todo-0001 --evidence "..."
   Progress: 0/1 todos done

.. code-block:: json

   {
     "kind": "task_next_action",
     "action": "todo-work",
     "next_command": "taskledger todo show todo-0001",
      "next_item": {
        "kind": "todo",
        "id": "todo-0001",
        "text": "Update next-action JSON payload.",
        "validation_hint": "Run: pytest tests/test_todo_implementation_gate.py -q; Expected: pass",
        "done_command_hint": "taskledger todo done todo-0001 --evidence \"...\""
      },
      "commands": [
        {
          "kind": "inspect",
          "label": "Show next todo",
          "command": "taskledger todo show todo-0001",
          "primary": true
        },
        {
          "kind": "complete",
          "label": "Mark todo done after evidence exists",
          "command": "taskledger todo done todo-0001 --evidence \"...\"",
          "primary": false
        }
      ],
     "progress": {
       "todos": {
         "total": 1,
         "done": 0,
         "open": 1,
         "open_ids": ["todo-0001"]
       }
     },
     "blocking": []
   }

All approval escape hatches require ``--reason``:

.. code-block:: bash

   taskledger plan approve --version 1 --actor user --approval-source explicit_chat --note "Ready." --no-materialize-todos --reason "trivial task"
   taskledger plan approve --version 1 --actor user --approval-source explicit_chat --note "Ready." --allow-empty-criteria --reason "no criteria needed"
   taskledger plan approve --version 1 --actor user --approval-source explicit_chat --note "Ready." --allow-lint-errors --reason "user accepted rough plan"

Use ``plan command`` to record diagnostic commands during planning:

.. code-block:: bash

   taskledger plan command -- pytest tests/ -q
   taskledger plan command --allow-failure -- pytest tests/ -q
   taskledger implement command -- ruff check --config=.ruff.toml .
   taskledger implement command --allow-failure -- python -c "raise SystemExit(7)"

When ``[agent_logging].enabled = true`` in ``taskledger.toml``, ``taskledger``
records CLI invocations and managed command outputs. Keep logging opt-in because
stdout/stderr may contain sensitive data. Route task-relevant commands through
``plan command`` and ``implement command`` so their output is included in task
transcripts and reports.

   taskledger context --for implementation --format markdown
   taskledger implement start
   taskledger implement log --message "Started implementation."
   taskledger implement change --path taskledger/storage/task_store.py --kind edit --summary "Updated storage semantics."
   taskledger implement scan-changes --from-git --summary "Implementation diff summary."
   taskledger implement finish --summary "Implemented the approved plan."
   taskledger review record --result pass --summary "No blocking code-quality issues."

   taskledger context --for validation --format markdown
   taskledger validate start
   taskledger validate check --criterion ac-0001 --status pass --evidence "pytest -q tests/test_taskledger_v2_cli.py"
   taskledger validate finish --result passed --summary "Validated the rewrite."

Code review evidence can also be recorded after ``validate finish`` has moved the
task to ``done``. This appends durable review evidence to the task and does not
reopen or otherwise mutate the task lifecycle stage.

When a user explicitly asks an agent for a review, the agent should persist
the final review with ``taskledger review record`` before answering. A
chat-only review is not durable task evidence. Post-completion review
records are append-only and do not reopen the task.

If validation finds an implementation bug and the accepted plan is still
correct, restart implementation instead of replanning:

.. code-block:: bash

   taskledger validate finish --result failed --summary "Parser edge case still fails."
   taskledger next-action
   taskledger context --for implementation --format markdown
   taskledger implement restart --summary "Fix failed validation findings."

If validation finds an implementation bug and the accepted plan is still
correct, restart implementation instead of replanning:

.. code-block:: bash

   taskledger validate finish --result failed --summary "Parser edge case still fails."
   taskledger next-action
   taskledger context --for implementation --format markdown
   taskledger implement restart --summary "Fix failed validation findings."

Machine-readable output
-----------------------

.. code-block:: bash

   taskledger --json status --full
   taskledger --json task active
   taskledger --json task show
   taskledger --json task show task-0001
   taskledger --json context --for validation --format json
   taskledger --json review list --task task-0001

.. code-block:: json

    {
      "ok": true,
      "command": "status",
      "result": {
        "kind": "taskledger_status",
        "workspace_root": "/workspace",
        "config_path": "/workspace/taskledger.toml",
        "taskledger_dir": "/workspace/.taskledger",
        "project_dir": "/workspace/.taskledger",
        "counts": {
          "tasks": 1,
          "introductions": 0,
         "plans": 1,
         "questions": 1,
         "runs": 2,
         "changes": 1,
         "locks": 0
       },
       "active_task": null,
       "healthy": true
      },
      "events": []
    }

Cloud-backed storage
--------------------

Use one storage root per source project:

.. code-block:: bash

   taskledger init --taskledger-dir /mnt/cloud/taskledger/project-a

Do not point two unrelated repositories at the same ``taskledger_dir``.
See :doc:`sync` for the recommended private-Git workflow when you want to use
the same Taskledger state across multiple PCs without committing ``.taskledger/``.

Integrity and recovery
----------------------

.. code-block:: bash

   taskledger doctor
   taskledger doctor locks
   taskledger lock show
   taskledger repair lock --reason "recover stale planning lock"
   taskledger implement resume --reason "Reacquire implementation lock for existing running run."
   taskledger task uncancel --task TASK_REF --reason "Restore the task to a safe durable stage."
   taskledger next-action
   taskledger repair index

Export and snapshots
--------------------

.. code-block:: bash

   taskledger init --project-name "Taskledger"
   taskledger export
   taskledger export --task task-0040
   taskledger export task-0040
   taskledger sync export --output ./taskledger-transfer.tar.gz
   taskledger import ./taskledger-transfer.tar.gz --dry-run
   taskledger sync import ./taskledger-transfer.tar.gz --dry-run
   taskledger import ./taskledger-task-planledger-main-task-0040-20260509T101500Z.tar.gz
   taskledger import ./taskledger-task-planledger-main-task-0040-20260509T101500Z.tar.gz --id-policy fail-on-conflict
   taskledger import ./taskledger-transfer.tar.gz --replace

For private multi-PC full-state sync with external storage, use:

.. code-block:: bash

   taskledger sync git init --repo ../taskledger-state --project-path project-a
   taskledger sync git status
   taskledger sync git pull
   taskledger sync git push
   taskledger sync git push --message "Sync project-a taskledger state"
   taskledger snapshot ./artifacts

When no explicit output path is passed, default export archives are written
inside the resolved workspace root. Filenames are project-specific:

.. code-block:: text

   taskledger-export-{project_slug}-{ledger_ref}-{timestamp}.tar.gz
   taskledger-task-{project_slug}-{ledger_ref}-{task_id}-{timestamp}.tar.gz

``project_slug`` is derived from ``project_name`` in ``taskledger.toml``.
If unset, taskledger falls back to the workspace directory name.
UUID safety checks still use ``project_uuid`` only.

Export include flags are content-affecting:

- ``--no-include-bodies`` removes record body fields from the exported payload.
- ``--include-run-artifacts`` embeds artifact files under ``artifacts/`` in the archive.

Cross-machine imports preserve durable task/run records but quarantine imported
runtime locks by default. For an imported in-progress implementation, run:

.. code-block:: bash

   taskledger next-action
   taskledger implement resume --reason "Continue imported implementation."

Use ``--lock-policy keep`` only when you explicitly want diagnostic lock
restoration behavior.

Single-task transfer from a config-only checkout
------------------------------------------------

.. code-block:: bash

   # fresh checkout on another PC
   taskledger init
   taskledger task create "Fix import edge case" --slug fix-import-edge-case --description "..."
   # ... normal plan / implementation / validation lifecycle ...
   taskledger export task-0040

   # main dev repo
   taskledger import ./taskledger-task-planledger-main-task-0040-20260509T101500Z.tar.gz
   taskledger task list
   taskledger task show task-0040

Task-centered traceability
--------------------------

Taskledger owns temporal work truth: task history, plans, acceptance criteria,
implementation changes, validation checks, reviews, locks, and handoffs.
SpecWeave owns executable behavior truth under ``specs/behavior/features`` and
plain pytest enforcement. Archledger owns durable architecture and specification
truth. Cross-ledger integration is explicit and file or ID based.

Use ``taskledger trace TASK --format json`` to emit a read-only
``combi.trace.v1`` task bundle. The bundle links task IDs, accepted AC IDs,
task-local BDD IDs, imported evidence refs, source/test refs, implementation
changes, review refs, and Archledger provenance refs. Missing BDD mappings or
missing evidence are reported as trace gaps, not crashes or passing evidence.

Evidence import is explicit and auditable through commands such as
``taskledger validate import-bdd-report reports/behavior/<file>.xml --format junit-xml --command "pytest ..."``.
Taskledger records the report path, command, import timestamp, linked BDD IDs,
and linked AC IDs where available.
