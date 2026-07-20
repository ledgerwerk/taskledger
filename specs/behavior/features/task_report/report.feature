@area-task_report @feature-task-report @generated
Feature: Task Report

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-task-report
  Rule: Task Report

    @req-REQ-0061 @ac-AC-0659
    Example: Task Report Full Markdown Includes Major Sections
      Given the pytest test setup is prepared
      When task report full markdown includes major sections is executed
      Then isinstance succeeds
      Then '## Summary' is in content
      Then '## Accepted Plan' is in content
      Then '## Acceptance Criteria' is in content
      Then '## Todo Checklist' is in content
      Then '## Implementation' is in content
      Then '## Code Reviews' is in content
      Then '## Code Changes' is in content
      Then '## Validation' is in content
      Then '## Worker Role' is not in content
      Then '## Worker Contract' is not in content
      Then '## Required Output' is not in content

    @req-REQ-0061 @ac-AC-0666
    Example: Task Report Planning Preset Excludes Impl And Val
      Given the pytest test setup is prepared
      When task report planning preset excludes impl and val is executed
      Then isinstance succeeds
      Then '## Plans' is in content
      Then '## Questions' is in content
      Then '## Implementation' is not in content
      Then '## Code Reviews' is not in content
      Then '## Validation' is not in content
      Then '## Code Changes' is not in content

    @req-REQ-0061 @ac-AC-0660
    Example: Task Report Implementation Preset Includes Code Reviews
      Given the pytest test setup is prepared
      When task report implementation preset includes code reviews is executed
      Then isinstance succeeds
      Then '## Code Reviews' is in content
      Then 'review-0001' is in content

    @req-REQ-0061 @ac-AC-0667
    Example: Task Report Planning Report Includes Proposed Plan Details
      Given the pytest test setup is prepared
      When task report planning report includes proposed plan details is executed
      Then isinstance succeeds
      Then '- plan-v1 — proposed' is in content
      Then '### Reviewable Plan Details' is in content
      Then '#### plan-v1 — proposed' is in content
      Then 'Render this proposed plan body in the task report.' is in content
      Then 'Proposed criterion is visible.' is in content
      Then 'Proposed todo is visible.' is in content
      Then 'No accepted plan.' is in content

    @req-REQ-0061 @ac-AC-0671
    Example: Task Report Without Removes Sections
      Given the pytest test setup is prepared
      When task report without removes sections is executed
      Then isinstance succeeds
      Then '## Todo Checklist' is not in content
      Then '## Acceptance Criteria' is not in content
      Then '## Summary' is in content

    @req-REQ-0061 @ac-AC-0658
    Example: Task Report Explicit Sections Override Preset
      Given the pytest test setup is prepared
      When task report explicit sections override preset is executed
      Then isinstance succeeds
      Then '## Summary' is in content
      Then '## Todo Checklist' is in content
      Then '## Implementation' is not in content
      Then '## Validation' is not in content

    @req-REQ-0061 @ac-AC-0656
    Example: Task Report Archive Includes Events
      Given the pytest test setup is prepared
      When task report archive includes events is executed
      Then isinstance succeeds
      Then '## Events' is in content

    @req-REQ-0061 @ac-AC-0657
    Example: Task Report Events Limit
      Given the pytest test setup is prepared
      When task report events limit is executed
      Then isinstance succeeds
      Then '## Events' is in content

    @req-REQ-0061 @ac-AC-0661
    Example: Task Report Include Command Log Section
      Given the pytest test setup is prepared
      When task report include command log section is executed
      Then isinstance succeeds
      Then '## Command Transcript' is in content

    @req-REQ-0061 @ac-AC-0663
    Example: Task Report Json Payload Is Structured
      Given the pytest test setup is prepared
      When task report json payload is structured is executed
      Then isinstance succeeds
      Then isinstance succeeds

    @req-REQ-0061 @ac-AC-0669
    Example: Task Report Stdout Markdown
      Given the pytest test setup is prepared
      When task report stdout markdown is executed
      Then exit_code equals 0
      Then '## Summary' is in stdout

    @req-REQ-0061 @ac-AC-0665
    Example: Task Report Output Writes File
      Given the pytest test setup is prepared
      When task report output writes file is executed
      Then exit_code equals 0
      Then 'wrote task report' is in stdout
      Then output_path.exists succeeds

    @req-REQ-0061 @ac-AC-0664
    Example: Task Report Output Json
      Given the pytest test setup is prepared
      When task report output json is executed
      Then exit_code equals 0

    @req-REQ-0061 @ac-AC-0670
    Example: Task Report Uses Active Task Default
      Given the pytest test setup is prepared
      When task report uses active task default is executed
      Then exit_code equals 0

    @req-REQ-0061 @ac-AC-0668
    Example: Task Report Preset Planning
      Given the pytest test setup is prepared
      When task report preset planning is executed
      Then exit_code equals 0
      Then '## Plans' is in stdout
      Then '## Implementation' is not in stdout

    @req-REQ-0061 @ac-AC-0672
    Example: Task Report Without Todos And Criteria
      Given the pytest test setup is prepared
      When task report without todos and criteria is executed
      Then exit_code equals 0
      Then '## Todo Checklist' is not in stdout
      Then '## Acceptance Criteria' is not in stdout
      Then '## Summary' is in stdout

    @req-REQ-0061 @ac-AC-0662
    Example: Task Report Invalid Format
      Given the pytest test setup is prepared
      When task report invalid format is executed
      Then exit_code does not equal 0
