@area-task_archive @feature-task-archive @generated
Feature: Task Archive

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-task-archive
  Rule: Task Archive

    @req-REQ-0058 @ac-AC-0626
    Example: Archive Hides Task From Default List
      Given the pytest test setup is prepared
      When archive hides task from default list is executed
      Then result.exit_code equals 0
      Then 'legacy-task' is not in result.stdout
      Then archived.exit_code equals 0
      Then 'legacy-task' is in archived.stdout
      Then 'archived' is in archived.stdout

    @req-REQ-0058 @ac-AC-0627
    Example: Archived Slug Can Be Reused And Archived Slug Can Be Ambiguous
      Given the pytest test setup is prepared
      When archived slug can be reused and archived slug can be ambiguous is executed
      Then archived.exit_code equals 0
      Then first is in archived.stdout
      Then second is in archived.stdout
      Then ambiguous.exit_code does not equal 0

    @req-REQ-0058 @ac-AC-0630
    Example: Unarchive Rejects Visible Slug Conflict And Accepts New Slug
      Given the pytest test setup is prepared
      When unarchive rejects visible slug conflict and accepts new slug is executed
      Then conflict.exit_code does not equal 0
      Then restored.exit_code equals 0

    @req-REQ-0058 @ac-AC-0629
    Example: Archiving All Tasks Does Not Reset Next Task Number
      Given the pytest test setup is prepared
      When archiving all tasks does not reset next task number is executed
      Then second equals 'task-0002'

    @req-REQ-0058 @ac-AC-0628
    Example: Archived Task Mutation Is Rejected And Exact Id Still Reads
      Given the pytest test setup is prepared
      When archived task mutation is rejected and exact id still reads is executed
      Then activate.exit_code does not equal 0
      Then 'Cannot activate archived task' is in activate.output
      Then show.exit_code equals 0
      Then 'immutable-archived' is in show.stdout
