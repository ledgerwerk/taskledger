API reference
=============

`taskledger` exposes a task-first public API through ``taskledger.api``.

Supported modules
-----------------

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
- ``taskledger.api.bdd``

Import boundary
---------------

Consumers should not import from ``taskledger.storage``, ``taskledger.services``,
``taskledger.domain``, or ``taskledger.search`` directly.

Project API
-----------

- ``init_project``
- ``project_status``
- ``project_status_summary``
- ``project_doctor``
- ``project_export``
- ``project_import``
- ``project_export_archive``
- ``project_import_archive``
- ``project_snapshot``
- ``project_tree``

Task API
--------

- ``create_task``
- ``record_completed_task``
- ``show_active_task``
- ``activate_task``
- ``deactivate_task``
- ``clear_active_task``
- ``resolve_active_task``
- ``list_task_summaries``
- ``show_task``
- ``edit_task``
- ``cancel_task``
- ``uncancel_task``
- ``close_task``
- ``archive_task``
- ``unarchive_task``
- ``create_follow_up_task``
- ``list_archived_task_summaries``
- ``add_requirement``
- ``remove_requirement``
- ``waive_requirement``
- ``add_file_link``
- ``remove_file_link``
- ``list_file_links``
- ``add_todo``
- ``set_todo_done``
- ``show_todo``
- ``todo_status``
- ``next_todo``
- ``task_dossier``
- ``render_task_report``
- ``TaskReportOptions``
- ``export_task_markdown``
- ``TaskMarkdownExportOptions``
- ``next_action``
- ``can_perform``
- ``reindex``
- ``repair_task_record``
- ``repair_orphaned_planning_run``
- ``repair_planning_command_changes``

Plan API
--------

- ``start_planning``
- ``propose_plan``
- ``plan_template``
- ``upsert_plan``
- ``PlanReviewOptions``
- ``build_plan_review_payload``
- ``render_plan_review``
- ``export_plan``
- ``amend_plan``
- ``list_plan_versions``
- ``show_plan``
- ``diff_plan``
- ``lint_plan``
- ``plan_guidance``
- ``approve_plan``
- ``reject_plan``
- ``revise_plan``
- ``regenerate_plan_from_answers``
- ``materialize_plan_todos``
- ``run_planning_command``

Planning guidance example:

.. code-block:: python

   from pathlib import Path
   from taskledger.api.plans import plan_guidance

   payload = plan_guidance(Path.cwd(), "task-0001")

Question API
------------

- ``add_question``
- ``add_questions``
- ``answer_question``
- ``answer_questions``
- ``list_questions``
- ``list_open_questions``
- ``dismiss_question``
- ``question_status``

Run API
-------

- ``start_implementation``
- ``restart_implementation``
- ``resume_implementation``
- ``log_implementation``
- ``add_implementation_deviation``
- ``add_implementation_artifact``
- ``add_change``
- ``scan_changes``
- ``run_implementation_command``
- ``finish_implementation``
- ``show_task_run``
- ``start_validation``
- ``add_validation_check``
- ``validation_status``
- ``waive_criterion``
- ``finish_validation``
- ``list_runs``
- ``list_changes``

Review API
----------

- ``record_code_review``
- ``list_code_review_records``
- ``show_code_review``

Other APIs
----------

Introduction API
~~~~~~~~~~~~~~~~

- ``create_introduction``
- ``list_introductions``
- ``resolve_introduction``
- ``link_introduction``

Lock API
~~~~~~~~

- ``show_lock``
- ``break_lock``
- ``list_locks``
- ``load_active_locks``

Handoff API
~~~~~~~~~~~

- ``render_handoff``
- ``create_handoff``
- ``list_all_handoffs``
- ``show_handoff``
- ``claim_handoff_api``
- ``close_handoff_api``
- ``cancel_handoff_api``

Release API
~~~~~~~~~~~

- ``build_changelog_context``
- ``list_release_records``
- ``show_release``
- ``tag_release``

Storage API
~~~~~~~~~~~

- ``storage_where``
- ``storage_move``
- ``sync_preflight``
- ``sync_status``
- ``sync_commit``

Search API
~~~~~~~~~~

- ``search_workspace``
- ``grep_workspace``
- ``symbols_workspace``
- ``dependencies_for_module``

BDD API
~~~~~~~

Task-local behavior mapping APIs. These are task-local BDD/example overlay
records. Taskledger is not the canonical spec owner — canonical behavior specs
live under ``specs/behavior/features/`` (SpecWeave-owned).

- ``bdd_init``
- ``bdd_status``
- ``bdd_rule_add``
- ``bdd_rule_list``
- ``bdd_rule_show``
- ``bdd_example_add``
- ``bdd_example_list``
- ``bdd_example_show``
- ``bdd_example_link_ac``
- ``bdd_example_link_archledger``
- ``bdd_example_link_automation``
- ``bdd_gherkin_export``
- ``bdd_export_json``
- ``bdd_archledger_candidate``
- ``import_bdd_report``

Sync API
~~~~~~~~

- ``sync_git_init``
- ``sync_git_paths``
- ``sync_git_status``
- ``sync_git_import_local``
- ``sync_git_commit``
- ``sync_git_export_local``
- ``sync_git_pull``
- ``sync_git_push``
- ``sync_git_sync``
- ``sync_git_hooks_install``
- ``sync_git_hooks_status``
- ``sync_git_hooks_uninstall``
