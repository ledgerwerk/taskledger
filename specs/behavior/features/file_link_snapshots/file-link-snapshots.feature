@area-file_link_snapshots @feature-file-link-snapshots @generated
Feature: File Link Snapshots

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-file-link-snapshots
  Rule: File Link Snapshots

    @req-REQ-0021 @ac-AC-0289
    Example: Existing Links Load Without Baseline Fields
      Given the pytest test setup is prepared
      When existing links load without baseline fields is executed
      Then link.baseline_hash is None
      Then link.baseline_size is None
      Then link.baseline_mtime is None
      Then link.baseline_exists is None

    @req-REQ-0021 @ac-AC-0292
    Example: New Links Record Baseline Fields
      Given the pytest test setup is prepared
      When new links record baseline fields is executed
      Then result.exit_code equals 0
      Then link.baseline_exists is True
      Then link.target_type equals 'file'

    @req-REQ-0021 @ac-AC-0285
    Example: Binary Files Hash Without Decoding Errors
      Given the pytest test setup is prepared
      When binary files hash without decoding errors is executed
      Then result.exit_code equals 0

    @req-REQ-0021 @ac-AC-0290
    Example: Modified File Status
      Given the pytest test setup is prepared
      When modified file status is executed
      Then result.exit_code equals 0

    @req-REQ-0021 @ac-AC-0286
    Example: Deleted File Status
      Given the pytest test setup is prepared
      When deleted file status is executed
      Then result.exit_code equals 0

    @req-REQ-0021 @ac-AC-0291
    Example: New File Status From Missing Baseline
      Given the pytest test setup is prepared
      When new file status from missing baseline is executed
      Then result.exit_code equals 0

    @req-REQ-0021 @ac-AC-0287
    Example: Directory Status Is Unchanged Without Recursive Hashing
      Given the pytest test setup is prepared
      When directory status is unchanged without recursive hashing is executed
      Then result.exit_code equals 0

    @req-REQ-0021 @ac-AC-0293
    Example: Refresh Rebaselines Modified File
      Given the pytest test setup is prepared
      When refresh rebaselines modified file is executed
      Then refreshed.exit_code equals 0

    @req-REQ-0021 @ac-AC-0288
    Example: Existing Link Baseline Is Preserved Without Explicit Snapshot
      Given the pytest test setup is prepared
      When existing link baseline is preserved without explicit snapshot is executed
      Then preserve.exit_code equals 0
      Then refresh.exit_code equals 0
