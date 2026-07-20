@area-implementation_change_scan @feature-implementation-change-scan @generated
Feature: Implementation Change Scan

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-implementation-change-scan
  Rule: Implementation Change Scan

    @req-REQ-0025 @ac-AC-0313
    Example: Scan Changes From Git Records Branch Status And Diff Stat
      Given the pytest test setup is prepared
      When scan changes from git records branch status and diff stat is executed
      Then result.exit_code equals 0

    @req-REQ-0025 @ac-AC-0314
    Example: Scan Changes From Git Rejects Non Git Workspace
      Given the pytest test setup is prepared
      When scan changes from git rejects non git workspace is executed
      Then result.exit_code does not equal 0

    @req-REQ-0025 @ac-AC-0312
    Example: Manual Implement Change Still Works Via Canonical Command
      Given the pytest test setup is prepared
      When manual implement change still works via canonical command is executed
      Then result.exit_code equals 0

    @req-REQ-0025 @ac-AC-0311
    Example: Implement Finish Warns When Git Scan Missing
      Given the pytest test setup is prepared
      When implement finish warns when git scan missing is executed
      Then manual.exit_code equals 0
      Then finish.exit_code equals 0
      Then isinstance succeeds
      Then any succeeds

    @req-REQ-0025 @ac-AC-0310
    Example: Implement Finish Warning Clears After Git Scan
      Given the pytest test setup is prepared
      When implement finish warning clears after git scan is executed
      Then finish.exit_code equals 0
      Then isinstance succeeds
