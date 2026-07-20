@area-plan_lint @feature-plan-lint @generated
Feature: Plan Lint

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-plan-lint
  Rule: Plan Lint

    @req-REQ-0037 @ac-AC-0422
    Example: Plan Lint Passes For Executable Plan
      Given the pytest test setup is prepared
      When plan lint passes for executable plan is executed
      Then result.exit_code equals 0
      Then isinstance succeeds
      Then isinstance succeeds

    @req-REQ-0037 @ac-AC-0435
    Example: Plan Template Prints Stdout When No File
      Given the pytest test setup is prepared
      When plan template prints stdout when no file is executed
      Then result.exit_code equals 0
      Then result.stdout.startswith succeeds
      Then 'acceptance_criteria:' is in result.stdout

    @req-REQ-0037 @ac-AC-0415
    Example: Plan Guidance Human Message When No Profile
      Given the pytest test setup is prepared
      When plan guidance human message when no profile is executed
      Then result.exit_code equals 0
      Then 'Built-in Taskledger plan input guidance' is in result.stdout
      Then 'Acceptance criteria use `text`' is in result.stdout

    @req-REQ-0037 @ac-AC-0416
    Example: Plan Guidance Json Contract When No Profile
      Given the pytest test setup is prepared
      When plan guidance json contract when no profile is executed
      Then result.exit_code equals 0
      Then isinstance succeeds

    @req-REQ-0037 @ac-AC-0417
    Example: Plan Guidance Rejects Invalid Format
      Given the pytest test setup is prepared
      When plan guidance rejects invalid format is executed
      Then result.exit_code does not equal 0
      Then 'Invalid --format value' is in combined

    @req-REQ-0037 @ac-AC-0433
    Example: Plan Template From Answers Writes File
      Given the pytest test setup is prepared
      When plan template from answers writes file is executed
      Then result.exit_code equals 0
      Then '## Notes from answered questions' is in contents
      Then '- q-0001: PostgreSQL.' is in contents

    @req-REQ-0037 @ac-AC-0434
    Example: Plan Template Include Guidance Writes Guidance In File
      Given the pytest test setup is prepared
      When plan template include guidance writes guidance in file is executed
      Then result.exit_code equals 0
      Then '<!-- Advisory project planning guidance from taskledger plan guidance. -->' is in contents

    @req-REQ-0037 @ac-AC-0410
    Example: Filled Plan Template Passes Lint
      Given the pytest test setup is prepared
      When filled plan template passes lint is executed
      Then result.exit_code equals 0
      Then upserted.exit_code equals 0
      Then linted.exit_code equals 0

    @req-REQ-0037 @ac-AC-0426
    Example: Plan Lint Reports Missing Goal
      Given the pytest test setup is prepared
      When plan lint reports missing goal is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED
      Then 'missing_goal' is in codes

    @req-REQ-0037 @ac-AC-0425
    Example: Plan Lint Reports Missing Criteria
      Given the pytest test setup is prepared
      When plan lint reports missing criteria is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED
      Then 'missing_acceptance_criteria' is in codes

    @req-REQ-0037 @ac-AC-0428
    Example: Plan Lint Reports Missing Todos
      Given the pytest test setup is prepared
      When plan lint reports missing todos is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED
      Then 'missing_todos' is in codes

    @req-REQ-0037 @ac-AC-0419
    Example: Plan Lint Allows Todo Waiver Reason
      Given the pytest test setup is prepared
      When plan lint allows todo waiver reason is executed
      Then result.exit_code equals 0
      Then 'missing_todos' is not in codes

    @req-REQ-0037 @ac-AC-0424
    Example: Plan Lint Rejects Vague Todo
      Given the pytest test setup is prepared
      When plan lint rejects vague todo is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED
      Then 'todo_not_concrete' is in codes

    @req-REQ-0037 @ac-AC-0431
    Example: Plan Lint Warns On Placeholders
      Given the pytest test setup is prepared
      When plan lint warns on placeholders is executed
      Then result.exit_code equals 0

    @req-REQ-0037 @ac-AC-0430
    Example: Plan Lint Strict Fails On Placeholders
      Given the pytest test setup is prepared
      When plan lint strict fails on placeholders is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED

    @req-REQ-0037 @ac-AC-0432
    Example: Plan Lint Warns When Todos Lack Validation Hints And No Tests
      Given the pytest test setup is prepared
      When plan lint warns when todos lack validation hints and no tests is executed
      Then result.exit_code equals 0

    @req-REQ-0037 @ac-AC-0429
    Example: Plan Lint Strict Errors When Todos Lack Validation Hints And No Tests
      Given the pytest test setup is prepared
      When plan lint strict errors when todos lack validation hints and no tests is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED

    @req-REQ-0037 @ac-AC-0420
    Example: Plan Lint Defaults To Latest Plan
      Given the pytest test setup is prepared
      When plan lint defaults to latest plan is executed
      Then result.exit_code equals 0

    @req-REQ-0037 @ac-AC-0411
    Example: Plan Approval Blocks Lint Errors
      Given the pytest test setup is prepared
      When plan approval blocks lint errors is executed
      Then result.exit_code does not equal 0

    @req-REQ-0037 @ac-AC-0413
    Example: Plan Approval Lint Escape Hatch Requires Reason
      Given the pytest test setup is prepared
      When plan approval lint escape hatch requires reason is executed
      Then result.exit_code does not equal 0

    @req-REQ-0037 @ac-AC-0414
    Example: Plan Approval Lint Escape Hatch Succeeds With Reason
      Given the pytest test setup is prepared
      When plan approval lint escape hatch succeeds with reason is executed
      Then result.exit_code equals 0

    @req-REQ-0037 @ac-AC-0427
    Example: Plan Lint Reports Missing Plan Body
      Given the pytest test setup is prepared
      When plan lint reports missing plan body is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED
      Then 'missing_plan_body' is in codes

    @req-REQ-0037 @ac-AC-0412
    Example: Plan Approval Blocks Missing Body
      Given the pytest test setup is prepared
      When plan approval blocks missing body is executed
      Then result.exit_code does not equal 0

    @req-REQ-0037 @ac-AC-0423
    Example: Plan Lint Passes With Body
      Given the pytest test setup is prepared
      When plan lint passes with body is executed
      Then result.exit_code equals 0
      Then 'missing_plan_body' is not in codes

    @req-REQ-0037 @ac-AC-0421
    Example: Plan Lint Human Output Renders Issue Details
      Given the pytest test setup is prepared
      When plan lint human output renders issue details is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED
      Then 'Plan lint failed' is in result.stdout
      Then 'Summary:' is in result.stdout
      Then 'ERROR todo_not_concrete' is in result.stdout
      Then 'plan.todos[0]' is in result.stdout
      Then 'No lint findings' is not in result.stdout

    @req-REQ-0037 @ac-AC-0418
    Example: Plan Lint Accepts Short File Path Todo
      Given the pytest test setup is prepared
      When plan lint accepts short file path todo is executed
      Then result.exit_code equals 0
      Then 'todo_not_concrete' is not in codes
