Transfer archives
=================

Transfer archives are portable taskledger state bundles for moving work between
machines and harnesses.

What transfer archives include
------------------------------

- Current-ledger durable records (tasks, plans, questions, runs, changes, todos, links, requirements, events, releases, handoffs).
- Project identity metadata:
  - ``project.uuid`` (safety identity)
  - ``project.name`` (human-facing label)
  - ``project.slug`` (filename/report slug)
  - ``project.ledger_ref`` (exported ledger)
- Optional run artifacts under ``artifacts/`` when ``--include-run-artifacts`` is set.

Filename policy
---------------

When no output path is passed to ``taskledger export``, taskledger writes:

.. code-block:: text

   taskledger-export-{project_slug}-{ledger_ref}-{timestamp}.tar.gz

For task-scoped exports:

.. code-block:: text

   taskledger-task-{project_slug}-{ledger_ref}-{task_id}-{timestamp}.tar.gz

``project_slug`` comes from ``project_name`` (or workspace fallback). Import
safety still depends on UUID checks, not name matching.

Single-task transfer from a config-only checkout
------------------------------------------------

.. code-block:: bash

   # fresh checkout on another PC
   taskledger init
   taskledger task create "Fix import edge case" --slug fix-import-edge-case --description "..."
   # ... normal plan/implement/validate workflow ...
   taskledger export task-0040

   # main dev repo
   taskledger import ./taskledger-task-planledger-main-task-0040-20260509T101500Z.tar.gz
   taskledger task list
   taskledger task show task-0040

Rules:

- Keep ``project_uuid`` committed in ``taskledger.toml`` (or legacy ``.taskledger.toml`` if the project still uses it).
- ``.taskledger/`` is local operational state and can be absent on another PC.
- Run ``taskledger init`` after cloning to create local state.
- ``taskledger export --task TASK_REF`` and ``taskledger export TASK_REF`` export task-scoped archives.
- ``taskledger sync export`` and ``taskledger sync import`` are aliases for the same archive transfer primitives.
- Task-scoped import is additive by default; if the task id already exists locally, import renumbers and reports an id map.
- ``--replace`` is for full-state replacement, not the normal single-task workflow.
- Import repairs ``ledger_next_task_number`` so future ``task create`` ids remain unique.
- Use :doc:`sync` when you want to keep an external ``taskledger_dir`` in a private Git repository and sync full project state between PCs.

Dry-run import
--------------

Use ``taskledger import --dry-run`` to validate archive or JSON payload imports
without mutating local state:

.. code-block:: bash

   taskledger import ./taskledger-transfer.tar.gz --dry-run
   taskledger import ./taskledger-export.json --dry-run

Lock policy and next action
---------------------------

Imported runtime locks are quarantined by default. After import, follow:

.. code-block:: bash

   taskledger next-action
   taskledger implement resume --reason "Continue imported implementation."
