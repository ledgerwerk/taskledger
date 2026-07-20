@area-taskledger_cli_api_parity @feature-taskledger-cli-api-parity @generated
Feature: Taskledger Cli Api Parity

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-taskledger-cli-api-parity
  Rule: Taskledger Cli Api Parity

    @req-REQ-0063 @ac-AC-0678
    Example: Cli Command Tree Matches Task First Contract
      Given the pytest test setup is prepared
      When cli command tree matches task first contract is executed
      Then result.exit_code equals 0
      Then name is in result.stdout

    @req-REQ-0063 @ac-AC-0680
    Example: Legacy Cli Groups Are Removed
      Given the pytest test setup is prepared
      When legacy cli groups are removed is executed
      Then result.exit_code does not equal 0

    @req-REQ-0063 @ac-AC-0681
    Example: Task First Subcommands Are Registered
      Given the pytest test setup is prepared
      When task first subcommands are registered is executed
      Then result.exit_code equals 0
      Then subcommand is in result.stdout

    @req-REQ-0063 @ac-AC-0679
    Example: File And Link Help Describe Distinct Surfaces
      Given the pytest test setup is prepared
      When file and link help describe distinct surfaces is executed
      Then file_help.exit_code equals 0
      Then link_help.exit_code equals 0
      Then 'Manage task file links.' is in file_help.stdout
      Then 'Manage external and typed task links.' is in link_help.stdout
