@area-storage_init @feature-storage-init @generated
Feature: Storage Init

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-storage-init
  Rule: Storage Init

    @req-REQ-0053 @ac-AC-0560
    Example: Init Project State Creates Structure
      Given the pytest test setup is prepared
      When init project state creates structure is executed
      Then paths.project_dir.exists succeeds
      Then paths.config_path.exists succeeds
      Then paths.repo_index_path.exists succeeds

    @req-REQ-0053 @ac-AC-0558
    Example: Ensure Project Exists After Init
      Given the pytest test setup is prepared
      When ensure project exists after init is executed
      Then paths.workspace_root equals tmp_path

    @req-REQ-0053 @ac-AC-0559
    Example: Init Creates Expected Directories
      Given the pytest test setup is prepared
      When init creates expected directories is executed
      Then paths.releases_dir.is_dir succeeds
