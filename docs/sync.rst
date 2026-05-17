Sync taskledger state across PCs
================================

Taskledger already supports keeping durable task state outside the source
repository. The recommended workflow is to commit only ``taskledger.toml`` in
the source repo, point ``taskledger_dir`` at an external sibling directory, and
sync that external directory with a private Git repository.

External state directory
------------------------

Use ``taskledger init --taskledger-dir`` or edit ``taskledger.toml`` so the
workspace keeps only config while the durable state lives elsewhere:

.. code-block:: toml

   config_version = 2
   taskledger_dir = "../taskledger-state/project-a"
   project_uuid = "keep-existing-uuid"
   project_name = "project-a"
   ledger_ref = "main"

Relative paths are preferred because they keep the same sibling layout working
across multiple PCs.

Private state Git repo
----------------------

Recommended layout:

.. code-block:: text

   /home/me/src/project-a/                  # source repo
   /home/me/src/taskledger-state/           # private state repo
   /home/me/src/taskledger-state/project-a/
     storage.yaml
     ledgers/
       main/
         tasks/
         events/
         releases/
         indexes/

The source repository keeps ``taskledger.toml`` and ignores ``.taskledger/``.
The private state repository stores the external ``taskledger_dir`` contents.

Second PC bootstrap
-------------------

Clone both repositories as siblings:

.. code-block:: bash

   cd ~/src
   git clone <source-repo-url> project-a
   git clone <private-state-repo-url> taskledger-state

   cd project-a
   taskledger status --full
   taskledger doctor
   taskledger task list

Daily sync protocol
-------------------

Taskledger provides a Git sync command group that automates this workflow:

.. code-block:: bash

   taskledger sync git init --repo ../taskledger-state --project-path project-a
   taskledger sync git status
   taskledger sync git pull
   taskledger sync git push --message "Sync project-a taskledger state"
   taskledger sync git sync --message "Sync project-a taskledger state"

Before starting work on a PC:

.. code-block:: bash

   cd ~/src/taskledger-state
   git pull --rebase

   cd ~/src/project-a
   taskledger doctor
   taskledger next-action

After finishing a task cycle or stopping at a safe boundary:

.. code-block:: bash

   cd ~/src/project-a
   taskledger doctor
   taskledger task list

   cd ~/src/taskledger-state
   git status --short
   git add project-a
   git commit -m "Sync project-a taskledger state"
   git pull --rebase
   git push

Active lock rule
----------------

Do not use the same Taskledger state concurrently from multiple PCs. Prefer to
switch machines only when:

* the task is ``done``;
* the task is ``approved`` and no implementation lock exists;
* implementation is finished and validation has not started; or
* no active lock is present.

Keep one active writer per project. Concurrent writes can produce Git conflicts
or semantic conflicts across canonical task records.

When to use export/import instead
---------------------------------

Archive commands are still the transfer primitive and remain available at both
the root and under ``sync``:

.. code-block:: bash

   taskledger export task-0040
   taskledger import ./taskledger-task-project-a-main-task-0040-...tar.gz
   taskledger sync export --output ./taskledger-transfer.tar.gz
   taskledger sync import ./taskledger-transfer.tar.gz --dry-run

If work must move mid-run, prefer task-scoped transfer archives instead of
syncing the full live state directory:

.. code-block:: bash

   taskledger export task-0040
   # copy archive to the other PC
   taskledger import ./taskledger-task-project-a-main-task-0040-...tar.gz
   taskledger next-action
   taskledger implement resume --reason "Continue imported implementation."

Imported runtime locks are quarantined by default, which makes archive transfer
safer than syncing an active lock between machines.

Syncthing/rclone caveats
------------------------

Syncthing and ``rclone bisync`` can transport the external state directory, but
Git is the safer default for Taskledger's text-first state because it preserves
history and exposes conflicts directly.

If Syncthing is used:

* avoid concurrent writers;
* stop one agent before starting another PC;
* run ``taskledger doctor`` after sync; and
* resolve conflict files before continuing.

Treat ``rclone bisync`` as an advanced workflow. Keep Git push/pull under user
control and do not automate network sync from Taskledger itself.
