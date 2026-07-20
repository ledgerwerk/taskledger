@area-search @feature-search @generated
Feature: Search

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-search
  Rule: Search

    @req-REQ-0047 @ac-AC-0525
    Example: Search Grep And Symbols Basic
      Given the pytest test setup is prepared
      When search grep and symbols basic is executed
      Then any succeeds
      Then any succeeds
      Then any succeeds
      Then 'file1.py' is in seen
      Then 'file2.txt' is in seen
      Then all succeeds

    @req-REQ-0047 @ac-AC-0524
    Example: Module Dependencies And Errors
      Given the pytest test setup is prepared
      When module dependencies and errors is executed
      Then info.repo equals 'repo_b'
      Then info.module equals 'mymodule'
      Then '__manifest__.py' is in info.manifest_path

    @req-REQ-0047 @ac-AC-0523
    Example: Discovery Tokens And Discover Files
      Given the pytest test setup is prepared
      When discovery tokens and discover files is executed
      Then all succeeds
      Then any succeeds
