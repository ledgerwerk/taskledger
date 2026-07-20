@area-cli_import_resilience @feature-cli-import-resilience @generated
Feature: Cli Import Resilience

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-cli-import-resilience
  Rule: Cli Import Resilience

    @req-REQ-0008 @ac-AC-0092
    Example: Optional Release Import Failure Keeps Core Commands Available
      Given the pytest test setup is prepared
      When optional release import failure keeps core commands available is executed
      Then failed_release.exit_code equals 1
      Then isinstance succeeds
      Then isinstance succeeds

    @req-REQ-0008 @ac-AC-0091
    Example: Launcher Reports Cli Import Failure
      Given the pytest test setup is prepared
      When launcher reports cli import failure is executed
      Then excinfo.value.code equals 1
      Then 'taskledger failed to import its CLI.' is in captured.err
      Then 'RuntimeError: broken import for taskledger.cli' is in captured.err
      Then 'python -m py_compile taskledger/cli.py taskledger/cli_release.py' is in captured.err

    @req-REQ-0008 @ac-AC-0093
    Example: Python M Taskledger Help Works
      Given the pytest test setup is prepared
      When python m taskledger help works is executed
      Then result.returncode equals 0
      Then 'Manage staged taskledger coding work.' is in result.stdout
