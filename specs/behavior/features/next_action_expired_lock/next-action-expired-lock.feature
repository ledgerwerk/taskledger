@area-next_action_expired_lock @feature-next-action-expired-lock @generated
Feature: Next Action Expired Lock

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-next-action-expired-lock
  Rule: Next Action Expired Lock

    @req-REQ-0034 @ac-AC-0374
    Example: Expired Impl Lock Next Action Recommends Resume
      Given the pytest test setup is prepared
      When expired impl lock next action recommends resume is executed
      Then r.exit_code equals 0

    @req-REQ-0034 @ac-AC-0375
    Example: Expired Impl Lock Resume Succeeds
      Given the pytest test setup is prepared
      When expired impl lock resume succeeds is executed
      Then r.exit_code equals 0

    @req-REQ-0034 @ac-AC-0376
    Example: Expired Planning Lock Still Routes To Repair
      Given the pytest test setup is prepared
      When expired planning lock still routes to repair is executed
      Then r.exit_code equals 0
      Then r.exit_code equals 0
      Then r.exit_code equals 0
      Then r.exit_code equals 0
