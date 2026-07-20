@area-storage_repos @feature-storage-repos @generated
Feature: Storage Repos

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-storage-repos
  Rule: Storage Repos

    @req-REQ-0055 @ac-AC-0595
    Example: Add Repo
      Given the pytest test setup is prepared
      When add repo is executed
      Then repo.name equals 'my-code'
      Then repo.slug equals 'my-code'

    @req-REQ-0055 @ac-AC-0601
    Example: Resolve Repo
      Given the pytest test setup is prepared
      When resolve repo is executed
      Then found.name equals 'my-code'

    @req-REQ-0055 @ac-AC-0602
    Example: Resolve Repo By Slugified Ref
      Given the pytest test setup is prepared
      When resolve repo by slugified ref is executed
      Then found.name equals 'My Code'

    @req-REQ-0055 @ac-AC-0599
    Example: Remove Repo
      Given the pytest test setup is prepared
      When remove repo is executed
      Then removed.name equals 'my-code'

    @req-REQ-0055 @ac-AC-0605
    Example: Set Repo Role
      Given the pytest test setup is prepared
      When set repo role is executed
      Then updated.role equals 'both'

    @req-REQ-0055 @ac-AC-0604
    Example: Set Default Execution Repo
      Given the pytest test setup is prepared
      When set default execution repo is executed
      Then result.preferred_for_execution is True

    @req-REQ-0055 @ac-AC-0596
    Example: Clear Default Execution Repo
      Given the pytest test setup is prepared
      When clear default execution repo is executed
      Then all succeeds

    @req-REQ-0055 @ac-AC-0600
    Example: Repository records persist and reload
      Given project repository records are configured
      When the repository collection is saved and loaded
      Then repository names, paths, kinds, and roles are preserved

    @req-REQ-0055 @ac-AC-0597
    Example: Invalid repository configuration is rejected
      Given a repository has a duplicate name, invalid type, or missing path
      When it is added to project repository configuration
      Then the repository is rejected

    @req-REQ-0055 @ac-AC-0598
    Example: A readonly repository cannot be the execution default
      Given a configured repository is readonly
      When it is selected as the default execution repository
      Then the change is rejected

    @req-REQ-0055 @ac-AC-0603
    Example: The root repository reference resolves to the project root
      Given repository-aware project state
      When the root repository reference is resolved
      Then the project root is returned

    @req-REQ-0055 @ac-AC-0606
    Example: Unknown repository references are rejected
      Given a repository reference is not configured
      When Taskledger resolves the reference
      Then resolution fails with a not-found error
