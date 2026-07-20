@area-cli_command_contract @feature-cli-command-contract @generated
Feature: Cli Command Contract

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-cli-command-contract
  Rule: Cli Command Contract

    @req-REQ-0007 @ac-AC-0085
    Example: Removed Aliases Are Not Registered
      Given the pytest test setup is prepared
      When removed aliases are not registered is executed
      Then REMOVED_COMMANDS.isdisjoint succeeds

    @req-REQ-0007 @ac-AC-0083
    Example: Commands Do Not Register Local Json Options
      Given the pytest test setup is prepared
      When commands do not register local json options is executed
      Then offenders is falsy

    @req-REQ-0007 @ac-AC-0090
    Example: Workflow Commands Reject Positional Task Refs With Json Remediation
      Given the pytest test setup is prepared
      When workflow commands reject positional task refs with json remediation is executed
      Then result.exit_code equals 2

    @req-REQ-0007 @ac-AC-0088
    Example: Task Show Accepts Positional Task Ref And Task Option
      Given the pytest test setup is prepared
      When task show accepts positional task ref and task option is executed
      Then positional.exit_code equals 0
      Then explicit.exit_code equals 0

    @req-REQ-0007 @ac-AC-0087
    Example: Task Cancel Requires Explicit Target Even When Active Exists
      Given the pytest test setup is prepared
      When task cancel requires explicit target even when active exists is executed
      Then result.exit_code equals 2

    @req-REQ-0007 @ac-AC-0086
    Example: Task Cancel Accepts Positional Task Ref And Active Flag
      Given the pytest test setup is prepared
      When task cancel accepts positional task ref and active flag is executed
      Then show_a.exit_code equals 0
      Then cancel_active.exit_code equals 0

    @req-REQ-0007 @ac-AC-0084
    Example: Global Json Only For Task Show
      Given the pytest test setup is prepared
      When global json only for task show is executed
      Then local.exit_code does not equal 0
      Then global_result.exit_code equals 0

    @req-REQ-0007 @ac-AC-0089
    Example: Version Flag Displays Version
      Given the pytest test setup is prepared
      When version flag displays version is executed
      Then result.exit_code equals 0
      Then 'taskledger, version' is in result.stdout
