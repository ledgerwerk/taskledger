@area-doctor @feature-doctor @generated
Feature: Doctor

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-doctor
  Rule: Doctor

    @req-REQ-0017 @ac-AC-0198
    Example: Inspect Project Reports Malformed Handoff Record
      Given the pytest test setup is prepared
      When inspect project reports malformed handoff record is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0199
    Example: Inspect Project Warns For Unsupported Legacy Sidecar
      Given the pytest test setup is prepared
      When inspect project warns for unsupported legacy sidecar is executed
      Then any succeeds
      Then any succeeds

    @req-REQ-0017 @ac-AC-0197
    Example: Inspect Project Active Task Missing
      Given the pytest test setup is prepared
      When inspect project active task missing is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0196
    Example: Inspect Project Active Task Done Warns
      Given the pytest test setup is prepared
      When inspect project active task done warns is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0184
    Example: Inspect Broken Introduction Ref
      Given the pytest test setup is prepared
      When inspect broken introduction ref is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0185
    Example: Inspect Broken Requirement Ref
      Given the pytest test setup is prepared
      When inspect broken requirement ref is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0182
    Example: Inspect Accepted Plan Version Missing
      Given the pytest test setup is prepared
      When inspect accepted plan version missing is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0194
    Example: Inspect Multiple Accepted Plans
      Given the pytest test setup is prepared
      When inspect multiple accepted plans is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0183
    Example: Inspect Accepted Plan Version Points To Wrong Plan
      Given the pytest test setup is prepared
      When inspect accepted plan version points to wrong plan is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0179
    Example: Doctor Warns For Worker Refs Without Enabled Pipeline
      Given the pytest test setup is prepared
      When doctor warns for worker refs without enabled pipeline is executed
      Then any succeeds
      Then any succeeds

    @req-REQ-0017 @ac-AC-0178
    Example: Doctor Warns For Worker Refs Missing From Pipeline
      Given the pytest test setup is prepared
      When doctor warns for worker refs missing from pipeline is executed
      Then any succeeds
      Then any succeeds

    @req-REQ-0017 @ac-AC-0201
    Example: Inspect Transient Stage In Status
      Given the pytest test setup is prepared
      When inspect transient stage in status is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0195
    Example: Inspect Multiple Running Runs
      Given the pytest test setup is prepared
      When inspect multiple running runs is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0200
    Example: Inspect Running Run Without Matching Lock
      Given the pytest test setup is prepared
      When inspect running run without matching lock is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0175
    Example: Doctor Reports Missing Lock For Running Implementation With Recovery Hint
      Given the pytest test setup is prepared
      When doctor reports missing lock for running implementation with recovery hint is executed
      Then any succeeds
      Then any succeeds

    @req-REQ-0017 @ac-AC-0193
    Example: Inspect Lock Without Running Run
      Given the pytest test setup is prepared
      When inspect lock without running run is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0186
    Example: Inspect Change References Missing Run
      Given the pytest test setup is prepared
      When inspect change references missing run is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0187
    Example: Inspect Change References Non Implementation Run
      Given the pytest test setup is prepared
      When inspect change references non implementation run is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0202
    Example: Inspect Validation Run References Missing Impl
      Given the pytest test setup is prepared
      When inspect validation run references missing impl is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0203
    Example: Inspect Validation Run References Non Impl Run
      Given the pytest test setup is prepared
      When inspect validation run references non impl run is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0190
    Example: Inspect Lock References Missing Task
      Given the pytest test setup is prepared
      When inspect lock references missing task is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0191
    Example: Inspect Lock References Non Running Run
      Given the pytest test setup is prepared
      When inspect lock references non running run is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0192
    Example: Inspect Lock Stage Run Type Mismatch
      Given the pytest test setup is prepared
      When inspect lock stage run type mismatch is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0188
    Example: Inspect Expired Lock
      Given the pytest test setup is prepared
      When inspect expired lock is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0189
    Example: Inspect Lock References Missing Run
      Given the pytest test setup is prepared
      When inspect lock references missing run is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0176
    Example: Doctor Warns About Empty Orphan Slug Dir
      Given the pytest test setup is prepared
      When doctor warns about empty orphan slug dir is executed
      Then any succeeds
      Then any succeeds

    @req-REQ-0017 @ac-AC-0177
    Example: Doctor Warns About Non Empty Legacy Sidecar
      Given the pytest test setup is prepared
      When doctor warns about non empty legacy sidecar is executed
      Then any succeeds

    @req-REQ-0017 @ac-AC-0181
    Example: A healthy project has no integrity findings
      Given an initialized project has consistent canonical state
      When Taskledger doctor inspects the project
      Then the project is reported healthy

    @req-REQ-0017 @ac-AC-0180
    Example: Duplicate todo IDs are reported
      Given a task contains duplicate todo identifiers
      When Taskledger doctor inspects the project
      Then the duplicate identifiers are reported as integrity errors

    @req-REQ-0017 @ac-AC-0204
    Example: Run and lock mismatches are reported
      Given an active run and lock identify different lifecycle operations
      When Taskledger doctor inspects locks
      Then the mismatch is reported with recovery guidance
