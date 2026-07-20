@area-task_events @feature-task-events @generated
Feature: Task Events

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-task-events
  Rule: Task Events

    @req-REQ-0059 @ac-AC-0633
    Example: Task Events Human Output
      Given the pytest test setup is prepared
      When task events human output is executed
      Then result.exit_code equals 0
      Then 'EVENTS' is in result.output
      Then 'task.created' is in result.output

    @req-REQ-0059 @ac-AC-0634
    Example: Task Events Json Output
      Given the pytest test setup is prepared
      When task events json output is executed
      Then isinstance succeeds
      Then 'event' is in event
      Then 'ts' is in event
      Then 'actor' is in event

    @req-REQ-0059 @ac-AC-0631
    Example: Task Events All
      Given the pytest test setup is prepared
      When task events all is executed
      Then result.exit_code equals 0
      Then 'task.created' is in result.output

    @req-REQ-0059 @ac-AC-0635
    Example: Task Events Limit
      Given the pytest test setup is prepared
      When task events limit is executed
      Then result.exit_code equals 0

    @req-REQ-0059 @ac-AC-0632
    Example: Task Events Empty
      Given the pytest test setup is prepared
      When task events empty is executed
      Then result.exit_code does not equal 0

    @req-REQ-0059 @ac-AC-0636
    Example: Task Events With Explicit Task Ref
      Given the pytest test setup is prepared
      When task events with explicit task ref is executed
      Then result.exit_code equals 0
      Then 'EVENTS' is in result.output
