---
schema_version: 4
id: block-0032
type: black_box
title: Services Layer
status: proposed
section: building_block_view
level: 1
parent: block-0029
order: 30
interfaces: []
location: []
fulfilled_requirements: []
risks: []
tags: []
body_format: markdown
kind: block
version: 2
---

Orchestrates lifecycle flows by coordinating Domain policies and records with Storage. Focused services own planning (`planning_flow.py`, `plan_input.py`, `plan_review.py`, `plan_lint.py`, `plan_materialization.py`), implementation (`implementation_flow.py`, `workspace_snapshot.py`), validation (`validation_flow.py`), handoffs (`handoff.py`, `handoff_lifecycle.py`, `worker_context.py`), doctor checks (`doctor.py`, `doctor_checks/`), navigation (`navigation.py`, `next_action_model.py`, `next_action_payload.py`, `ready_work.py`), worker pipelines (`worker_pipeline.py`, `workflow_guidance.py`), archival (`task_archive.py`, `task_export.py`, `task_reports.py`), code-review evidence (`code_review.py`), event logging (`task_events.py`, `agent_transcripts.py`, `agent_logging.py`, `change_tracking.py`, `check_tracking.py`, `event_logging.py`), exports and dashboard assembly (`dashboard.py`, `tree.py`, `monitor.py`). `tasks.py` remains the compatibility-oriented lifecycle facade while ownership is progressively extracted into focused modules.
