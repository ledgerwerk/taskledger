@area-monitor @feature-monitor @generated
Feature: Monitor

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-monitor
  Rule: Monitor

    @req-REQ-0033 @ac-AC-0369
    Example: Monitor Snapshot Includes Active Task And Progress
      Given the pytest test setup is prepared
      When monitor snapshot includes active task and progress is executed
      Then isinstance succeeds
      Then isinstance succeeds

    @req-REQ-0033 @ac-AC-0368
    Example: Monitor Snapshot Groups In Progress And Ready Tasks
      Given the pytest test setup is prepared
      When monitor snapshot groups in progress and ready tasks is executed
      Then planning.id is in in_progress_ids
      Then implementing.id is in in_progress_ids
      Then validating.id is in in_progress_ids
      Then ready is in ready_ids
      Then failed is in ready_ids

    @req-REQ-0033 @ac-AC-0370
    Example: Monitor Snapshot Lists Newest Activity First
      Given the pytest test setup is prepared
      When monitor snapshot lists newest activity first is executed
      Then isinstance succeeds
      Then activity is truthy

    @req-REQ-0033 @ac-AC-0372
    Example: Render Monitor Text Truncates Without Throwing
      Given the pytest test setup is prepared
      When render monitor text truncates without throwing is executed
      Then 'CURRENT WORK' is in rendered
      Then '...' is in rendered

    @req-REQ-0033 @ac-AC-0367
    Example: Monitor Cli Once Exits Zero
      Given the pytest test setup is prepared
      When monitor cli once exits zero is executed
      Then result.exit_code equals 0
      Then 'CURRENT WORK' is in result.stdout

    @req-REQ-0033 @ac-AC-0366
    Example: Monitor Cli Json Once Emits Monitor Snapshot
      Given the pytest test setup is prepared
      When monitor cli json once emits monitor snapshot is executed
      Then result.exit_code equals 0

    @req-REQ-0033 @ac-AC-0363
    Example: Empty initialized projects produce a monitor snapshot
      Given an initialized project has no tasks
      When a monitor snapshot is requested
      Then the snapshot is produced without error

    @req-REQ-0033 @ac-AC-0371
    Example: Plan review tasks appear in ready work
      Given a task is awaiting plan review
      When a monitor snapshot is requested
      Then the task appears in the ready work group

    @req-REQ-0033 @ac-AC-0373
    Example: Task activity scope filters events to one task
      Given the ledger contains activity for multiple tasks
      When monitor activity is scoped to a selected task
      Then only activity for that task is returned

    @req-REQ-0033 @ac-AC-0365
    Example: Ledger activity scope shows activity across tasks
      Given the ledger contains activity for multiple tasks
      When monitor activity is scoped to the ledger
      Then activity across those tasks is returned

    @req-REQ-0033 @ac-AC-0364
    Example: Invalid monitor activity scope is rejected
      Given an unsupported activity scope
      When the monitor command is invoked
      Then the command fails with a usage error
