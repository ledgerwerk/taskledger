@area-models_v1_schema @feature-models-v1-schema @generated
Feature: Models V1 Schema

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-models-v1-schema
  Rule: Models V1 Schema

    @req-REQ-0032 @ac-AC-0361
    Example: Plan Record Round Trips Acceptance Criteria And Approval Metadata
      Given the pytest test setup is prepared
      When plan record round trips acceptance criteria and approval metadata is executed
      Then restored.approved_by is not None
      Then restored.approval_note equals 'Looks good.'
      Then restored.plan_id equals 'plan-v7'

    @req-REQ-0032 @ac-AC-0360
    Example: Handoff Record Round Trips Focused Context Metadata
      Given the pytest test setup is prepared
      When handoff record round trips focused context metadata is executed
      Then restored.context_for equals 'implementer'
      Then restored.scope equals 'todo'
      Then restored.todo_id equals 'todo-0003'
      Then restored.focus_run_id is None
      Then restored.context_hash equals 'sha256:abc123'
      Then legacy.context_for is None
      Then legacy.scope equals 'task'
      Then legacy.todo_id is None
      Then legacy.focus_run_id is None
      Then legacy.context_format equals 'markdown'
      Then legacy.context_hash is None
      Then legacy.generated_at is None

    @req-REQ-0032 @ac-AC-0362
    Example: Validation Check Requires Criterion Id Unless Not Run
      Given the pytest test setup is prepared
      When validation check requires criterion id unless not run is executed
      Then check.criterion_id is None
