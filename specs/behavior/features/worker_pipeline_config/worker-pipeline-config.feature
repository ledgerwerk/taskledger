@area-worker_pipeline_config @feature-worker-pipeline-config @generated
Feature: Worker Pipeline Config

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-worker-pipeline-config
  Rule: Worker Pipeline Config

    @req-REQ-0072 @ac-AC-0808
    Example: No Worker Pipeline Section Preserves Default Config
      Given the pytest test setup is prepared
      When no worker pipeline section preserves default config is executed
      Then config.worker_pipeline is None

    @req-REQ-0072 @ac-AC-0806
    Example: Disabled Worker Pipeline Section Returns Disabled Config
      Given the pytest test setup is prepared
      When disabled worker pipeline section returns disabled config is executed
      Then config.worker_pipeline is not None

    @req-REQ-0072 @ac-AC-0811
    Example: Worker Pipeline Parse Three Step Config
      Given the pytest test setup is prepared
      When worker pipeline parse three step config is executed
      Then config.worker_pipeline is not None
      Then config.worker_pipeline.enabled is True
      Then config.worker_pipeline.name equals 'simple-three-context'
      Then config.worker_pipeline.mode equals 'guided'

    @req-REQ-0072 @ac-AC-0810
    Example: Worker Pipeline Parse Four Step Config Without Skeletor
      Given the pytest test setup is prepared
      When worker pipeline parse four step config without skeletor is executed
      Then config.worker_pipeline is not None

    @req-REQ-0072 @ac-AC-0809
    Example: Worker Pipeline Parse Custom Worker Name
      Given the pytest test setup is prepared
      When worker pipeline parse custom worker name is executed
      Then config.worker_pipeline is not None
      Then api_designer.label equals 'Api Designer'
      Then api_designer.todo_tag equals 'api-design'
      Then domain_reviewer.actor_role equals 'reviewer'

    @req-REQ-0072 @ac-AC-0807
    Example: Invalid worker pipeline configuration is rejected
      Given an enabled pipeline has missing steps, duplicate IDs, or invalid fields
      When Taskledger validates project configuration
      Then configuration loading fails with a validation error
