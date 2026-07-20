@area-usage_cli @feature-usage-cli @generated
Feature: Usage Cli

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-usage-cli
  Rule: Usage Cli

    @req-REQ-0070 @ac-AC-0794
    Example: Usage Works In Empty Initialized Project
      Given the pytest test setup is prepared
      When usage works in empty initialized project is executed
      Then result.exit_code equals 0
      Then 'SESSION' is in result.stdout
      Then 'ACTIVE' is in result.stdout

    @req-REQ-0070 @ac-AC-0791
    Example: Usage Json Emits Usage Result
      Given the pytest test setup is prepared
      When usage json emits usage result is executed
      Then result.exit_code equals 0

    @req-REQ-0070 @ac-AC-0792
    Example: Usage Reports Active Implementation And Next Action
      Given the pytest test setup is prepared
      When usage reports active implementation and next action is executed
      Then isinstance succeeds
      Then isinstance succeeds
      Then result.exit_code equals 0
      Then task_id is in result.stdout
      Then 'next:' is in result.stdout

    @req-REQ-0070 @ac-AC-0790
    Example: Usage Does Not Mark Latest Run Review Ready When Review Exists
      Given the pytest test setup is prepared
      When usage does not mark latest run review ready when review exists is executed
      Then review_ready_task is in review_ready_ids
      Then reviewed_task is not in review_ready_ids

    @req-REQ-0070 @ac-AC-0793
    Example: Usage Reports Expired Lock In Inbox
      Given the pytest test setup is prepared
      When usage reports expired lock in inbox is executed
      Then lock is not None
      Then any succeeds
