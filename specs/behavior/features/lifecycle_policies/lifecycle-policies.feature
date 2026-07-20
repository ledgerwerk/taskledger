@area-lifecycle_policies @feature-lifecycle-policies @generated
Feature: Lifecycle Policies

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-lifecycle-policies
  Rule: Lifecycle Policies

    @req-REQ-0029 @ac-AC-0337
    Example: Plan Proposal Uses Durable Status Plus Active Planning
      Given the pytest test setup is prepared
      When plan proposal uses durable status plus active planning is executed
      Then decision.ok is True

    @req-REQ-0029 @ac-AC-0336
    Example: Implementation Mutation Allows Active Implementation Without Status Flip
      Given the pytest test setup is prepared
      When implementation mutation allows active implementation without status flip is executed
      Then decision.ok is True
