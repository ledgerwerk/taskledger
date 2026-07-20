@area-worker_pipeline_context @feature-worker-pipeline-context @generated
Feature: Worker Pipeline Context

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-worker-pipeline-context
  Rule: Worker Pipeline Context

    @req-REQ-0073 @ac-AC-0812
    Example: Context For Implementer Unchanged Without Worker Pipeline
      Given the pytest test setup is prepared
      When context for implementer unchanged without worker pipeline is executed
      Then before.exit_code equals 0
      Then after.exit_code equals 0
      Then after.stdout equals before.stdout

    @req-REQ-0073 @ac-AC-0815
    Example: Worker Context Renders Base Context Plus Worker Guidance
      Given the pytest test setup is prepared
      When worker context renders base context plus worker guidance is executed
      Then result.exit_code equals 0
      Then '# Implementation Context:' is in result.stdout
      Then '## Worker step' is in result.stdout
      Then '- id: tester' is in result.stdout
      Then '- lifecycle_stage: implementation' is in result.stdout
      Then '- base_context: implementer' is in result.stdout
      Then '- actor_role: implementer' is in result.stdout
      Then '- kind: check' is in result.stdout
      Then '- todo_tag: test-first' is in result.stdout
      Then '- test_command_policy: may_fail' is in result.stdout
      Then 'Add regression tests that fail for the expected reason' is in result.stdout
      Then 'record failing test commands as evidence when this worker step expects them' is in result.stdout
      Then 'Must not:' is in result.stdout
      Then 'Do not implement production behavior to make the test pass.' is in result.stdout

    @req-REQ-0073 @ac-AC-0814
    Example: Pipeline Context Command Renders Worker Context
      Given the pytest test setup is prepared
      When pipeline context command renders worker context is executed
      Then result.exit_code equals 0
      Then '## Worker step' is in result.stdout
      Then 'Test Writer' is in result.stdout

    @req-REQ-0073 @ac-AC-0813
    Example: Context Worker Requires Enabled Pipeline
      Given the pytest test setup is prepared
      When context worker requires enabled pipeline is executed
      Then result.exit_code does not equal 0
