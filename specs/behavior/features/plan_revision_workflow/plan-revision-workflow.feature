@area-plan_revision_workflow @feature-plan-revision-workflow @generated
Feature: Plan Revision Workflow

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-plan-revision-workflow
  Rule: Plan Revision Workflow

    @req-REQ-0039 @ac-AC-0452
    Example: Plan Upsert Rejects Taskledger Storage File
      Given the pytest test setup is prepared
      When plan upsert rejects taskledger storage file is executed
      Then result.exit_code equals 2

    @req-REQ-0039 @ac-AC-0450
    Example: Plan Propose And Regenerate Reject Taskledger Storage File
      Given the pytest test setup is prepared
      When plan propose and regenerate reject taskledger storage file is executed
      Then propose.exit_code equals 2
      Then regenerate.exit_code equals 2

    @req-REQ-0039 @ac-AC-0449
    Example: Plan Export Round Trips After Revision
      Given the pytest test setup is prepared
      When plan export round trips after revision is executed
      Then export_result.exit_code equals 0
      Then upsert_result.exit_code equals 0

    @req-REQ-0039 @ac-AC-0447
    Example: Plan Amend Drops Criteria And Todos And Records Event
      Given the pytest test setup is prepared
      When plan amend drops criteria and todos and records event is executed
      Then amend.exit_code equals 0
      Then event_files is truthy
      Then any succeeds

    @req-REQ-0039 @ac-AC-0448
    Example: Plan Amend Unknown Criterion Fails Without Mutation
      Given the pytest test setup is prepared
      When plan amend unknown criterion fails without mutation is executed
      Then amend.exit_code equals 2
      Then task.latest_plan_version equals 1

    @req-REQ-0039 @ac-AC-0451
    Example: Plan Upsert Auto Revise From Plan Review
      Given the pytest test setup is prepared
      When plan upsert auto revise from plan review is executed
      Then upsert.exit_code equals 0

    @req-REQ-0039 @ac-AC-0453
    Example: Plan Upsert Without Active Planning Suggests Revision Workflow
      Given the pytest test setup is prepared
      When plan upsert without active planning suggests revision workflow is executed
      Then upsert.exit_code equals 3

    @req-REQ-0039 @ac-AC-0446
    Example: Next Action Plan Review Mentions Revision Commands
      Given the pytest test setup is prepared
      When next action plan review mentions revision commands is executed
      Then next_action.exit_code equals 0
      Then 'Command: taskledger plan review --version 1' is in next_action.stdout
      Then 'Accept plan after explicit user approval: taskledger plan accept --version 1 --note "User approved in harness."' is in next_action.stdout
      Then 'Revise proposed plan: taskledger plan revise' is in next_action.stdout
      Then 'Export editable plan: taskledger plan export --version 1 --file ./plan.md' is in next_action.stdout
