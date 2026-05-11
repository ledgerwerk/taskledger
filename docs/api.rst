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
- ``taskledger.api.introductions``
- ``taskledger.api.locks``
- ``taskledger.api.handoff``
- ``taskledger.api.releases``
- ``taskledger.api.search``

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

Search API
~~~~~~~~~~

- ``search_workspace``
- ``grep_workspace``
- ``symbols_workspace``
- ``dependencies_for_module``
