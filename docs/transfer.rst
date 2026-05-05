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

``project_slug`` comes from ``project_name`` (or workspace fallback). Import
safety still depends on UUID checks, not name matching.

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
