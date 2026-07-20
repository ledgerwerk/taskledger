@area-actor_resolution @feature-actor-resolution @generated
Feature: Actor Resolution

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-actor-resolution
  Rule: Actor Resolution

    @req-REQ-0003 @ac-AC-0049
    Example: Round Trip Command Pid And Pid Scope
      Given the pytest test setup is prepared
      When round trip command pid and pid scope is executed
      Then b.pid is None
      Then b.command_pid equals 123
      Then b.pid_scope equals 'unverifiable_harness'

    @req-REQ-0003 @ac-AC-0050
    Example: Round Trip Owner Pid Scope
      Given the pytest test setup is prepared
      When round trip owner pid scope is executed
      Then b.pid equals 99999
      Then b.command_pid equals 123
      Then b.pid_scope equals 'owner'

    @req-REQ-0003 @ac-AC-0044
    Example: Missing Pid Scope Is None
      Given the pytest test setup is prepared
      When missing pid scope is none is executed
      Then b.pid equals 123
      Then b.pid_scope is None
      Then b.command_pid is None

    @req-REQ-0003 @ac-AC-0043
    Example: Invalid Pid Scope Is Ignored
      Given the pytest test setup is prepared
      When invalid pid scope is ignored is executed
      Then b.pid_scope is None

    @req-REQ-0003 @ac-AC-0048
    Example: Pi Context Without Owner Pid Stores None Pid
      Given the pytest test setup is prepared
      When pi context without owner pid stores none pid is executed
      Then actor.actor_name equals 'pi'
      Then actor.tool equals 'pi'
      Then actor.session_id equals 'pi-session-1'
      Then actor.pid is None
      Then actor.pid_scope equals 'unverifiable_harness'

    @req-REQ-0003 @ac-AC-0047
    Example: Pi Context With Owner Pid Env
      Given the pytest test setup is prepared
      When pi context with owner pid env is executed
      Then actor.pid equals 12345
      Then actor.pid_scope equals 'owner'

    @req-REQ-0003 @ac-AC-0041
    Example: Harness Pid Alias Env
      Given the pytest test setup is prepared
      When harness pid alias env is executed
      Then actor.pid equals 54321
      Then actor.pid_scope equals 'owner'

    @req-REQ-0003 @ac-AC-0046
    Example: Owner Pid Takes Priority Over Harness Pid
      Given the pytest test setup is prepared
      When owner pid takes priority over harness pid is executed
      Then actor.pid equals 111

    @req-REQ-0003 @ac-AC-0038
    Example: Codex Context Without Owner Pid
      Given the pytest test setup is prepared
      When codex context without owner pid is executed
      Then actor.actor_name equals 'codex'
      Then actor.tool equals 'codex'
      Then actor.pid is None
      Then actor.pid_scope equals 'unverifiable_harness'

    @req-REQ-0003 @ac-AC-0045
    Example: Opencode Context Without Owner Pid
      Given the pytest test setup is prepared
      When opencode context without owner pid is executed
      Then actor.actor_name equals 'opencode'
      Then actor.pid is None
      Then actor.pid_scope equals 'unverifiable_harness'

    @req-REQ-0003 @ac-AC-0040
    Example: Env Actor With Harness Session
      Given the pytest test setup is prepared
      When env actor with harness session is executed
      Then actor.actor_name equals 'my-agent'
      Then actor.pid is None
      Then actor.pid_scope equals 'unverifiable_harness'

    @req-REQ-0003 @ac-AC-0039
    Example: Default Agent Gets Command Pid As Owner
      Given the pytest test setup is prepared
      When default agent gets command pid as owner is executed
      Then actor.pid_scope equals 'owner'

    @req-REQ-0003 @ac-AC-0042
    Example: Invalid Owner Pid Ignored
      Given the pytest test setup is prepared
      When invalid owner pid ignored is executed
      Then actor.pid is None
      Then actor.pid_scope equals 'unverifiable_harness'

    @req-REQ-0003 @ac-AC-0051
    Example: Zero Owner Pid Ignored
      Given the pytest test setup is prepared
      When zero owner pid ignored is executed
      Then actor.pid is None
      Then actor.pid_scope equals 'unverifiable_harness'
