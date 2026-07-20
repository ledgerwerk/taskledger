@area-worker_pipeline_cli @feature-worker-pipeline-cli @generated
Feature: Worker Pipeline Cli

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-worker-pipeline-cli
  Rule: Worker Pipeline Cli

    @req-REQ-0071 @ac-AC-0798
    Example: Pipeline Commands Print No Config Message
      Given the pytest test setup is prepared
      When pipeline commands print no config message is executed
      Then result.exit_code equals 0

    @req-REQ-0071 @ac-AC-0797
    Example: Pipeline Commands Print Disabled Message
      Given the pytest test setup is prepared
      When pipeline commands print disabled message is executed
      Then result.exit_code equals 0

    @req-REQ-0071 @ac-AC-0805
    Example: Pipeline Show And List Render Enabled Config
      Given the pytest test setup is prepared
      When pipeline show and list render enabled config is executed
      Then show_result.exit_code equals 0
      Then list_result.exit_code equals 0
      Then 'planner' is in list_result.stdout
      Then 'Test Writer' is in list_result.stdout
      Then 'reviewer' is in list_result.stdout

    @req-REQ-0071 @ac-AC-0804
    Example: Pipeline Next Returns Planner Before Plan Acceptance
      Given the pytest test setup is prepared
      When pipeline next returns planner before plan acceptance is executed
      Then result.exit_code equals 0

    @req-REQ-0071 @ac-AC-0799
    Example: Pipeline Next Advances After Closed Worker Review Handoff
      Given the pytest test setup is prepared
      When pipeline next advances after closed worker review handoff is executed
      Then first.exit_code equals 0
      Then second.exit_code equals 0

    @req-REQ-0071 @ac-AC-0800
    Example: Pipeline Next Advances After Passing Code Review Record
      Given the pytest test setup is prepared
      When pipeline next advances after passing code review record is executed
      Then before.exit_code equals 0
      Then record.exit_code equals 0
      Then after.exit_code equals 0

    @req-REQ-0071 @ac-AC-0803
    Example: Pipeline Next Keeps Code Review When Latest Review Failed
      Given the pytest test setup is prepared
      When pipeline next keeps code review when latest review failed is executed
      Then record.exit_code equals 0
      Then next_step.exit_code equals 0

    @req-REQ-0071 @ac-AC-0801
    Example: Pipeline Next Ignores Cancelled Worker Review Handoff
      Given the pytest test setup is prepared
      When pipeline next ignores cancelled worker review handoff is executed
      Then handoff.exit_code equals 0
      Then cancel.exit_code equals 0
      Then result.exit_code equals 0

    @req-REQ-0071 @ac-AC-0796
    Example: Next Action Guided Worker Pipeline Payload And Commands
      Given the pytest test setup is prepared
      When next action guided worker pipeline payload and commands is executed
      Then result.exit_code equals 0

    @req-REQ-0071 @ac-AC-0795
    Example: Next Action Guided Worker Pipeline Human Output
      Given the pytest test setup is prepared
      When next action guided worker pipeline human output is executed
      Then result.exit_code equals 0
      Then 'Worker step: tester' is in result.stdout
      Then 'Worker context: taskledger pipeline context tester' is in result.stdout
      Then 'Worker handoff: taskledger handoff create --worker tester --summary "..."' is in result.stdout

    @req-REQ-0071 @ac-AC-0802
    Example: Pipeline Next Ignores Normal Review Handoff
      Given the pytest test setup is prepared
      When pipeline next ignores normal review handoff is executed
      Then handoff.exit_code equals 0
      Then close.exit_code equals 0
      Then result.exit_code equals 0
