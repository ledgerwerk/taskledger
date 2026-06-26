@area-plan_lint @feature-plan-lint @generated @needs-review
Feature: Plan Lint

  Generated from pytest tests. Review and refine domain language before using as acceptance evidence.

  @rule-plan-lint
  Rule: Plan Lint

    @bdd-plan-lint-plan-lint-passes-for-executable-plan @needs-review
    Example: Plan Lint Passes For Executable Plan
      Given the pytest test setup is prepared
      When plan lint passes for executable plan is executed
      Then result.exit_code equals 0
      Then isinstance succeeds
      Then isinstance succeeds

    @bdd-plan-lint-plan-template-prints-stdout-when-no-file @needs-review
    Example: Plan Template Prints Stdout When No File
      Given the pytest test setup is prepared
      When plan template prints stdout when no file is executed
      Then result.exit_code equals 0
      Then result.stdout.startswith succeeds
      Then 'acceptance_criteria:' is in result.stdout

    @bdd-plan-lint-plan-guidance-human-message-when-no-profile @needs-review
    Example: Plan Guidance Human Message When No Profile
      Given the pytest test setup is prepared
      When plan guidance human message when no profile is executed
      Then result.exit_code equals 0
      Then 'Built-in Taskledger plan input guidance' is in result.stdout
      Then 'Acceptance criteria use `text`' is in result.stdout

    @bdd-plan-lint-plan-guidance-json-contract-when-no-profile @needs-review
    Example: Plan Guidance Json Contract When No Profile
      Given the pytest test setup is prepared
      When plan guidance json contract when no profile is executed
      Then result.exit_code equals 0
      Then isinstance succeeds

    @bdd-plan-lint-plan-guidance-rejects-invalid-format @needs-review
    Example: Plan Guidance Rejects Invalid Format
      Given the pytest test setup is prepared
      When plan guidance rejects invalid format is executed
      Then result.exit_code does not equal 0
      Then 'Invalid --format value' is in combined

    @bdd-plan-lint-plan-template-from-answers-writes-file @needs-review
    Example: Plan Template From Answers Writes File
      Given the pytest test setup is prepared
      When plan template from answers writes file is executed
      Then result.exit_code equals 0
      Then '## Notes from answered questions' is in contents
      Then '- q-0001: PostgreSQL.' is in contents

    @bdd-plan-lint-plan-template-include-guidance-writes-guidance-in-file @needs-review
    Example: Plan Template Include Guidance Writes Guidance In File
      Given the pytest test setup is prepared
      When plan template include guidance writes guidance in file is executed
      Then result.exit_code equals 0
      Then '<!-- Advisory project planning guidance from taskledger plan guidance. -->' is in contents

    @bdd-plan-lint-filled-plan-template-passes-lint @needs-review
    Example: Filled Plan Template Passes Lint
      Given the pytest test setup is prepared
      When filled plan template passes lint is executed
      Then result.exit_code equals 0
      Then upserted.exit_code equals 0
      Then linted.exit_code equals 0

    @bdd-plan-lint-plan-lint-reports-missing-goal @needs-review
    Example: Plan Lint Reports Missing Goal
      Given the pytest test setup is prepared
      When plan lint reports missing goal is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED
      Then 'missing_goal' is in codes

    @bdd-plan-lint-plan-lint-reports-missing-criteria @needs-review
    Example: Plan Lint Reports Missing Criteria
      Given the pytest test setup is prepared
      When plan lint reports missing criteria is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED
      Then 'missing_acceptance_criteria' is in codes

    @bdd-plan-lint-plan-lint-reports-missing-todos @needs-review
    Example: Plan Lint Reports Missing Todos
      Given the pytest test setup is prepared
      When plan lint reports missing todos is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED
      Then 'missing_todos' is in codes

    @bdd-plan-lint-plan-lint-allows-todo-waiver-reason @needs-review
    Example: Plan Lint Allows Todo Waiver Reason
      Given the pytest test setup is prepared
      When plan lint allows todo waiver reason is executed
      Then result.exit_code equals 0
      Then 'missing_todos' is not in codes

    @bdd-plan-lint-plan-lint-rejects-vague-todo @needs-review
    Example: Plan Lint Rejects Vague Todo
      Given the pytest test setup is prepared
      When plan lint rejects vague todo is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED
      Then 'todo_not_concrete' is in codes

    @bdd-plan-lint-plan-lint-warns-on-placeholders @needs-review
    Example: Plan Lint Warns On Placeholders
      Given the pytest test setup is prepared
      When plan lint warns on placeholders is executed
      Then result.exit_code equals 0

    @bdd-plan-lint-plan-lint-strict-fails-on-placeholders @needs-review
    Example: Plan Lint Strict Fails On Placeholders
      Given the pytest test setup is prepared
      When plan lint strict fails on placeholders is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED

    @bdd-plan-lint-plan-lint-warns-when-todos-lack-validation-hints-and-no-tests @needs-review
    Example: Plan Lint Warns When Todos Lack Validation Hints And No Tests
      Given the pytest test setup is prepared
      When plan lint warns when todos lack validation hints and no tests is executed
      Then result.exit_code equals 0

    @bdd-plan-lint-plan-lint-strict-errors-when-todos-lack-validation-hints-and-no-tests @needs-review
    Example: Plan Lint Strict Errors When Todos Lack Validation Hints And No Tests
      Given the pytest test setup is prepared
      When plan lint strict errors when todos lack validation hints and no tests is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED

    @bdd-plan-lint-plan-lint-defaults-to-latest-plan @needs-review
    Example: Plan Lint Defaults To Latest Plan
      Given the pytest test setup is prepared
      When plan lint defaults to latest plan is executed
      Then result.exit_code equals 0

    @bdd-plan-lint-plan-approval-blocks-lint-errors @needs-review
    Example: Plan Approval Blocks Lint Errors
      Given the pytest test setup is prepared
      When plan approval blocks lint errors is executed
      Then result.exit_code does not equal 0

    @bdd-plan-lint-plan-approval-lint-escape-hatch-requires-reason @needs-review
    Example: Plan Approval Lint Escape Hatch Requires Reason
      Given the pytest test setup is prepared
      When plan approval lint escape hatch requires reason is executed
      Then result.exit_code does not equal 0

    @bdd-plan-lint-plan-approval-lint-escape-hatch-succeeds-with-reason @needs-review
    Example: Plan Approval Lint Escape Hatch Succeeds With Reason
      Given the pytest test setup is prepared
      When plan approval lint escape hatch succeeds with reason is executed
      Then result.exit_code equals 0

    @bdd-plan-lint-plan-lint-reports-missing-plan-body @needs-review
    Example: Plan Lint Reports Missing Plan Body
      Given the pytest test setup is prepared
      When plan lint reports missing plan body is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED
      Then 'missing_plan_body' is in codes

    @bdd-plan-lint-plan-approval-blocks-missing-body @needs-review
    Example: Plan Approval Blocks Missing Body
      Given the pytest test setup is prepared
      When plan approval blocks missing body is executed
      Then result.exit_code does not equal 0

    @bdd-plan-lint-plan-lint-passes-with-body @needs-review
    Example: Plan Lint Passes With Body
      Given the pytest test setup is prepared
      When plan lint passes with body is executed
      Then result.exit_code equals 0
      Then 'missing_plan_body' is not in codes

    @bdd-plan-lint-plan-lint-human-output-renders-issue-details @needs-review
    Example: Plan Lint Human Output Renders Issue Details
      Given the pytest test setup is prepared
      When plan lint human output renders issue details is executed
      Then result.exit_code equals EXIT_CODE_VALIDATION_FAILED
      Then 'Plan lint failed' is in result.stdout
      Then 'Summary:' is in result.stdout
      Then 'ERROR todo_not_concrete' is in result.stdout
      Then 'plan.todos[0]' is in result.stdout
      Then 'No lint findings' is not in result.stdout

    @bdd-plan-lint-plan-lint-accepts-short-file-path-todo @needs-review
    Example: Plan Lint Accepts Short File Path Todo
      Given the pytest test setup is prepared
      When plan lint accepts short file path todo is executed
      Then result.exit_code equals 0
      Then 'todo_not_concrete' is not in codes
