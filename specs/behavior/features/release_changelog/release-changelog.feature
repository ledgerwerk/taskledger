@area-release_changelog @feature-release-changelog @generated
Feature: Release Changelog

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-release-changelog
  Rule: Release Changelog

    @req-REQ-0046 @ac-AC-0520
    Example: Release Tag Persists Release Record
      Given the pytest test setup is prepared
      When release tag persists release record is executed
      Then result.exit_code equals 0

    @req-REQ-0046 @ac-AC-0522
    Example: Release Tag Rejects Non Done Boundary
      Given the pytest test setup is prepared
      When release tag rejects non done boundary is executed
      Then result.exit_code equals 0
      Then tag_result.exit_code does not equal 0

    @req-REQ-0046 @ac-AC-0521
    Example: Release Tag Rejects Duplicate Version
      Given the pytest test setup is prepared
      When release tag rejects duplicate version is executed
      Then result.exit_code does not equal 0

    @req-REQ-0046 @ac-AC-0516
    Example: Release Changelog Markdown Includes Instruction And Evidence
      Given the pytest test setup is prepared
      When release changelog markdown includes instruction and evidence is executed
      Then result.exit_code equals 0
      Then expected_line is in result.stdout
      Then '## LLM instruction' is in result.stdout
      Then 'Improve dashboard refresh stability' is in result.stdout
      Then 'Implementation summary:' is in result.stdout
      Then 'Relevant changes:' is in result.stdout
      Then 'Evidence:' is in result.stdout
      Then "python -c print('ok')" is in result.stdout

    @req-REQ-0046 @ac-AC-0512
    Example: Release Changelog From Task Is Inclusive
      Given the pytest test setup is prepared
      When release changelog from task is inclusive is executed
      Then first is in task_ids
      Then second is in task_ids

    @req-REQ-0046 @ac-AC-0513
    Example: Release Changelog From Task Rejects Multiple Selectors
      Given the pytest test setup is prepared
      When release changelog from task rejects multiple selectors is executed
      Then result.exit_code does not equal 0

    @req-REQ-0046 @ac-AC-0511
    Example: Release Changelog Fail On Omitted
      Given the pytest test setup is prepared
      When release changelog fail on omitted is executed
      Then result.exit_code does not equal 0
      Then 'Omitted tasks found' is in omitted_text

    @req-REQ-0046 @ac-AC-0514
    Example: Release Changelog Include Status Implemented
      Given the pytest test setup is prepared
      When release changelog include status implemented is executed
      Then failed is in task_ids

    @req-REQ-0046 @ac-AC-0517
    Example: Release Changelog Target Changelog And Release Date
      Given the pytest test setup is prepared
      When release changelog target changelog and release date is executed
      Then md_result.exit_code equals 0
      Then '## Changelog edit guidance' is in md_result.stdout
      Then 'Target changelog: CHANGELOG.md' is in md_result.stdout
      Then 'Use release date: 2026-05-30' is in md_result.stdout
      Then md_result2.exit_code equals 0
      Then '## Changelog edit guidance' is not in md_result2.stdout

    @req-REQ-0046 @ac-AC-0515
    Example: Release Changelog Include Status Rejects Unknown
      Given the pytest test setup is prepared
      When release changelog include status rejects unknown is executed
      Then result.exit_code does not equal 0

    @req-REQ-0046 @ac-AC-0518
    Example: Release listing is ordered by boundary task
      Given several release records exist at different task boundaries
      When releases are listed
      Then releases are ordered by their boundary tasks

    @req-REQ-0046 @ac-AC-0519
    Example: Release show returns the persisted release record
      Given a release record has been tagged
      When that release is shown
      Then its persisted version and boundary metadata are returned

    @req-REQ-0046 @ac-AC-0510
    Example: Changelog defaults to done tasks and reports omissions
      Given a release range contains done and unfinished tasks
      When a changelog is generated with default status selection
      Then done tasks are included
      And omitted unfinished tasks are reported

    @req-REQ-0046 @ac-AC-0509
    Example: Changelog supports a bootstrap starting task
      Given no prior release boundary is available
      When changelog generation starts from an explicit task
      Then tasks from that bootstrap boundary are considered
