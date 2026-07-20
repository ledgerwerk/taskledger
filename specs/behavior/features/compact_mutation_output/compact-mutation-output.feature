@area-compact_mutation_output @feature-compact-mutation-output @generated
Feature: Compact Mutation Output

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-compact-mutation-output
  Rule: Compact Mutation Output

    @req-REQ-0013 @ac-AC-0120
    Example: Human Mode Does Not Contain Full Task
      Given the pytest test setup is prepared
      When human mode does not contain full task is executed
      Then result.exit_code equals 0
      Then '"task"' is not in result.stdout
      Then 'accepted_plan' is not in result.stdout

    @req-REQ-0013 @ac-AC-0123
    Example: Json Mode Compact Payload
      Given the pytest test setup is prepared
      When json mode compact payload is executed
      Then result.exit_code equals 0
      Then 'todo' is in result_data
      Then 'progress' is in result_data
      Then 'next_command' is in result_data
      Then 'accepted_plan' is not in result_data

    @req-REQ-0013 @ac-AC-0121
    Example: Human Mode Does Not Contain Full Task
      Given the pytest test setup is prepared
      When human mode does not contain full task is executed
      Then add_result.exit_code equals 0
      Then result.exit_code equals 0
      Then '"task"' is not in result.stdout
      Then 'accepted_plan' is not in result.stdout

    @req-REQ-0013 @ac-AC-0124
    Example: Json Mode Compact Payload
      Given the pytest test setup is prepared
      When json mode compact payload is executed
      Then add_result.exit_code equals 0
      Then result.exit_code equals 0
      Then 'progress' is in result_data
      Then 'next_command' is in result_data
      Then 'accepted_plan' is not in result_data

    @req-REQ-0013 @ac-AC-0122
    Example: Human Mode Does Not Contain Full Task
      Given the pytest test setup is prepared
      When human mode does not contain full task is executed
      Then result.exit_code equals 0
      Then '"task"' is not in result.stdout
      Then 'accepted_plan' is not in result.stdout

    @req-REQ-0013 @ac-AC-0125
    Example: Json Mode Compact Payload
      Given the pytest test setup is prepared
      When json mode compact payload is executed
      Then result.exit_code equals 0
      Then 'task_id' is in result_data
      Then 'run_id' is in result_data
      Then 'next_command' is in result_data
      Then 'accepted_plan' is not in result_data

    @req-REQ-0013 @ac-AC-0119
    Example: Cli Implement No Raw Render Json Payload
      Given the pytest test setup is prepared
      When cli implement no raw render json payload is executed
      Then 'typer.echo(\n            render_json(' is not in content
