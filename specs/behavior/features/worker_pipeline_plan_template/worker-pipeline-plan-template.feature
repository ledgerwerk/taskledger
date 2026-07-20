@area-worker_pipeline_plan_template @feature-worker-pipeline-plan-template @generated
Feature: Worker Pipeline Plan Template

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-worker-pipeline-plan-template
  Rule: Worker Pipeline Plan Template

    @req-REQ-0075 @ac-AC-0820
    Example: Plan Template Unchanged Without Worker Pipeline
      Given the pytest test setup is prepared
      When plan template unchanged without worker pipeline is executed
      Then result.exit_code equals 0
      Then '## Optional worker pipeline todo hints' is not in result.stdout
      Then 'worker_step:' is not in result.stdout

    @req-REQ-0075 @ac-AC-0819
    Example: Plan Template Requires Opt In Flag For Worker Pipeline Hints
      Given the pytest test setup is prepared
      When plan template requires opt in flag for worker pipeline hints is executed
      Then result.exit_code equals 0
      Then '## Optional worker pipeline todo hints' is not in result.stdout
      Then 'api-designer' is not in result.stdout

    @req-REQ-0075 @ac-AC-0822
    Example: Worker Plan Template Uses Configured Steps Not Hardcoded Names
      Given the pytest test setup is prepared
      When worker plan template uses configured steps not hardcoded names is executed
      Then result.exit_code equals 0
      Then '## Optional worker pipeline todo hints' is in result.stdout
      Then 'worker_step: "api-designer"' is in result.stdout
      Then 'worker_step: "coder"' is in result.stdout
      Then 'skeletor' is not in result.stdout

    @req-REQ-0075 @ac-AC-0821
    Example: Plan Template Worker Hints Require Template Or Guided Mode
      Given the pytest test setup is prepared
      When plan template worker hints require template or guided mode is executed
      Then result.exit_code does not equal 0
      Then "mode = 'template' or 'guided'" is in output
