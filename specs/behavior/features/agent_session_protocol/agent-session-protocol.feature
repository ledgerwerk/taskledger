@area-agent_session_protocol @feature-agent-session-protocol @generated
Feature: Agent Session Protocol

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-agent-session-protocol
  Rule: Agent Session Protocol

    @req-REQ-0005 @ac-AC-0067
    Example: Lock Break No Lock Message Mentions Next Action
      Given the pytest test setup is prepared
      When lock break no lock message mentions next action is executed
      Then result.exit_code does not equal 0

    @req-REQ-0005 @ac-AC-0064
    Example: Allow Empty Criteria Requires Reason
      Given the pytest test setup is prepared
      When allow empty criteria requires reason is executed
      Then result.exit_code does not equal 0

    @req-REQ-0005 @ac-AC-0066
    Example: Allow Open Questions Requires Reason
      Given the pytest test setup is prepared
      When allow open questions requires reason is executed
      Then result.exit_code does not equal 0

    @req-REQ-0005 @ac-AC-0065
    Example: Allow Empty Criteria With Reason Succeeds
      Given the pytest test setup is prepared
      When allow empty criteria with reason succeeds is executed
      Then result.exit_code equals 0

    @req-REQ-0005 @ac-AC-0070
    Example: Plan Approval Blocks When No Todos
      Given the pytest test setup is prepared
      When plan approval blocks when no todos is executed
      Then result.exit_code does not equal 0
      Then 'todo' is in message

    @req-REQ-0005 @ac-AC-0071
    Example: Plan Approval Empty Todos With Reason Succeeds
      Given the pytest test setup is prepared
      When plan approval empty todos with reason succeeds is executed
      Then result.exit_code equals 0

    @req-REQ-0005 @ac-AC-0072
    Example: Plan Approval Empty Todos Without Reason Fails
      Given the pytest test setup is prepared
      When plan approval empty todos without reason fails is executed
      Then result.exit_code does not equal 0

    @req-REQ-0005 @ac-AC-0077
    Example: Plan Command Records Exit Code
      Given the pytest test setup is prepared
      When plan command records exit code is executed
      Then result.exit_code equals 0

    @req-REQ-0005 @ac-AC-0074
    Example: Plan Command Fails Without Active Planning
      Given the pytest test setup is prepared
      When plan command fails without active planning is executed
      Then result.exit_code does not equal 0

    @req-REQ-0005 @ac-AC-0076
    Example: Plan Command No Change Records
      Given the pytest test setup is prepared
      When plan command no change records is executed
      Then result.exit_code equals 0

    @req-REQ-0005 @ac-AC-0075
    Example: Plan Command Mirrors Inner Exit Code By Default
      Given the pytest test setup is prepared
      When plan command mirrors inner exit code by default is executed
      Then result.exit_code equals 6

    @req-REQ-0005 @ac-AC-0073
    Example: Plan Command Allow Failure Keeps Wrapper Exit Zero
      Given the pytest test setup is prepared
      When plan command allow failure keeps wrapper exit zero is executed
      Then raw.exit_code equals 0

    @req-REQ-0005 @ac-AC-0081
    Example: Validate Finish Passed Blocks Unchecked Mandatory Criteria
      Given the pytest test setup is prepared
      When validate finish passed blocks unchecked mandatory criteria is executed
      Then result.exit_code does not equal 0

    @req-REQ-0005 @ac-AC-0069
    Example: No Materialize Todos Without Reason Fails
      Given the pytest test setup is prepared
      When no materialize todos without reason fails is executed
      Then result.exit_code does not equal 0

    @req-REQ-0005 @ac-AC-0068
    Example: No Materialize Todos With Reason Succeeds
      Given the pytest test setup is prepared
      When no materialize todos with reason succeeds is executed
      Then result.exit_code equals 0

    @req-REQ-0005 @ac-AC-0078
    Example: Todo Added During Implementation Is Implementer Sourced
      Given the pytest test setup is prepared
      When todo added during implementation is implementer sourced is executed
      Then result.exit_code equals 0

    @req-REQ-0005 @ac-AC-0079
    Example: Todo Added During Planning Is Planner Sourced
      Given the pytest test setup is prepared
      When todo added during planning is planner sourced is executed
      Then result.exit_code equals 0

    @req-REQ-0005 @ac-AC-0080
    Example: Todo Added Without Active Stage Defaults To User
      Given the pytest test setup is prepared
      When todo added without active stage defaults to user is executed
      Then result.exit_code equals 0
