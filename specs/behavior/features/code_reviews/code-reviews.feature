@area-code_reviews @feature-code-reviews @generated
Feature: Code Reviews

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-code-reviews
  Rule: Code Reviews

    @req-REQ-0009 @ac-AC-0096
    Example: Code Review Record Round Trip
      Given the pytest test setup is prepared
      When code review record round trip is executed
      Then loaded.review_id equals 'review-0001'
      Then loaded.result equals 'pass'
      Then loaded.source equals 'working_tree'

    @req-REQ-0009 @ac-AC-0101
    Example: Storage Save List Resolve Code Reviews
      Given the pytest test setup is prepared
      When storage save list resolve code reviews is executed
      Then resolved.review_id equals 'review-0001'

    @req-REQ-0009 @ac-AC-0097
    Example: Service Records And Lists Manual Review
      Given the pytest test setup is prepared
      When service records and lists manual review is executed
      Then review.review_id equals 'review-0001'
      Then review.source equals 'manual'
      Then shown.body equals 'No blocking issues.'

    @req-REQ-0009 @ac-AC-0099
    Example: Service Records Review After Task Is Done
      Given the pytest test setup is prepared
      When service records review after task is done is executed
      Then review.review_id equals 'review-0001'
      Then review.implementation_run is not None
      Then shown.body equals 'Post-completion code review.'

    @req-REQ-0009 @ac-AC-0100
    Example: Service Records Working Tree Git Metadata
      Given the pytest test setup is prepared
      When service records working tree git metadata is executed
      Then review.source equals 'working_tree'
      Then review.git_status_short is not None
      Then review.git_diff_hash is not None
      Then review.git_diff_hash.startswith succeeds
      Then 'sample.txt' is in review.git_changed_paths

    @req-REQ-0009 @ac-AC-0098
    Example: Service Records Commit Git Metadata
      Given the pytest test setup is prepared
      When service records commit git metadata is executed
      Then review.source equals 'commit'
      Then review.git_commit is not None
      Then 'sample.txt' is in review.git_changed_paths

    @req-REQ-0009 @ac-AC-0094
    Example: Cli Review Record List Show And Json
      Given the pytest test setup is prepared
      When cli review record list show and json is executed
      Then 'review-0001' is in list_result.stdout
      Then 'Looks good.' is in show_result.stdout

    @req-REQ-0009 @ac-AC-0095
    Example: Cli Review Record Summary And File Are Mutually Exclusive
      Given the pytest test setup is prepared
      When cli review record summary and file are mutually exclusive is executed
      Then result.exit_code does not equal 0
      Then 'Use either --summary or --summary-file' is in stderr
