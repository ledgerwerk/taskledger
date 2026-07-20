@area-lock_diagnostics @feature-lock-diagnostics @generated
Feature: Lock Diagnostics

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-lock-diagnostics
  Rule: Lock Diagnostics

    @req-REQ-0030 @ac-AC-0346
    Example: Diagnose Lock None Returns None Classification
      Given the pytest test setup is prepared
      When diagnose lock none returns none classification is executed
      Then diag.classification equals CLASSIFICATION_NONE
      Then diag.active is False
      Then diag.expired is False
      Then diag.holder is None

    @req-REQ-0030 @ac-AC-0339
    Example: Diagnose Expired Impl Recommends Repair Flag
      Given the pytest test setup is prepared
      When diagnose expired impl recommends repair flag is executed
      Then diag.classification equals CLASSIFICATION_EXPIRED
      Then diag.expired is True
      Then diag.active is True
      Then diag.seconds_until_expiry is not None
      Then diag.seconds_until_expiry is less than 0

    @req-REQ-0030 @ac-AC-0340
    Example: Diagnose Lock Expired Planning Recommends Repair Lock
      Given the pytest test setup is prepared
      When diagnose lock expired planning recommends repair lock is executed
      Then diag.classification equals CLASSIFICATION_EXPIRED

    @req-REQ-0030 @ac-AC-0341
    Example: Diagnose Lock Local Dead Pid Classifies Dead Local Process
      Given the pytest test setup is prepared
      When diagnose lock local dead pid classifies dead local process is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS
      Then diag.holder_pid_check equals PID_CHECK_DEAD
      Then diag.expired is False
      Then diag.holder_pid equals 512425
      Then diag.holder_host equals HOST_LOCAL
      Then 'is no longer running' is in diag.summary
      Then any succeeds
      Then any succeeds
      Then any succeeds

    @req-REQ-0030 @ac-AC-0342
    Example: Diagnose Lock Local Dead Pid For Planning Only Recommends Repair
      Given the pytest test setup is prepared
      When diagnose lock local dead pid for planning only recommends repair is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS
      Then all succeeds

    @req-REQ-0030 @ac-AC-0343
    Example: Diagnose Lock Local Live Pid Other Actor Classifies Other Actor
      Given the pytest test setup is prepared
      When diagnose lock local live pid other actor classifies other actor is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_OTHER_ACTOR
      Then diag.holder_pid_check equals PID_CHECK_ALIVE
      Then all succeeds

    @req-REQ-0030 @ac-AC-0344
    Example: Diagnose Lock Local Live Pid Same Actor Classifies Same Actor
      Given the pytest test setup is prepared
      When diagnose lock local live pid same actor classifies same actor is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_SAME_ACTOR
      Then diag.holder_pid_check equals PID_CHECK_ALIVE

    @req-REQ-0030 @ac-AC-0347
    Example: Diagnose Lock Remote Host Is Unverifiable
      Given the pytest test setup is prepared
      When diagnose lock remote host is unverifiable is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS
      Then all succeeds
      Then any succeeds

    @req-REQ-0030 @ac-AC-0345
    Example: Diagnose Lock No Pid Local Host Classifies No Pid
      Given the pytest test setup is prepared
      When diagnose lock no pid local host classifies no pid is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_NO_PID
      Then diag.holder_pid_check equals 'n/a'
      Then all succeeds

    @req-REQ-0030 @ac-AC-0348
    Example: Diagnose Lock Same Actor Without Pid Still Classifies Same Actor
      Given the pytest test setup is prepared
      When diagnose lock same actor without pid still classifies same actor is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_SAME_ACTOR

    @req-REQ-0030 @ac-AC-0349
    Example: Diagnose Lock Unknown Pid Check Stays Unverifiable
      Given the pytest test setup is prepared
      When diagnose lock unknown pid check stays unverifiable is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS
      Then diag.holder_pid_check equals PID_CHECK_UNKNOWN
      Then all succeeds

    @req-REQ-0030 @ac-AC-0351
    Example: Diagnostics To Dict Round Trips Through Payload Reconstruction
      Given the pytest test setup is prepared
      When diagnostics to dict round trips through payload reconstruction is executed
      Then rebuilt is not None
      Then rebuilt.classification equals CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS
      Then rebuilt.remediation equals diag.remediation
      Then rebuilt.summary equals diag.summary

    @req-REQ-0030 @ac-AC-0350
    Example: Diagnose Lock Uses Task Id In Remediation When Provided
      Given the pytest test setup is prepared
      When diagnose lock uses task id in remediation when provided is executed
      Then all succeeds

    @req-REQ-0030 @ac-AC-0357
    Example: Pi Harness Without Owner Pid Is Not Dead Local Process
      Given the pytest test setup is prepared
      When pi harness without owner pid is not dead local process is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_HARNESS_SESSION
      Then all succeeds

    @req-REQ-0030 @ac-AC-0353
    Example: Harness Owner Pid Dead Still Repairs
      Given the pytest test setup is prepared
      When harness owner pid dead still repairs is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS
      Then any succeeds

    @req-REQ-0030 @ac-AC-0356
    Example: Legacy Pi Lock With Session Inferred As Unverifiable
      Given the pytest test setup is prepared
      When legacy pi lock with session inferred as unverifiable is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_HARNESS_SESSION
      Then all succeeds

    @req-REQ-0030 @ac-AC-0355
    Example: Legacy Pi Lock With Harness Ref Inferred As Unverifiable
      Given the pytest test setup is prepared
      When legacy pi lock with harness ref inferred as unverifiable is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_HARNESS_SESSION
      Then all succeeds

    @req-REQ-0030 @ac-AC-0338
    Example: Command Pid Scope Not Checkable
      Given the pytest test setup is prepared
      When command pid scope not checkable is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_HARNESS_SESSION
      Then all succeeds

    @req-REQ-0030 @ac-AC-0352
    Example: Direct User Dead Pid Still Repairs
      Given the pytest test setup is prepared
      When direct user dead pid still repairs is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS
      Then any succeeds

    @req-REQ-0030 @ac-AC-0354
    Example: Harness Session Same Actor Classification
      Given the pytest test setup is prepared
      When harness session same actor classification is executed
      Then diag.classification equals CLASSIFICATION_ACTIVE_SAME_ACTOR
