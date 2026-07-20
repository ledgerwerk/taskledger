@area-json_contracts @feature-json-contracts @generated
Feature: Json Contracts

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-json-contracts
  Rule: Json Contracts

    @req-REQ-0027 @ac-AC-0326
    Example: Json Success Envelope Uses Ok Command Result And Events
      Given the pytest test setup is prepared
      When json success envelope uses ok command result and events is executed
      Then result.exit_code equals 0

    @req-REQ-0027 @ac-AC-0325
    Example: Json Failure Envelope Includes Structured Error
      Given the pytest test setup is prepared
      When json failure envelope includes structured error is executed
      Then result.exit_code equals 3

    @req-REQ-0027 @ac-AC-0323
    Example: Context Missing Todo Focus Returns Json Error
      Given the pytest test setup is prepared
      When context missing todo focus returns json error is executed
      Then result.exit_code equals 1

    @req-REQ-0027 @ac-AC-0330
    Example: Status Json Reports Workspace And Storage Paths
      Given the pytest test setup is prepared
      When status json reports workspace and storage paths is executed
      Then result.exit_code equals 0

    @req-REQ-0027 @ac-AC-0331
    Example: Worker Pipeline Json Contracts Cover Guided Surfaces
      Given the pytest test setup is prepared
      When worker pipeline json contracts cover guided surfaces is executed
      Then show_result.exit_code equals 0
      Then next_result.exit_code equals 0
      Then context_result.exit_code equals 0
      Then handoff_result.exit_code equals 0
      Then action_result.exit_code equals 0

    @req-REQ-0027 @ac-AC-0329
    Example: Python M Taskledger Uses Canonical Json Command Names
      Given the pytest test setup is prepared
      When python m taskledger uses canonical json command names is executed
      Then result.returncode equals 0

    @req-REQ-0027 @ac-AC-0332
    Example: Workflow Positional Task Ref Returns Json Usage Error Envelope
      Given the pytest test setup is prepared
      When workflow positional task ref returns json usage error envelope is executed
      Then result.exit_code equals 2

    @req-REQ-0027 @ac-AC-0328
    Example: Python M Taskledger Json Parse Error Envelope
      Given the pytest test setup is prepared
      When python m taskledger json parse error envelope is executed
      Then result.returncode equals 2

    @req-REQ-0027 @ac-AC-0327
    Example: Plan Lint Usage Error Includes Waiver Hint
      Given the pytest test setup is prepared
      When plan lint usage error includes waiver hint is executed
      Then result.returncode equals 2
      Then 'Lint has no waiver flags' is in remediation
      Then 'allow-lint-errors' is in remediation

    @req-REQ-0027 @ac-AC-0324
    Example: Doctor Usage Error For Errors Argument Has Specific Hint
      Given the pytest test setup is prepared
      When doctor usage error for errors argument has specific hint is executed
      Then result.returncode equals 2
      Then 'doctor locks' is in remediation
      Then 'doctor schema' is in remediation
