@area-command_runner @feature-command-runner @generated
Feature: Command Runner

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-command-runner
  Rule: Command Runner

    @req-REQ-0012 @ac-AC-0117
    Example: Run Command Preserves Nonzero Python Exit Code
      Given the pytest test setup is prepared
      When run command preserves nonzero python exit code is executed
      Then result.returncode equals 3
      Then result.stdout equals ''
      Then result.stderr equals ''

    @req-REQ-0012 @ac-AC-0118
    Example: Run Command Preserves Zero Python Exit Code
      Given the pytest test setup is prepared
      When run command preserves zero python exit code is executed
      Then result.returncode equals 0
      Then result.stdout equals ''
      Then result.stderr equals ''
