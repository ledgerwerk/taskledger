@area-trace @feature-trace @generated
Feature: Trace

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-trace
  Rule: Trace

    @req-REQ-0068 @ac-AC-0771
    Example: Trace Cli Format Json Is Raw Json
      Given the pytest test setup is prepared
      When trace cli format json is raw json is executed
      Then result.exit_code equals 0
