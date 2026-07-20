@area-plan_approval_contract @feature-plan-approval-contract @generated
Feature: Plan Approval Contract

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-plan-approval-contract
  Rule: Plan Approval Contract

    @req-REQ-0036 @ac-AC-0403
    Example: Plan Approval Records Actor Metadata And Criteria Ids
      Given the pytest test setup is prepared
      When plan approval records actor metadata and criteria ids is executed
      Then approve.exit_code equals 0
      Then isinstance succeeds

    @req-REQ-0036 @ac-AC-0406
    Example: Plan Approval Warns When Source Is Missing
      Given the pytest test setup is prepared
      When plan approval warns when source is missing is executed
      Then approve.exit_code equals 0
      Then isinstance succeeds
      Then any succeeds

    @req-REQ-0036 @ac-AC-0409
    Example: Task Report Warns When Approved Plan Hash Mismatches
      Given the pytest test setup is prepared
      When task report warns when approved plan hash mismatches is executed
      Then approve.exit_code equals 0
      Then report.exit_code equals 0
      Then 'approved plan content hash does not match' is in report.stdout

    @req-REQ-0036 @ac-AC-0402
    Example: Plan Approval Blocks Running Planning Run Without Lock
      Given the pytest test setup is prepared
      When plan approval blocks running planning run without lock is executed
      Then task.latest_planning_run is not None
      Then approve.exit_code does not equal 0

    @req-REQ-0036 @ac-AC-0404
    Example: Plan Approval Rejects Agent Approval Without Escape Hatch
      Given the pytest test setup is prepared
      When plan approval rejects agent approval without escape hatch is executed
      Then approve.exit_code does not equal 0

    @req-REQ-0036 @ac-AC-0405
    Example: Plan Approval Requires Criteria By Default
      Given the pytest test setup is prepared
      When plan approval requires criteria by default is executed
      Then approve.exit_code does not equal 0

    @req-REQ-0036 @ac-AC-0401
    Example: Plan Accept Human Error Includes Lint Issue Details
      Given the pytest test setup is prepared
      When plan accept human error includes lint issue details is executed
      Then result.exit_code does not equal 0
      Then 'Plan lint details:' is in combined
      Then 'missing_todos' is in combined
      Then 'plan.todos' is in combined

    @req-REQ-0036 @ac-AC-0407
    Example: Plan Approve Default Actor Is Agent
      Given the pytest test setup is prepared
      When plan approve default actor is agent is executed
      Then approve.exit_code does not equal 0

    @req-REQ-0036 @ac-AC-0408
    Example: Plan Yaml Single Key Shorthand Criteria
      Given the pytest test setup is prepared
      When plan yaml single key shorthand criteria is executed
      Then show.exit_code equals 0
