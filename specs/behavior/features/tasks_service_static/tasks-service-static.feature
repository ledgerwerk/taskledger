@area-tasks_service_static @feature-tasks-service-static @generated
Feature: Tasks Service Static

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-tasks-service-static
  Rule: Tasks Service Static

    @req-REQ-0066 @ac-AC-0749
    Example: Services Tasks Has No Duplicate Top Level Function Names
      Given the task service module source is parsed
      When top level function definitions are inspected
      Then no duplicate function names are present
