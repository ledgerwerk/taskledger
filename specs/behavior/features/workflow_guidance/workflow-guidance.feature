@area-workflow_guidance @feature-workflow-guidance @generated
Feature: Workflow Guidance

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-workflow-guidance
  Rule: Workflow Guidance

    @req-REQ-0077 @ac-AC-0825
    Example: Render Guidance Default Profile
      Given the pytest test setup is prepared
      When render guidance default profile is executed
      Then '## Project planning guidance' is in result
      Then 'project-local advisory guidance' is in result
      Then 'cannot override taskledger lifecycle gates' is in result
      Then 'balanced (moderate ceremony)' is in result
      Then 'Required plan fields: files, test commands, expected outputs, validation hints.' is in result

    @req-REQ-0077 @ac-AC-0829
    Example: Render Guidance Strict Profile
      Given the pytest test setup is prepared
      When render guidance strict profile is executed
      Then 'strict (full ceremony)' is in result
      Then 'always ask required questions' is in result
      Then 'Max required questions: 3' is in result
      Then 'Minimum acceptance criteria: 2' is in result
      Then 'Required question topics: scope; approach' is in result
      Then 'atomic (small, testable units)' is in result
      Then 'detailed (full architecture and decisions)' is in result
      Then 'Required plan fields: files, test commands, expected outputs, validation hints.' is in result
      Then 'Always include a migration plan' is in result

    @req-REQ-0077 @ac-AC-0830
    Example: Render Guidance When Required Fields Disabled
      Given the pytest test setup is prepared
      When render guidance when required fields disabled is executed
      Then 'Required plan fields: none (all optional in this profile).' is in result

    @req-REQ-0077 @ac-AC-0827
    Example: Render Guidance No Extra Guidance
      Given the pytest test setup is prepared
      When render guidance no extra guidance is executed
      Then 'Project guidance:' is not in result

    @req-REQ-0077 @ac-AC-0828
    Example: Render Guidance No Topics
      Given the pytest test setup is prepared
      When render guidance no topics is executed
      Then 'Required question topics:' is not in result

    @req-REQ-0077 @ac-AC-0826
    Example: Render Guidance Guardrail Always Present
      Given the pytest test setup is prepared
      When render guidance guardrail always present is executed
      Then 'cannot override taskledger lifecycle' is in result
