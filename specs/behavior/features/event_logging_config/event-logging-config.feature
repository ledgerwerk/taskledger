@area-event_logging_config @feature-event-logging-config @generated
Feature: Event Logging Config

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-event-logging-config
  Rule: Event Logging Config

    @req-REQ-0019 @ac-AC-0279
    Example: Runtime Events Enabled By Default
      Given the pytest test setup is prepared
      When runtime events enabled by default is executed
      Then result.exit_code equals 0

    @req-REQ-0019 @ac-AC-0281
    Example: Task Events Shows Default Action Events
      Given the pytest test setup is prepared
      When task events shows default action events is executed
      Then result.exit_code equals 0

    @req-REQ-0019 @ac-AC-0277
    Example: Lock Break Writes Events By Default
      Given the pytest test setup is prepared
      When lock break writes events by default is executed
      Then result.exit_code equals 0

    @req-REQ-0019 @ac-AC-0280
    Example: Event Logging Override Disables New Events
      Given the pytest test setup is prepared
      When event logging override disables new events is executed
      Then any succeeds

    @req-REQ-0019 @ac-AC-0278
    Example: Lock Break Writes Events With Default Configuration
      Given the pytest test setup is prepared
      When lock break writes events with default configuration is executed
      Then result.exit_code equals 0
      Then any succeeds

    @req-REQ-0019 @ac-AC-0276
    Example: Existing Events Readable After Disable
      Given the pytest test setup is prepared
      When existing events readable after disable is executed
      Then result.exit_code equals 0
