@area-taskledger_branch_scoped_ledgers @feature-taskledger-branch-scoped-ledgers @generated
Feature: Taskledger Branch Scoped Ledgers

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-taskledger-branch-scoped-ledgers
  Rule: Taskledger Branch Scoped Ledgers

    @req-REQ-0062 @ac-AC-0677
    Example: Branch Ledgers Derive Task IDs Per Ledger
      Given a project uses main and feature ledger references
      When tasks are created on each ledger
      Then each ledger derives its task IDs independently

    @req-REQ-0062 @ac-AC-0675
    Example: Ledger Status Reports Derived Next Task ID
      Given the current ledger contains one task
      When ledger status is inspected
      Then the next task ID is derived from the ledger state

    @req-REQ-0062 @ac-AC-0674
    Example: Ledger Fork Switch And Doctor Use Sibling State
      Given a project has a sibling ledger store
      When a ledger is forked, switched, and inspected
      Then the selected ledger state remains healthy

    @req-REQ-0062 @ac-AC-0673
    Example: Release JSON Includes Ledger Reference
      Given a release is listed for the current ledger
      When release output is requested as JSON
      Then the response includes the active ledger reference

    @req-REQ-0062 @ac-AC-0676
    Example: Global References Remain Branch Agnostic
      Given a task is created on a branch-scoped ledger
      When its global reference is inspected
      Then the reference does not encode the branch ledger
