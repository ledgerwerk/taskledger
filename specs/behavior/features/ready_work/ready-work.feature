@area-ready_work @feature-ready-work
Feature: Ready work

  Ready-work discovery exposes actionable tasks with explicit next commands.

  @rule-ready-work-selection
  Rule: Ready work selection

    @req-REQ-0045 @ac-AC-0506
    Example: Ready work includes only actionable task statuses
      Given a ledger contains tasks in ready and non-ready lifecycle stages
      When ready work is listed
      Then only tasks in supported ready stages are returned

    @req-REQ-0045 @ac-AC-0507
    Example: Ready work includes its next action and command
      Given a task is ready for lifecycle progress
      When ready work is listed
      Then the task includes its next action
      And the task includes an explicit command to perform that action

    @req-REQ-0045 @ac-AC-0508
    Example: Ready work respects the requested result limit
      Given more actionable tasks exist than the requested maximum
      When ready work is listed with that maximum
      Then no more than the requested number of tasks is returned
