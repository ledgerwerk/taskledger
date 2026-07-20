@area-worker_pipeline_handoff @feature-worker-pipeline-handoff @generated
Feature: Worker Pipeline Handoff

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-worker-pipeline-handoff
  Rule: Worker Pipeline Handoff

    @req-REQ-0074 @ac-AC-0818
    Example: Worker Handoff Stores Worker Step Id Sparse
      Given the pytest test setup is prepared
      When worker handoff stores worker step id sparse is executed
      Then worker_result.exit_code equals 0
      Then normal_result.exit_code equals 0
      Then 'worker_step_id' is not in normal_payload

    @req-REQ-0074 @ac-AC-0817
    Example: Worker Handoff Rejects Conflicting Mode Override
      Given the pytest test setup is prepared
      When worker handoff rejects conflicting mode override is executed
      Then result.exit_code does not equal 0
      Then "requires mode 'implementation'" is in output

    @req-REQ-0074 @ac-AC-0816
    Example: Worker Handoff Rejects Conflicting Context Override
      Given the pytest test setup is prepared
      When worker handoff rejects conflicting context override is executed
      Then result.exit_code does not equal 0
      Then "requires context 'implementer'" is in output
