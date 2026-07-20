@area-atomic_fast_io @feature-atomic-fast-io @generated
Feature: Atomic Fast Io

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-atomic-fast-io
  Rule: Atomic Fast Io

    @req-REQ-0006 @ac-AC-0082
    Example: Atomic Write Uses Fsync By Default
      Given the pytest test setup is prepared
      When atomic write uses fsync by default is executed
      Then calls is truthy
