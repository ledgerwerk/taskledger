@area-plan_review @feature-plan-review @generated
Feature: Plan Review

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-plan-review
  Rule: Plan Review

    @req-REQ-0038 @ac-AC-0439
    Example: Plan Review Markdown Includes Proposed Plan Body
      Given the pytest test setup is prepared
      When plan review markdown includes proposed plan body is executed
      Then isinstance succeeds
      Then content.startswith succeeds
      Then '## Proposed Plan' is in content
      Then 'Render a concise approval-focused review artifact.' is in content

    @req-REQ-0038 @ac-AC-0436
    Example: Plan Review Includes Machine Commitments
      Given the pytest test setup is prepared
      When plan review includes machine commitments is executed
      Then '## Machine-Readable Commitments' is in content
      Then '### Acceptance Criteria' is in content
      Then 'ac-0001: Review command renders markdown.' is in content
      Then '### Planned Todos' is in content
      Then 'todo-0001: Add a plan review service.' is in content
      Then '### Files' is in content
      Then 'taskledger/services/plan_review.py' is in content
      Then '### Test Commands' is in content
      Then 'pytest tests/test_plan_review.py -q' is in content
      Then '### Expected Outputs' is in content
      Then 'All plan review tests pass.' is in content

    @req-REQ-0038 @ac-AC-0444
    Example: Plan Review Reports Ready When Lint Passes And No Blockers
      Given the pytest test setup is prepared
      When plan review reports ready when lint passes and no blockers is executed
      Then isinstance succeeds

    @req-REQ-0038 @ac-AC-0442
    Example: Plan Review Reports Blocked For Open Questions
      Given the pytest test setup is prepared
      When plan review reports blocked for open questions is executed
      Then 'open_questions' is in kinds

    @req-REQ-0038 @ac-AC-0443
    Example: Plan Review Reports Blocked For Stale Answers
      Given the pytest test setup is prepared
      When plan review reports blocked for stale answers is executed
      Then 'stale_answers' is in kinds

    @req-REQ-0038 @ac-AC-0441
    Example: Plan Review Reports Blocked For Missing Todos
      Given the pytest test setup is prepared
      When plan review reports blocked for missing todos is executed
      Then 'missing_todos' is in kinds

    @req-REQ-0038 @ac-AC-0438
    Example: Plan Review Json Payload Is Structured
      Given the pytest test setup is prepared
      When plan review json payload is structured is executed
      Then isinstance succeeds
      Then isinstance succeeds
      Then isinstance succeeds

    @req-REQ-0038 @ac-AC-0445
    Example: Plan Review Stdout Markdown
      Given the pytest test setup is prepared
      When plan review stdout markdown is executed
      Then result.exit_code equals 0
      Then '# Proposed Plan:' is in result.stdout
      Then '## Review Summary' is in result.stdout

    @req-REQ-0038 @ac-AC-0440
    Example: Plan Review Output Writes File
      Given the pytest test setup is prepared
      When plan review output writes file is executed
      Then result.exit_code equals 0
      Then output_path.exists succeeds
      Then '# Proposed Plan:' is in written
      Then '## Review Summary' is in written

    @req-REQ-0038 @ac-AC-0437
    Example: Plan Review Json Output
      Given the pytest test setup is prepared
      When plan review json output is executed
      Then isinstance succeeds
      Then isinstance succeeds
      Then isinstance succeeds
