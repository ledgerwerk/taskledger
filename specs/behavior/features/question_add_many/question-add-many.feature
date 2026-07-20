@area-question_add_many @feature-question-add-many @generated
Feature: Question Add Many

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-question-add-many
  Rule: Question Add Many

    @req-REQ-0042 @ac-AC-0482
    Example: Question Add Many Adds Required Questions To Active Task
      Given the pytest test setup is prepared
      When question add many adds required questions to active task is executed
      Then result.exit_code equals 0
      Then isinstance succeeds

    @req-REQ-0042 @ac-AC-0485
    Example: Question Add Many Supports Yaml File And Explicit Task
      Given the pytest test setup is prepared
      When question add many supports yaml file and explicit task is executed
      Then result.exit_code equals 0
      Then isinstance succeeds

    @req-REQ-0042 @ac-AC-0483
    Example: Question Add Many Rejects Blank Lines Without Partial Write
      Given the pytest test setup is prepared
      When question add many rejects blank lines without partial write is executed
      Then result.exit_code does not equal 0
      Then listed.exit_code equals 0

    @req-REQ-0042 @ac-AC-0484
    Example: Question Add Many Rejects Duplicates Without Partial Write
      Given the pytest test setup is prepared
      When question add many rejects duplicates without partial write is executed
      Then result.exit_code does not equal 0
      Then listed.exit_code equals 0
