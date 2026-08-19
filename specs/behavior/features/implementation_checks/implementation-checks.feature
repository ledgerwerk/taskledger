@area-implementation_checks @feature-implementation-checks @generated
Feature: Implementation Checks

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-implementation-checks
  Rule: Implementation Checks

    @req-REQ-0026 @ac-AC-0322
    Example: To Dict From Dict Round Trip
      Given the pytest test setup is prepared
      When to dict from dict round trip is executed
      Then restored equals record

    @req-REQ-0026 @ac-AC-0319
    Example: Defaults
      Given the pytest test setup is prepared
      When defaults is executed
      Then record.status equals 'unknown'
      Then record.category equals 'other'
      Then record.exit_code is None
      Then record.summary is None

    @req-REQ-0026 @ac-AC-0318
    Example: Creates Check Not Change
      Given the pytest test setup is prepared
      When creates check not change is executed
      Then r.exit_code equals 0

    @req-REQ-0026 @ac-AC-0316
    Example: Check Has Category
      Given the pytest test setup is prepared
      When check has category is executed
      Then r.exit_code equals 0

    @req-REQ-0026 @ac-AC-0317
    Example: Check Refs On Run
      Given the pytest test setup is prepared
      When check refs on run is executed
      Then r.exit_code equals 0
      Then check_id is in run.check_refs

    @req-REQ-0026 @ac-AC-0321
    Example: Human Output Shows Check
      Given the pytest test setup is prepared
      When managed command execution is exercised
      Then r.exit_code equals 0
      Then 'recorded check check-' is in r.output
      Then child stdout and stderr are visible in human output
      Then the managed result reports the actual child cwd
      Then the child receives the exact argv after --
      Then planning and implementation wrappers use the same execution contract
