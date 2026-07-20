@area-active_task @feature-active-task @generated
Feature: Active Task

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-active-task
  Rule: Active Task

    @req-REQ-0001 @ac-AC-0008
    Example: Task Scoped Command Without Active Task Fails Json
      Given the pytest test setup is prepared
      When task scoped command without active task fails json is executed
      Then result.exit_code equals 5

    @req-REQ-0001 @ac-AC-0003
    Example: Single Task Without Active Task Fails For Task Scoped Defaults
      Given the pytest test setup is prepared
      When single task without active task fails for task scoped defaults is executed
      Then result.exit_code equals 5

    @req-REQ-0001 @ac-AC-0002
    Example: Single Task Without Active Task Can Still Be Used Explicitly
      Given the pytest test setup is prepared
      When single task without active task can still be used explicitly is executed
      Then result.exit_code equals 0

    @req-REQ-0001 @ac-AC-0005
    Example: Task Activate Sets Active Task
      Given the pytest test setup is prepared
      When task activate sets active task is executed
      Then result.exit_code equals 0

    @req-REQ-0001 @ac-AC-0007
    Example: Task Option Overrides Active Task
      Given the pytest test setup is prepared
      When task option overrides active task is executed
      Then activate.exit_code equals 0

    @req-REQ-0001 @ac-AC-0001
    Example: Export Import Preserves Active Task
      Given the pytest test setup is prepared
      When export import preserves active task is executed
      Then activate.exit_code equals 0
      Then export_result.exit_code equals 0

    @req-REQ-0001 @ac-AC-0006
    Example: Task List Marks Active Task Without Active Stage
      Given the pytest test setup is prepared
      When task list marks active task without active stage is executed
      Then result.exit_code equals 0
      Then '* task-0001' is in result.stdout
      Then 'active' is in result.stdout

    @req-REQ-0001 @ac-AC-0004
    Example: Status Human Output Shows Active Task Before Counts
      Given the pytest test setup is prepared
      When status human output shows active task before counts is executed
      Then result.exit_code equals 0
      Then active_idx is less than counts_idx
