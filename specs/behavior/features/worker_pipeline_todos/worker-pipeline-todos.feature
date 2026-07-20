@area-worker_pipeline_todos @feature-worker-pipeline-todos @generated
Feature: Worker Pipeline Todos

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-worker-pipeline-todos
  Rule: Worker Pipeline Todos

    @req-REQ-0076 @ac-AC-0823
    Example: Pipeline Next Returns First Open Worker Todo
      Given the pytest test setup is prepared
      When pipeline next returns first open worker todo is executed
      Then result.exit_code equals 0

    @req-REQ-0076 @ac-AC-0824
    Example: Plan Todo Worker Step Requires Enabled Pipeline
      Given the pytest test setup is prepared
      When plan todo worker step requires enabled pipeline is executed
      Then result.exit_code does not equal 0
      Then 'requires an enabled worker pipeline' is in output
