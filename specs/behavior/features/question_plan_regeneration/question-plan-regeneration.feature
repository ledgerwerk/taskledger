@area-question_plan_regeneration @feature-question-plan-regeneration @generated
Feature: Question Plan Regeneration

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-question-plan-regeneration
  Rule: Question Plan Regeneration

    @req-REQ-0044 @ac-AC-0504
    Example: Required Question Blocks Approval Until Answered And Regenerated
      Given the pytest test setup is prepared
      When required question blocks approval until answered and regenerated is executed
      Then blocked.exit_code does not equal 0

    @req-REQ-0044 @ac-AC-0499
    Example: Plan Regeneration Finishes Orphaned Latest Planning Run
      Given the pytest test setup is prepared
      When plan regeneration finishes orphaned latest planning run is executed
      Then task.latest_planning_run is not None
      Then regenerated.exit_code equals 0
      Then run.status equals 'finished'

    @req-REQ-0044 @ac-AC-0495
    Example: Answered Question Blocks Approval Of Stale Plan
      Given the pytest test setup is prepared
      When answered question blocks approval of stale plan is executed
      Then blocked.exit_code equals 3

    @req-REQ-0044 @ac-AC-0494
    Example: Answer Many Rejects Duplicate Plain Text Ids
      Given the pytest test setup is prepared
      When answer many rejects duplicate plain text ids is executed
      Then result.exit_code does not equal 0

    @req-REQ-0044 @ac-AC-0505
    Example: Required Question Needs Explicit User Source For Agent
      Given the pytest test setup is prepared
      When required question needs explicit user source for agent is executed
      Then result.exit_code does not equal 0

    @req-REQ-0044 @ac-AC-0501
    Example: Question Answer Accepts Question Option Alias
      Given the pytest test setup is prepared
      When question answer accepts question option alias is executed
      Then result.exit_code equals 0

    @req-REQ-0044 @ac-AC-0502
    Example: Question Answer Rejects Both Positional And Option Id
      Given the pytest test setup is prepared
      When question answer rejects both positional and option id is executed
      Then result.exit_code does not equal 0
      Then 'Provide exactly one question id' is in combined

    @req-REQ-0044 @ac-AC-0503
    Example: Question Status Human Lists Required Open Ids
      Given the pytest test setup is prepared
      When question status human lists required open ids is executed
      Then result.exit_code equals 0
      Then 'Open required questions: q-0002' is in result.stdout
      Then 'Answered required questions: q-0001' is in result.stdout
      Then 'Do not infer answers.' is in result.stdout

    @req-REQ-0044 @ac-AC-0500
    Example: Plan Upsert From Answers Releases Planning Lock And Allows Accept
      Given the pytest test setup is prepared
      When plan upsert from answers releases planning lock and allows accept is executed
      Then accepted.exit_code equals 0

    @req-REQ-0044 @ac-AC-0496
    Example: Changing an answer requires plan regeneration again
      Given a plan was regenerated from an answered required question
      When that answer changes
      Then the current plan becomes stale again

    @req-REQ-0044 @ac-AC-0493
    Example: Answer-many records user answers and requires regeneration
      Given several planning questions are open
      When user-provided answers are recorded together
      Then each answer is persisted with user source
      And plan regeneration is required

    @req-REQ-0044 @ac-AC-0497
    Example: Next action prefers answering an open planning question
      Given required planning questions remain open
      When the next action is requested
      Then the recommended action is to answer a question

    @req-REQ-0044 @ac-AC-0498
    Example: Next action prefers regeneration for stale answers
      Given required questions are answered but the plan is stale
      When the next action is requested
      Then the recommended action is to regenerate the plan
