@area-plan_todo_materialization @feature-plan-todo-materialization @generated
Feature: Plan Todo Materialization

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-plan-todo-materialization
  Rule: Plan Todo Materialization

    @req-REQ-0040 @ac-AC-0454
    Example: Plan Approval Materializes Structured Todos Once
      Given a proposed plan contains structured todo front matter
      When the plan is approved
      Then the structured todos are materialized once for the task
