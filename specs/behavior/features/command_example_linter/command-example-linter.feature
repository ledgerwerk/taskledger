@area-command_example_linter @feature-command-example-linter @generated
Feature: Command Example Linter

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-command-example-linter
  Rule: Command Example Linter

    @req-REQ-0010 @ac-AC-0103
    Example: Docs Do Not Reference Removed Commands
      Given the pytest test setup is prepared
      When docs do not reference removed commands is executed
      Then needle is not in text

    @req-REQ-0010 @ac-AC-0102
    Example: Command Examples In Docs Use Valid Commands
      Given the pytest test setup is prepared
      When command examples in docs use valid commands is executed
      Then failures is falsy

    @req-REQ-0010 @ac-AC-0104
    Example: Readme Skill Path Matches Repository
      Given the pytest test setup is prepared
      When readme skill path matches repository is executed
      Then 'skills/taskledger/SKILL.md' is in readme
      Then 'taskledger/skills/taskledger/SKILL.md' is not in readme
