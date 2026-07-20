@area-locks_audit @feature-locks-audit @generated
Feature: Locks Audit

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-locks-audit
  Rule: Locks Audit

    @req-REQ-0031 @ac-AC-0358
    Example: Break Lock Writes Audit File And Repair Event
      Given the pytest test setup is prepared
      When break lock writes audit file and repair event is executed
      Then result.exit_code equals 0
      Then any succeeds

    @req-REQ-0031 @ac-AC-0359
    Example: Stale Lock Blocks New Run Until Explicit Break
      Given the pytest test setup is prepared
      When stale lock blocks new run until explicit break is executed
      Then blocked.exit_code does not equal 0
