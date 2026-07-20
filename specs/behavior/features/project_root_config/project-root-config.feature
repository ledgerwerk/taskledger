@area-project_root_config @feature-project-root-config @generated
Feature: Project Root Config

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-project-root-config
  Rule: Project Root Config

    @req-REQ-0041 @ac-AC-0464
    Example: Init Writes Root Taskledger Toml And Default Storage
      Given the pytest test setup is prepared
      When init writes root taskledger toml and default storage is executed
      Then result.exit_code equals 0

    @req-REQ-0041 @ac-AC-0463
    Example: Init Writes Project Name From Workspace Basename
      Given the pytest test setup is prepared
      When init writes project name from workspace basename is executed
      Then result.exit_code equals 0
      Then 'project_name = "odoo17-addon"' is in config_text
      Then json_result.exit_code equals 0

    @req-REQ-0041 @ac-AC-0461
    Example: Init Project Name Option Overrides Basename
      Given the pytest test setup is prepared
      When init project name option overrides basename is executed
      Then result.exit_code equals 0
      Then 'project_name = "Odoo 17 Addons"' is in config_text

    @req-REQ-0041 @ac-AC-0462
    Example: Init With External Taskledger Dir Uses Directory Directly
      Given the pytest test setup is prepared
      When init with external taskledger dir uses directory directly is executed
      Then result.exit_code equals 0

    @req-REQ-0041 @ac-AC-0481
    Example: Task Create Uses Configured External Storage
      Given the pytest test setup is prepared
      When task create uses configured external storage is executed
      Then init_result.exit_code equals 0
      Then result.exit_code equals 0
      Then any succeeds

    @req-REQ-0041 @ac-AC-0478
    Example: Relative external storage resolves from the config directory
      Given taskledger.toml configures a relative taskledger directory
      When Taskledger resolves project storage
      Then the storage path is relative to the directory containing taskledger.toml

    @req-REQ-0041 @ac-AC-0455
    Example: Cli Discovers Taskledger Toml From Subdirectory
      Given the pytest test setup is prepared
      When cli discovers taskledger toml from subdirectory is executed
      Then result.exit_code equals 0

    @req-REQ-0041 @ac-AC-0469
    Example: Legacy project configuration remains readable as a fallback
      Given no root taskledger.toml exists
      When Taskledger resolves configuration from legacy project state
      Then legacy .taskledger and project.toml configuration can still be loaded

    @req-REQ-0041 @ac-AC-0468
    Example: Invalid Taskledger Toml Returns Json Error
      Given the pytest test setup is prepared
      When invalid taskledger toml returns json error is executed
      Then result.exit_code equals 1

    @req-REQ-0041 @ac-AC-0459
    Example: Dot Taskledger Toml Wins And Doctor Warns
      Given the pytest test setup is prepared
      When dot taskledger toml wins and doctor warns is executed
      Then any succeeds

    @req-REQ-0041 @ac-AC-0458
    Example: Doctor Warns On Legacy Project Toml
      Given the pytest test setup is prepared
      When doctor warns on legacy project toml is executed
      Then any succeeds

    @req-REQ-0041 @ac-AC-0477
    Example: Merge Project Config With Valid Prompt Profile
      Given the pytest test setup is prepared
      When merge project config with valid prompt profile is executed
      Then config.prompt_profile is not None
      Then p.name equals 'planning'
      Then p.profile equals 'strict'
      Then p.question_policy equals 'minimal'
      Then p.max_required_questions equals 3
      Then p.min_acceptance_criteria equals 2
      Then p.todo_granularity equals 'atomic'
      Then p.require_files is False
      Then p.require_test_commands is False
      Then p.require_expected_outputs is False
      Then p.require_validation_hints is False
      Then p.plan_body_detail equals 'terse'
      Then p.extra_guidance equals 'Always include a migration plan.'

    @req-REQ-0041 @ac-AC-0470
    Example: Merge Project Config No Prompt Profile Is None
      Given the pytest test setup is prepared
      When merge project config no prompt profile is none is executed
      Then config.prompt_profile is None

    @req-REQ-0041 @ac-AC-0471
    Example: Merge Project Config Partial Prompt Profile Uses Defaults
      Given the pytest test setup is prepared
      When merge project config partial prompt profile uses defaults is executed
      Then config.prompt_profile is not None
      Then p.profile equals 'compact'
      Then p.max_required_questions equals 2
      Then p.question_policy equals 'ask_when_missing'
      Then p.todo_granularity equals 'implementation_steps'
      Then p.require_files is True

    @req-REQ-0041 @ac-AC-0474
    Example: Merge Project Config Preserves Base Prompt Profile
      Given the pytest test setup is prepared
      When merge project config preserves base prompt profile is executed
      Then config.prompt_profile is None
      Then config.prompt_profile is not None
      Then config.prompt_profile.profile equals 'strict'
      Then config.prompt_profile.question_policy equals 'minimal'

    @req-REQ-0041 @ac-AC-0467
    Example: Invalid planning profile configuration is rejected
      Given a planning profile contains an unknown key or invalid typed value
      When Taskledger validates project configuration
      Then configuration loading fails with a validation error

    @req-REQ-0041 @ac-AC-0475
    Example: Merge Project Config With Agent Logging Override
      Given the pytest test setup is prepared
      When merge project config with agent logging override is executed
      Then config.agent_logging.enabled is True
      Then config.agent_logging.max_inline_chars equals 1234

    @req-REQ-0041 @ac-AC-0472
    Example: Merge Project Config Preserves Base Agent Logging
      Given the pytest test setup is prepared
      When merge project config preserves base agent logging is executed
      Then config.agent_logging.enabled is True
      Then config.agent_logging.max_inline_chars equals 2048

    @req-REQ-0041 @ac-AC-0457
    Example: Default Taskledger Toml Includes Commented Planning Guidance
      Given the pytest test setup is prepared
      When default taskledger toml includes commented planning guidance is executed
      Then '# [prompt_profiles.planning]' is in rendered
      Then '# profile = "balanced"' is in rendered
      Then '# require_files = true' is in rendered
      Then '# extra_guidance = "Mention docs and validation evidence in every plan."' is in rendered

    @req-REQ-0041 @ac-AC-0479
    Example: Render Default Taskledger Toml Includes Project Name When Given
      Given the pytest test setup is prepared
      When render default taskledger toml includes project name when given is executed
      Then 'project_name = "taskledger"' is in rendered

    @req-REQ-0041 @ac-AC-0466
    Example: Invalid project names are rejected
      Given a project name is blank, non-text, or contains a newline
      When Taskledger validates the project name
      Then configuration loading fails with a validation error

    @req-REQ-0041 @ac-AC-0480
    Example: Sync Git project paths cannot escape the workspace
      Given sync_git config uses an absolute path or parent traversal
      When Taskledger validates project configuration
      Then configuration loading fails with a validation error

    @req-REQ-0041 @ac-AC-0460
    Example: Event Logging Enabled By Default
      Given the pytest test setup is prepared
      When event logging enabled by default is executed
      Then config.event_logging.enabled is True

    @req-REQ-0041 @ac-AC-0476
    Example: Merge Project Config Can Disable Event Logging
      Given the pytest test setup is prepared
      When merge project config can disable event logging is executed
      Then config.event_logging.enabled is False

    @req-REQ-0041 @ac-AC-0473
    Example: Merge Project Config Preserves Base Event Logging
      Given the pytest test setup is prepared
      When merge project config preserves base event logging is executed
      Then config.event_logging.enabled is True

    @req-REQ-0041 @ac-AC-0456
    Example: Default Taskledger Toml Includes Commented Event Logging
      Given the pytest test setup is prepared
      When default taskledger toml includes commented event logging is executed
      Then '# [event_logging]' is in rendered
      Then '# enabled = true' is in rendered

    @req-REQ-0041 @ac-AC-0465
    Example: Invalid event logging configuration is rejected
      Given event_logging is not a table or contains invalid fields
      When Taskledger validates project configuration
      Then configuration loading fails with a validation error
