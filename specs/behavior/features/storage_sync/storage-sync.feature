@area-storage_sync @feature-storage-sync @generated
Feature: Storage Sync

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-storage-sync
  Rule: Storage Sync

    @req-REQ-0056 @ac-AC-0610
    Example: Storage Where Reports External Storage Details
      Given the pytest test setup is prepared
      When storage where reports external storage details is executed
      Then init_result.exit_code equals 0
      Then result.exit_code equals 0

    @req-REQ-0056 @ac-AC-0608
    Example: Storage Move Copy Updates Config And Preserves Project Uuid
      Given the pytest test setup is prepared
      When storage move copy updates config and preserves project uuid is executed
      Then init_result.exit_code equals 0
      Then result.exit_code equals 0

    @req-REQ-0056 @ac-AC-0609
    Example: Storage Move Refuses Non Empty Target
      Given the pytest test setup is prepared
      When storage move refuses non empty target is executed
      Then init_result.exit_code equals 0
      Then result.exit_code does not equal 0

    @req-REQ-0056 @ac-AC-0614
    Example: Sync Preflight Is Read Only And Warns About Active Locks
      Given the pytest test setup is prepared
      When sync preflight is read only and warns about active locks is executed
      Then result.exit_code equals 0
      Then before equals after
      Then any succeeds

    @req-REQ-0056 @ac-AC-0615
    Example: Sync Preflight Warns When In Repo Storage Is Tracked
      Given the pytest test setup is prepared
      When sync preflight warns when in repo storage is tracked is executed
      Then result.exit_code equals 0
      Then any succeeds

    @req-REQ-0056 @ac-AC-0616
    Example: Sync Status Reports Git Changes For External State Repo
      Given the pytest test setup is prepared
      When sync status reports git changes for external state repo is executed
      Then result.exit_code equals 0

    @req-REQ-0056 @ac-AC-0611
    Example: Sync Commit Commits External State Repo
      Given the pytest test setup is prepared
      When sync commit commits external state repo is executed
      Then result.exit_code equals 0

    @req-REQ-0056 @ac-AC-0613
    Example: Sync Help Includes Aliases And Git Group
      Given the pytest test setup is prepared
      When sync help includes aliases and git group is executed
      Then result.exit_code equals 0
      Then 'preflight' is in result.stdout
      Then 'status' is in result.stdout
      Then 'commit' is in result.stdout
      Then 'export' is in result.stdout
      Then 'import' is in result.stdout
      Then 'git' is in result.stdout

    @req-REQ-0056 @ac-AC-0612
    Example: Sync Export Alias Writes Archive
      Given the pytest test setup is prepared
      When sync export alias writes archive is executed
      Then root_result.exit_code equals 0
      Then sync_result.exit_code equals 0
      Then root_archive.exists succeeds
      Then sync_archive.exists succeeds

    @req-REQ-0056 @ac-AC-0607
    Example: Export Conflicting Output Args Include Command Specific Hint
      Given the pytest test setup is prepared
      When export conflicting output args include command specific hint is executed
      Then root_result.exit_code equals 2
      Then sync_result.exit_code equals 2
