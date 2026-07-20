@area-actor_harness_state @feature-actor-harness-state @generated
Feature: Actor Harness State

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-actor-harness-state
  Rule: Actor Harness State

    @req-REQ-0002 @ac-AC-0036
    Example: Save And Load Actor State
      Given the pytest test setup is prepared
      When save and load actor state is executed
      Then loaded is not None
      Then loaded.actor_type equals 'agent'
      Then loaded.actor_name equals 'test-agent'
      Then loaded.role equals 'implementer'
      Then loaded.tool equals 'test-tool'
      Then loaded.session_id equals 'sess-1'

    @req-REQ-0002 @ac-AC-0011
    Example: Clear Actor State
      Given the pytest test setup is prepared
      When clear actor state is executed
      Then cleared is not None
      Then cleared.actor_name equals 'bob'

    @req-REQ-0002 @ac-AC-0037
    Example: Save And Load Harness State
      Given the pytest test setup is prepared
      When save and load harness state is executed
      Then loaded is not None
      Then loaded.name equals 'test-harness'
      Then loaded.kind equals 'agent_harness'
      Then loaded.session_id equals 'sess-2'

    @req-REQ-0002 @ac-AC-0012
    Example: Clear Harness State
      Given the pytest test setup is prepared
      When clear harness state is executed
      Then cleared is not None
      Then cleared.name equals 'my-harness'

    @req-REQ-0002 @ac-AC-0010
    Example: Actor State Yaml On Disk
      Given the pytest test setup is prepared
      When actor state yaml on disk is executed
      Then actor_path.exists succeeds

    @req-REQ-0002 @ac-AC-0025
    Example: Harness State Yaml On Disk
      Given the pytest test setup is prepared
      When harness state yaml on disk is executed
      Then harness_path.exists succeeds

    @req-REQ-0002 @ac-AC-0009
    Example: Actor State Roundtrip
      Given the pytest test setup is prepared
      When actor state roundtrip is executed
      Then loaded equals original

    @req-REQ-0002 @ac-AC-0024
    Example: Harness State Roundtrip
      Given the pytest test setup is prepared
      When harness state roundtrip is executed
      Then loaded equals original

    @req-REQ-0002 @ac-AC-0031
    Example: Resolve Actor Uses Stored When No Env Vars
      Given the pytest test setup is prepared
      When resolve actor uses stored when no env vars is executed
      Then actor.actor_name equals 'stored-user'
      Then actor.role equals 'reviewer'

    @req-REQ-0002 @ac-AC-0029
    Example: Resolve Actor Env Overrides Stored
      Given the pytest test setup is prepared
      When resolve actor env overrides stored is executed
      Then actor.actor_name equals 'env-actor'
      Then actor.actor_type equals 'system'

    @req-REQ-0002 @ac-AC-0030
    Example: Resolve Actor Explicit Overrides All
      Given the pytest test setup is prepared
      When resolve actor explicit overrides all is executed
      Then actor.actor_name equals 'explicit'
      Then actor.actor_type equals 'agent'

    @req-REQ-0002 @ac-AC-0035
    Example: Resolve Harness Uses Stored When No Env Vars
      Given the pytest test setup is prepared
      When resolve harness uses stored when no env vars is executed
      Then harness.name equals 'stored-harness'
      Then harness.kind equals 'ci'

    @req-REQ-0002 @ac-AC-0033
    Example: Resolve Harness Env Overrides Stored
      Given the pytest test setup is prepared
      When resolve harness env overrides stored is executed
      Then harness.name equals 'env-harness'

    @req-REQ-0002 @ac-AC-0034
    Example: Resolve Harness Explicit Overrides All
      Given the pytest test setup is prepared
      When resolve harness explicit overrides all is executed
      Then harness.name equals 'explicit'

    @req-REQ-0002 @ac-AC-0028
    Example: Resolve Actor After Clear
      Given the pytest test setup is prepared
      When resolve actor after clear is executed
      Then actor.actor_name does not equal 'to-clear'

    @req-REQ-0002 @ac-AC-0032
    Example: Resolve Harness After Clear
      Given the pytest test setup is prepared
      When resolve harness after clear is executed
      Then harness.name does not equal 'to-clear'

    @req-REQ-0002 @ac-AC-0016
    Example: Cli Actor Set
      Given the pytest test setup is prepared
      When cli actor set is executed
      Then result.exit_code equals 0
      Then 'Actor set: agent:cli-agent' is in result.output
      Then 'Role: implementer' is in result.output
      Then state is not None
      Then state.actor_name equals 'cli-agent'

    @req-REQ-0002 @ac-AC-0017
    Example: Cli Actor Set Json
      Given the pytest test setup is prepared
      When cli actor set json is executed
      Then result.exit_code equals 0
      Then '"actor_set"' is in result.output
      Then '"json-user"' is in result.output

    @req-REQ-0002 @ac-AC-0013
    Example: Cli Actor Clear
      Given the pytest test setup is prepared
      When cli actor clear is executed
      Then result.exit_code equals 0
      Then 'Actor cleared.' is in result.output

    @req-REQ-0002 @ac-AC-0014
    Example: Cli Actor Clear Empty
      Given the pytest test setup is prepared
      When cli actor clear empty is executed
      Then result.exit_code equals 0
      Then 'No stored actor to clear.' is in result.output

    @req-REQ-0002 @ac-AC-0015
    Example: Cli Actor Clear Json
      Given the pytest test setup is prepared
      When cli actor clear json is executed
      Then result.exit_code equals 0
      Then '"actor_clear"' is in result.output

    @req-REQ-0002 @ac-AC-0020
    Example: Cli Harness Set
      Given the pytest test setup is prepared
      When cli harness set is executed
      Then result.exit_code equals 0
      Then 'Harness set: cli-harness (agent_harness)' is in result.output
      Then state is not None
      Then state.name equals 'cli-harness'

    @req-REQ-0002 @ac-AC-0021
    Example: Cli Harness Set Json
      Given the pytest test setup is prepared
      When cli harness set json is executed
      Then result.exit_code equals 0
      Then '"harness_set"' is in result.output
      Then '"json-harness"' is in result.output

    @req-REQ-0002 @ac-AC-0018
    Example: Cli Harness Clear
      Given the pytest test setup is prepared
      When cli harness clear is executed
      Then result.exit_code equals 0
      Then 'Harness cleared.' is in result.output

    @req-REQ-0002 @ac-AC-0019
    Example: Cli Harness Clear Empty
      Given the pytest test setup is prepared
      When cli harness clear empty is executed
      Then result.exit_code equals 0
      Then 'No stored harness to clear.' is in result.output

    @req-REQ-0002 @ac-AC-0023
    Example: Cli Whoami Uses Stored
      Given the pytest test setup is prepared
      When cli whoami uses stored is executed
      Then result.exit_code equals 0
      Then 'stored-whoami' is in result.output
      Then 'stored-harness-whoami' is in result.output

    @req-REQ-0002 @ac-AC-0022
    Example: Cli Whoami Json Uses Stored
      Given the pytest test setup is prepared
      When cli whoami json uses stored is executed
      Then result.exit_code equals 0
      Then '"json-whoami"' is in result.output

    @req-REQ-0002 @ac-AC-0026
    Example: Missing actor and harness state loads empty
      Given no actor or harness state has been stored
      When Taskledger loads active actor and harness state
      Then both state lookups return no stored value

    @req-REQ-0002 @ac-AC-0027
    Example: Actor resolution without workspace state uses defaults
      Given no workspace and no stored actor state are available
      When Taskledger resolves the active actor
      Then a default actor identity is returned
