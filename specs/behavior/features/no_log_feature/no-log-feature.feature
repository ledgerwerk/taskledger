@area-no_log_feature @feature-no-log-feature @generated
Feature: No Log Feature

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-no-log-feature
  Rule: No Log Feature

    @req-REQ-0035 @ac-AC-0385
    Example: Env Var 1
      Given the pytest test setup is prepared
      When env var 1 is executed
      Then _env_no_log succeeds

    @req-REQ-0035 @ac-AC-0389
    Example: Env Var True
      Given the pytest test setup is prepared
      When env var true is executed
      Then _env_no_log succeeds

    @req-REQ-0035 @ac-AC-0390
    Example: Env Var Yes
      Given the pytest test setup is prepared
      When env var yes is executed
      Then _env_no_log succeeds

    @req-REQ-0035 @ac-AC-0387
    Example: Env Var On
      Given the pytest test setup is prepared
      When env var on is executed
      Then _env_no_log succeeds

    @req-REQ-0035 @ac-AC-0386
    Example: Env Var Case Insensitive
      Given the pytest test setup is prepared
      When env var case insensitive is executed
      Then _env_no_log succeeds

    @req-REQ-0035 @ac-AC-0400
    Example: Skip When No Log Flag Set
      Given the pytest test setup is prepared
      When skip when no log flag set is executed
      Then _should_skip_cli_recording succeeds

    @req-REQ-0035 @ac-AC-0399
    Example: Skip When Env Var Set
      Given the pytest test setup is prepared
      When skip when env var set is executed
      Then _should_skip_cli_recording succeeds

    @req-REQ-0035 @ac-AC-0398
    Example: Skip When Disabled
      Given the pytest test setup is prepared
      When skip when disabled is executed
      Then _should_skip_cli_recording succeeds

    @req-REQ-0035 @ac-AC-0397
    Example: Skip When Cli Capture Disabled
      Given the pytest test setup is prepared
      When skip when cli capture disabled is executed
      Then _should_skip_cli_recording succeeds

    @req-REQ-0035 @ac-AC-0395
    Example: Skip Human Oriented When Capture Disabled
      Given the pytest test setup is prepared
      When skip human oriented when capture disabled is executed
      Then _should_skip_cli_recording succeeds

    @req-REQ-0035 @ac-AC-0396
    Example: Skip Safe Read Only When Capture Disabled
      Given the pytest test setup is prepared
      When skip safe read only when capture disabled is executed
      Then _should_skip_cli_recording succeeds

    @req-REQ-0035 @ac-AC-0394
    Example: Precedence No Log Overrides Config
      Given the pytest test setup is prepared
      When precedence no log overrides config is executed
      Then _should_skip_cli_recording succeeds

    @req-REQ-0035 @ac-AC-0391
    Example: No Log Flag Suppresses Logging
      Given the pytest test setup is prepared
      When no log flag suppresses logging is executed
      Then result.exit_code equals 0
      Then log_count equals 0

    @req-REQ-0035 @ac-AC-0393
    Example: Normal Command Still Logs
      Given the pytest test setup is prepared
      When normal command still logs is executed
      Then result.exit_code equals 0
      Then log_count equals 1

    @req-REQ-0035 @ac-AC-0388
    Example: Env Var Suppresses Logging
      Given the pytest test setup is prepared
      When env var suppresses logging is executed
      Then result.exit_code equals 0
      Then log_count equals 0

    @req-REQ-0035 @ac-AC-0392
    Example: No Log Mutation Still Executes
      Given the pytest test setup is prepared
      When no log mutation still executes is executed
      Then result.exit_code equals 0
      Then logs_after_creation equals initial_logs
      Then result.exit_code equals 0
      Then 'test-task' is in result.stdout

    @req-REQ-0035 @ac-AC-0378
    Example: Capture Safe Read Only False Skips View
      Given the pytest test setup is prepared
      When capture safe read only false skips view is executed
      Then result.exit_code equals 0
      Then logs_after_status equals initial_logs

    @req-REQ-0035 @ac-AC-0379
    Example: Capture Safe Read Only False Still Logs Mutations
      Given the pytest test setup is prepared
      When capture safe read only false still logs mutations is executed
      Then result.exit_code equals 0
      Then final_logs is greater than initial_logs

    @req-REQ-0035 @ac-AC-0377
    Example: Capture Human Oriented False Skips Report
      Given the pytest test setup is prepared
      When capture human oriented false skips report is executed
      Then result.exit_code equals 0
      Then logs_after_commands equals initial_logs

    @req-REQ-0035 @ac-AC-0384
    Example: Commands List All
      Given the pytest test setup is prepared
      When commands list all is executed
      Then result.exit_code equals 0
      Then 'view' is in result.stdout
      Then 'task create' is in result.stdout
      Then 'stable_for_agents' is in result.stdout
      Then 'safe_read_only' is in result.stdout

    @req-REQ-0035 @ac-AC-0380
    Example: Commands Filter By Audience
      Given the pytest test setup is prepared
      When commands filter by audience is executed
      Then result.exit_code equals 0
      Then 'task report' is in result.stdout
      Then 'view' is not in result.stdout

    @req-REQ-0035 @ac-AC-0381
    Example: Commands Filter By Effect
      Given the pytest test setup is prepared
      When commands filter by effect is executed
      Then result.exit_code equals 0
      Then 'view' is in result.stdout
      Then 'task create' is not in result.stdout

    @req-REQ-0035 @ac-AC-0382
    Example: Commands Json Output
      Given the pytest test setup is prepared
      When commands json output is executed
      Then result.exit_code equals 0
      Then 'commands' is in result_data

    @req-REQ-0035 @ac-AC-0383
    Example: Commands Json With Filters
      Given the pytest test setup is prepared
      When commands json with filters is executed
      Then result.exit_code equals 0
