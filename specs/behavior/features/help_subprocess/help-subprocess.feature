@area-help_subprocess @feature-help-subprocess @generated
Feature: Help Subprocess

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-help-subprocess
  Rule: Help Subprocess

    @req-REQ-0024 @ac-AC-0307
    Example: Help Subprocess Exits Quickly
      Given the pytest test setup is prepared
      When help subprocess exits quickly is executed
      Then result.returncode equals 0
      Then 'Usage:' is in result.stdout

    @req-REQ-0024 @ac-AC-0308
    Example: Root Help Shows Completion Options
      Given the pytest test setup is prepared
      When root help shows completion options is executed
      Then result.returncode equals 0
      Then completion.returncode equals 0

    @req-REQ-0024 @ac-AC-0309
    Example: Show Completion Exits Quickly And Does Not Create Agent Logs
      Given the pytest test setup is prepared
      When show completion exits quickly and does not create agent logs is executed
      Then result.returncode equals 0
      Then 'taskledger' is in result.stdout
