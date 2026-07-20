@area-question_filter_answers @feature-question-filter-answers @generated
Feature: Question Filter Answers

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-question-filter-answers
  Rule: Question Filter Answers

    @req-REQ-0043 @ac-AC-0489
    Example: Answers Markdown Format
      Given the pytest test setup is prepared
      When answers markdown format is executed
      Then result.exit_code equals 0
      Then 'q-0001' is in result.output
      Then 'Q: Q1?' is in result.output
      Then 'A: A1' is in result.output

    @req-REQ-0043 @ac-AC-0488
    Example: Answers Empty When None Answered
      Given the pytest test setup is prepared
      When answers empty when none answered is executed
      Then result.exit_code equals 0
      Then '(empty)' is in result.output

    @req-REQ-0043 @ac-AC-0486
    Example: Answer Empty Text Rejected
      Given the pytest test setup is prepared
      When answer empty text rejected is executed
      Then result.exit_code does not equal 0

    @req-REQ-0043 @ac-AC-0487
    Example: Answer Whitespace Only Rejected
      Given the pytest test setup is prepared
      When answer whitespace only rejected is executed
      Then result.exit_code does not equal 0

    @req-REQ-0043 @ac-AC-0491
    Example: Question listing filters by one or more statuses
      Given a task has answered, dismissed, and open questions
      When questions are listed with a status filter
      Then only questions matching the requested statuses are returned

    @req-REQ-0043 @ac-AC-0492
    Example: Question listing without a status filter returns all questions
      Given a task has questions in several statuses
      When questions are listed without a status filter
      Then every question is returned

    @req-REQ-0043 @ac-AC-0490
    Example: Answer output supports structured JSON
      Given a task has answered questions
      When answers are requested in JSON mode
      Then the response contains structured answer records
