@area-handoff_lifecycle @feature-handoff-lifecycle @generated
Feature: Handoff Lifecycle

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-handoff-lifecycle
  Rule: Handoff Lifecycle

    @req-REQ-0023 @ac-AC-0298
    Example: Handoff Claim
      Given the pytest test setup is prepared
      When handoff claim is executed
      Then claimed.status equals 'claimed'
      Then claimed.claimed_by is not None
      Then claimed.claimed_at is not None

    @req-REQ-0023 @ac-AC-0299
    Example: Handoff Close
      Given the pytest test setup is prepared
      When handoff close is executed
      Then closed.status equals 'closed'

    @req-REQ-0023 @ac-AC-0297
    Example: Handoff Cancel
      Given the pytest test setup is prepared
      When handoff cancel is executed
      Then cancelled.status equals 'cancelled'

    @req-REQ-0023 @ac-AC-0302
    Example: Handoff Lifecycle Sequence
      Given the pytest test setup is prepared
      When handoff lifecycle sequence is executed
      Then claimed.status equals 'claimed'
      Then closed.status equals 'closed'

    @req-REQ-0023 @ac-AC-0300
    Example: Handoff Create Stores Generated Context For Todo
      Given the pytest test setup is prepared
      When handoff create stores generated context for todo is executed
      Then '## Focused Todo' is in handoff.context_body
      Then 'todo-0001' is in handoff.context_body

    @req-REQ-0023 @ac-AC-0301
    Example: Handoff Lifecycle Preserves Context Metadata On Claim Close Cancel
      Given the pytest test setup is prepared
      When handoff lifecycle preserves context metadata on claim close cancel is executed
      Then claimed.context_for equals 'implementer'
      Then claimed.scope equals 'todo'
      Then claimed.todo_id equals 'todo-0001'
      Then claimed.focus_run_id is None
      Then closed.context_for equals 'implementer'
      Then closed.scope equals 'todo'
      Then closed.todo_id equals 'todo-0001'
      Then closed.context_body equals claimed.context_body
      Then cancelled.context_for equals 'implementer'
      Then cancelled.scope equals 'todo'
      Then cancelled.todo_id equals 'todo-0001'

    @req-REQ-0023 @ac-AC-0296
    Example: Creating a handoff persists an open handoff
      Given a task is ready to transfer context
      When a handoff is created
      Then the handoff is stored with open status and actor intent

    @req-REQ-0023 @ac-AC-0295
    Example: A claimed handoff cannot be claimed again
      Given a handoff has already been claimed
      When another claim is attempted
      Then the claim is rejected

    @req-REQ-0023 @ac-AC-0303
    Example: Invalid handoff actor intent is rejected
      Given a handoff uses an unsupported intended actor
      When the handoff is created or updated
      Then validation rejects the actor intent

    @req-REQ-0023 @ac-AC-0304
    Example: Handoff listing returns the task handoffs
      Given a task contains handoff records
      When its handoffs are listed
      Then the stored handoffs are returned

    @req-REQ-0023 @ac-AC-0305
    Example: Malformed handoff records are reported
      Given a task contains a malformed handoff record
      When its handoffs are listed
      Then loading fails with a record validation error

    @req-REQ-0023 @ac-AC-0306
    Example: Supported handoff modes are preserved
      Given handoffs are created for supported lifecycle modes
      When the handoffs are loaded
      Then each handoff retains its selected mode
