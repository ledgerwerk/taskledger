@area-config_cli @feature-config-cli @generated
Feature: Config Cli

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-config-cli
  Rule: Config Cli

    @req-REQ-0014 @ac-AC-0130
    Example: Config List And Get Json
      Given the pytest test setup is prepared
      When config list and get json is executed
      Then listed.exit_code equals 0
      Then isinstance succeeds
      Then gotten.exit_code equals 0

    @req-REQ-0014 @ac-AC-0129
    Example: Config Keys Lists Known Paths
      Given the pytest test setup is prepared
      When config keys lists known paths is executed
      Then result.exit_code equals 0
      Then isinstance succeeds
      Then 'prompt_profiles.<profile>.plan_body_detail' is in key_names
      Then 'prompt_profiles.<profile>.question_policy' is in key_names
      Then 'default_memory_update_mode' is in key_names

    @req-REQ-0014 @ac-AC-0126
    Example: Config Describe Shows Allowed Values And Current Value
      Given the pytest test setup is prepared
      When config describe shows allowed values and current value is executed
      Then set_result.exit_code equals 0
      Then describe_result.exit_code equals 0

    @req-REQ-0014 @ac-AC-0127
    Example: Config Describe Unknown Key Returns Error
      Given the pytest test setup is prepared
      When config describe unknown key returns error is executed
      Then result.exit_code equals 1

    @req-REQ-0014 @ac-AC-0135
    Example: Config Set Updates Prompt Profile Numbers
      Given the pytest test setup is prepared
      When config set updates prompt profile numbers is executed
      Then set_result.exit_code equals 0
      Then get_result.exit_code equals 0

    @req-REQ-0014 @ac-AC-0132
    Example: Config Set Parses Bare String Value
      Given the pytest test setup is prepared
      When config set parses bare string value is executed
      Then set_result.exit_code equals 0
      Then get_result.exit_code equals 0

    @req-REQ-0014 @ac-AC-0133
    Example: Config Set Rejects Invalid Values With Json Error
      Given the pytest test setup is prepared
      When config set rejects invalid values with json error is executed
      Then first_set.exit_code equals 0
      Then invalid_set.exit_code equals 1
      Then get_result.exit_code equals 0

    @req-REQ-0014 @ac-AC-0128
    Example: Config Get Missing Key Returns Error
      Given the pytest test setup is prepared
      When config get missing key returns error is executed
      Then result.exit_code equals 1

    @req-REQ-0014 @ac-AC-0134
    Example: Config Set Rejects Reserved Keys
      Given the pytest test setup is prepared
      When config set rejects reserved keys is executed
      Then result.exit_code equals 1

    @req-REQ-0014 @ac-AC-0131
    Example: Config Set Handles Inline Section Comments
      Given the pytest test setup is prepared
      When config set handles inline section comments is executed
      Then result.exit_code equals 0
      Then '[prompt_profiles.planning] # keep note' is in updated
