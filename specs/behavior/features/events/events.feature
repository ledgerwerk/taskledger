@area-events @feature-events @generated
Feature: Events

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-events
  Rule: Events

    @req-REQ-0020 @ac-AC-0283
    Example: Load Events Sorts By Timestamp And Event Id
      Given the event log contains events written out of chronological order
      When the events are loaded
      Then they are returned sorted by timestamp and event id

    @req-REQ-0020 @ac-AC-0282
    Example: Load Events Rejects Duplicate Event Ids
      Given the event log contains duplicate event ids
      When the events are loaded
      Then loading fails with a duplicate event id error

    @req-REQ-0020 @ac-AC-0284
    Example: Load Recent Events Returns Chronological Task Tail
      Given the event log contains events for multiple tasks
      When recent events are loaded for one task with a limit
      Then the returned events are that task's chronological tail
