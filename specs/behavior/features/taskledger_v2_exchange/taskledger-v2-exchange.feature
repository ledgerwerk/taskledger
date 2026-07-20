@area-taskledger_v2_exchange @feature-taskledger-v2-exchange @generated
Feature: Taskledger V2 Exchange

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-taskledger-v2-exchange
  Rule: Taskledger V2 Exchange

    @req-REQ-0065 @ac-AC-0730
    Example: Export And Import Include V2 State
      Given the pytest test setup is prepared
      When export and import include v2 state is executed
      Then export_result.exit_code equals 0
      Then archive_path.exists succeeds
      Then import_result.exit_code equals 0

    @req-REQ-0065 @ac-AC-0733
    Example: Export Import Roundtrip Preserves Code Reviews
      Given the pytest test setup is prepared
      When export import roundtrip preserves code reviews is executed
      Then export_result.exit_code equals 0
      Then import_result.exit_code equals 0

    @req-REQ-0065 @ac-AC-0727
    Example: Default Export Filename Includes Project Slug And Ledger
      Given the pytest test setup is prepared
      When default export filename includes project slug and ledger is executed
      Then init_result.exit_code equals 0
      Then archive_path.parent equals workspace
      Then filename.startswith succeeds
      Then filename.endswith succeeds

    @req-REQ-0065 @ac-AC-0728
    Example: Default Export Filename Sanitizes Project Name
      Given the pytest test setup is prepared
      When default export filename sanitizes project name is executed
      Then init_result.exit_code equals 0
      Then archive_path.parent equals workspace
      Then filename.startswith succeeds

    @req-REQ-0065 @ac-AC-0734
    Example: Export Positional Task Ref Exports Task Archive
      Given the pytest test setup is prepared
      When export positional task ref exports task archive is executed
      Then archive_path.parent equals workspace
      Then archive_path.name.startswith succeeds

    @req-REQ-0065 @ac-AC-0725
    Example: Archive Manifest Includes Project Name Slug And Uuid
      Given the pytest test setup is prepared
      When archive manifest includes project name slug and uuid is executed
      Then init_result.exit_code equals 0
      Then export_result.exit_code equals 0

    @req-REQ-0065 @ac-AC-0724
    Example: Archive Import Dry Run Reports Project Name
      Given the pytest test setup is prepared
      When archive import dry run reports project name is executed
      Then export_result.exit_code equals 0

    @req-REQ-0065 @ac-AC-0731
    Example: Export Import Preserves Agent Command Logs
      Given the pytest test setup is prepared
      When export import preserves agent command logs is executed
      Then source_logs is truthy
      Then export_result.exit_code equals 0
      Then import_result.exit_code equals 0
      Then dest_logs is truthy
      Then any succeeds

    @req-REQ-0065 @ac-AC-0729
    Example: Export And Import Include Release Records
      Given the pytest test setup is prepared
      When export and import include release records is executed
      Then export_result.exit_code equals 0
      Then import_result.exit_code equals 0

    @req-REQ-0065 @ac-AC-0741
    Example: Import Replace Quarantines Lock And Allows Resume
      Given the pytest test setup is prepared
      When import replace quarantines lock and allows resume is executed
      Then export_result.exit_code equals 0
      Then import_result.exit_code equals 0
      Then imported_lock_audits is truthy

    @req-REQ-0065 @ac-AC-0740
    Example: Import Replace Lock Policy Keep Restores Lock
      Given the pytest test setup is prepared
      When import replace lock policy keep restores lock is executed
      Then export_result.exit_code equals 0
      Then import_result.exit_code equals 0
      Then _task_lock_paths succeeds

    @req-REQ-0065 @ac-AC-0738
    Example: Import Archive Rejects Different Project Uuid Without Mutation
      Given the pytest test setup is prepared
      When import archive rejects different project uuid without mutation is executed
      Then export_result.exit_code equals 0
      Then import_result.exit_code does not equal 0
      Then 'Project UUID mismatch' is in import_result.output
      Then dest_task_result.exit_code equals 0

    @req-REQ-0065 @ac-AC-0743
    Example: Import Single Task Preserves Id When Free
      Given the pytest test setup is prepared
      When import single task preserves id when free is executed
      Then show.exit_code equals 0

    @req-REQ-0065 @ac-AC-0742
    Example: Import Single Task Id Policy Fail On Conflict
      Given the pytest test setup is prepared
      When import single task id policy fail on conflict is executed
      Then import_result.exit_code does not equal 0

    @req-REQ-0065 @ac-AC-0732
    Example: Export Import Preserves Archived Task Metadata And Slug Reuse
      Given the pytest test setup is prepared
      When export import preserves archived task metadata and slug reuse is executed
      Then record.exit_code equals 0
      Then archive.exit_code equals 0
      Then export_result.exit_code equals 0
      Then import_result.exit_code equals 0
      Then visible.exit_code equals 0
      Then 'legacy-archive' is not in visible.output
      Then archived.exit_code equals 0
      Then 'legacy-archive' is in archived.output

    @req-REQ-0065 @ac-AC-0745
    Example: Old Archive Without Project Name Still Imports
      Given the pytest test setup is prepared
      When old archive without project name still imports is executed
      Then export_result.exit_code equals 0
      Then import_result.exit_code equals 0

    @req-REQ-0065 @ac-AC-0736
    Example: Export Without Bodies Omits Plan And Task Body
      Given the pytest test setup is prepared
      When export without bodies omits plan and task body is executed
      Then export_result.exit_code equals 0

    @req-REQ-0065 @ac-AC-0735
    Example: Export With Run Artifacts Includes Artifact Members
      Given the pytest test setup is prepared
      When export with run artifacts includes artifact members is executed
      Then export_result.exit_code equals 0
      Then 'artifacts/tasks/task-0001/artifacts/run.log' is in names
      Then import_result.exit_code equals 0

    @req-REQ-0065 @ac-AC-0744
    Example: Single-task import renumbers conflicts without overwriting
      Given an imported task ID already exists in the target ledger
      When the task archive is imported with automatic ID handling
      Then the imported task receives a free task ID
      And the existing task is not overwritten

    @req-REQ-0065 @ac-AC-0739
    Example: Import dry run reports changes without mutating state
      Given an archive can be imported into the current project
      When import is run in dry-run mode
      Then the proposed ID mapping is reported
      And project state remains unchanged

    @req-REQ-0065 @ac-AC-0726
    Example: Archive resource limits are enforced
      Given a project archive exceeds member or payload size limits
      When Taskledger reads the archive
      Then the archive is rejected before import

    @req-REQ-0065 @ac-AC-0748
    Example: Unsafe artifact member paths are rejected
      Given an archive artifact member escapes its expected directory
      When Taskledger imports the archive
      Then the archive is rejected without writing the unsafe path

    @req-REQ-0065 @ac-AC-0737
    Example: Single-task import advances the ledger task counter
      Given an imported task uses a task number beyond the current ledger counter
      When the task archive is imported
      Then the ledger counter advances beyond the imported task number

    @req-REQ-0065 @ac-AC-0746
    Example: Artifacts follow a task that is renumbered during import
      Given an imported task conflicts with an existing task and has artifacts
      When the imported task receives a new task ID
      Then its artifacts are stored under the new task ID

    @req-REQ-0065 @ac-AC-0747
    Example: Single-task import preserves the current active task
      Given the destination ledger already has an active task
      When another task is imported from an archive
      Then the destination active task is unchanged
