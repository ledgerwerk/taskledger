@area-find_code_clones_script @feature-find-code-clones-script @generated
Feature: Find Code Clones Script

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-find-code-clones-script
  Rule: Find Code Clones Script

    @req-REQ-0022 @ac-AC-0294
    Example: Find Code Clones Script Json And Include Tests
      Given the pytest test setup is prepared
      When find code clones script json and include tests is executed
      Then 'scan: files=' is in human.stdout
