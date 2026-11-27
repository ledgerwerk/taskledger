from __future__ import annotations

from dataclasses import dataclass

from taskledger.storage.project_config import (
    _DEFAULT_CONFIG,
    AGENT_LOGGING_CONFIG_KEYS,
    EVENT_LOGGING_CONFIG_KEYS,
    VALID_PLAN_BODY_DETAIL_VALUES,
    VALID_PROFILE_VALUES,
    VALID_QUESTION_POLICY_VALUES,
    VALID_TODO_GRANULARITY_VALUES,
)
from taskledger.storage.worker_pipeline_config import (
    VALID_WORKER_ACTOR_ROLES,
    VALID_WORKER_BASE_CONTEXTS,
    VALID_WORKER_LIFECYCLE_STAGES,
    VALID_WORKER_PIPELINE_MODES,
    VALID_WORKER_STEP_KINDS,
    VALID_WORKER_TEST_COMMAND_POLICIES,
    WORKER_PIPELINE_CONFIG_KEYS,
    WORKER_STEP_CONFIG_KEYS,
)


@dataclass(frozen=True, slots=True)
class ConfigKeyHelp:
    key: str
    description: str
    value_type: str
    allowed_values: tuple[str, ...] = ()
    default_value: object = None
    mutable: bool = True

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "key": self.key,
            "description": self.description,
            "value_type": self.value_type,
            "mutable": self.mutable,
        }
        if self.allowed_values:
            payload["allowed_values"] = list(self.allowed_values)
        if self.default_value is not None:
            payload["default_value"] = self.default_value
        return payload


PROJECT_CONFIG_KEY_SCHEMA: tuple[ConfigKeyHelp, ...] = (
    ConfigKeyHelp("config_version", "Config schema version.", "integer", mutable=False),
    ConfigKeyHelp(
        "taskledger_dir",
        "Path to the durable taskledger state directory.",
        "string",
        mutable=False,
    ),
    ConfigKeyHelp("project_uuid", "Stable project UUID.", "string", mutable=False),
    ConfigKeyHelp(
        "project_name",
        "Normalized project name used in sync contexts.",
        "string",
        mutable=False,
    ),
    ConfigKeyHelp(
        "ledger_ref",
        "Active ledger reference name.",
        "string",
        mutable=False,
    ),
    ConfigKeyHelp(
        "ledger_parent_ref", "Parent ledger reference name.", "string", mutable=False
    ),
    ConfigKeyHelp(
        "ledger_next_task_number",
        "Next task number for this ledger.",
        "integer",
        mutable=False,
    ),
    ConfigKeyHelp(
        "ledger_branch_guard",
        "Ledger branch guard policy.",
        "string",
        allowed_values=("off", "warn", "error"),
        mutable=False,
    ),
    ConfigKeyHelp(
        "ledger.code",
        "Stable code for this ledger.",
        "string",
        mutable=False,
    ),
    ConfigKeyHelp(
        "ledger.name",
        "Display name for this ledger.",
        "string",
        mutable=False,
    ),
    ConfigKeyHelp(
        "artifact_max_bytes",
        "Maximum stored size of a Taskledger-owned artifact file; may only lower "
        "the hard ceiling.",
        "integer",
        default_value=_DEFAULT_CONFIG.artifact_max_bytes,
    ),
    ConfigKeyHelp(
        "prompt_profiles.<profile>.profile",
        "Planning strictness profile.",
        "string",
        allowed_values=tuple(sorted(VALID_PROFILE_VALUES)),
        default_value="balanced",
    ),
    ConfigKeyHelp(
        "prompt_profiles.<profile>.question_policy",
        "How required planning questions are asked.",
        "string",
        allowed_values=tuple(sorted(VALID_QUESTION_POLICY_VALUES)),
        default_value="ask_when_missing",
    ),
    ConfigKeyHelp(
        "prompt_profiles.<profile>.max_required_questions",
        "Maximum required planning questions before proposing a plan.",
        "integer",
        default_value=5,
    ),
    ConfigKeyHelp(
        "prompt_profiles.<profile>.min_acceptance_criteria",
        "Minimum required acceptance criteria in plans.",
        "integer",
        default_value=1,
    ),
    ConfigKeyHelp(
        "prompt_profiles.<profile>.todo_granularity",
        "Expected planning todo granularity.",
        "string",
        allowed_values=tuple(sorted(VALID_TODO_GRANULARITY_VALUES)),
        default_value="implementation_steps",
    ),
    ConfigKeyHelp(
        "prompt_profiles.<profile>.require_files",
        "Require file links in plans.",
        "boolean",
        default_value=True,
    ),
    ConfigKeyHelp(
        "prompt_profiles.<profile>.require_test_commands",
        "Require test commands in plans.",
        "boolean",
        default_value=True,
    ),
    ConfigKeyHelp(
        "prompt_profiles.<profile>.require_expected_outputs",
        "Require expected command outputs in plans.",
        "boolean",
        default_value=True,
    ),
    ConfigKeyHelp(
        "prompt_profiles.<profile>.require_validation_hints",
        "Require validation hints in plans.",
        "boolean",
        default_value=True,
    ),
    ConfigKeyHelp(
        "prompt_profiles.<profile>.plan_body_detail",
        "Expected depth of the plan body narrative.",
        "string",
        allowed_values=tuple(sorted(VALID_PLAN_BODY_DETAIL_VALUES)),
        default_value="normal",
    ),
    ConfigKeyHelp(
        "prompt_profiles.<profile>.required_question_topics",
        "Topics that must appear in required planning questions.",
        "array[string]",
        default_value=[],
    ),
    ConfigKeyHelp(
        "prompt_profiles.<profile>.extra_guidance",
        "Additional project guidance appended during planning.",
        "string|null",
    ),
    ConfigKeyHelp(
        "event_logging.enabled",
        "Enable task lifecycle event logging.",
        "boolean",
        default_value=False,
    ),
    ConfigKeyHelp(
        "sync.git.repo",
        "External Git repository path for sync state.",
        "string|null",
    ),
    ConfigKeyHelp(
        "sync.git.project_path",
        "Relative path inside sync.git.repo for this project state.",
        "string|null",
    ),
    ConfigKeyHelp(
        "sync.git.remote",
        "Git remote used for sync operations.",
        "string",
        default_value="origin",
    ),
    ConfigKeyHelp(
        "sync.git.branch",
        "Git branch used for sync operations.",
        "string",
        default_value="main",
    ),
    ConfigKeyHelp(
        "sync.git.allow_active_locks",
        "Allow sync operations while active locks exist.",
        "boolean",
        default_value=False,
    ),
    ConfigKeyHelp(
        "sync.git.hooks",
        "Enable Git hook integration for sync.",
        "boolean",
        default_value=False,
    ),
    ConfigKeyHelp(
        "worker_pipeline.enabled",
        "Enable worker pipeline overlays.",
        "boolean",
        default_value=False,
    ),
    ConfigKeyHelp(
        "worker_pipeline.name",
        "Worker pipeline display name.",
        "string",
        default_value="worker-pipeline",
    ),
    ConfigKeyHelp(
        "worker_pipeline.mode",
        "Worker pipeline behavior mode.",
        "string",
        allowed_values=tuple(sorted(VALID_WORKER_PIPELINE_MODES)),
        default_value="available",
    ),
    ConfigKeyHelp(
        "worker_pipeline.steps",
        "Ordered worker pipeline step definitions.",
        "array[table]",
        default_value=[],
    ),
    ConfigKeyHelp(
        "worker_pipeline.steps[].id",
        "Worker step identifier.",
        "string",
    ),
    ConfigKeyHelp(
        "worker_pipeline.steps[].label",
        "Worker step display label.",
        "string",
    ),
    ConfigKeyHelp(
        "worker_pipeline.steps[].lifecycle_stage",
        "Lifecycle stage where the worker step applies.",
        "string",
        allowed_values=tuple(sorted(VALID_WORKER_LIFECYCLE_STAGES)),
    ),
    ConfigKeyHelp(
        "worker_pipeline.steps[].base_context",
        "Base context renderer used for this step.",
        "string",
        allowed_values=tuple(sorted(VALID_WORKER_BASE_CONTEXTS)),
    ),
    ConfigKeyHelp(
        "worker_pipeline.steps[].actor_role",
        "Actor role expected for this step.",
        "string|null",
        allowed_values=tuple(sorted(VALID_WORKER_ACTOR_ROLES)),
    ),
    ConfigKeyHelp(
        "worker_pipeline.steps[].kind",
        "Worker step semantic kind.",
        "string",
        allowed_values=tuple(sorted(VALID_WORKER_STEP_KINDS)),
        default_value="custom",
    ),
    ConfigKeyHelp(
        "worker_pipeline.steps[].description",
        "Worker step description text.",
        "string|null",
    ),
    ConfigKeyHelp(
        "worker_pipeline.steps[].required_output",
        "Required output checklist for the step.",
        "array[string]",
        default_value=[],
    ),
    ConfigKeyHelp(
        "worker_pipeline.steps[].must_not",
        "Disallowed behavior checklist for the step.",
        "array[string]",
        default_value=[],
    ),
    ConfigKeyHelp(
        "worker_pipeline.steps[].todo_tag",
        "Todo tag associated with this step.",
        "string|null",
    ),
    ConfigKeyHelp(
        "worker_pipeline.steps[].test_command_policy",
        "How test command failures are handled for this step.",
        "string",
        allowed_values=tuple(sorted(VALID_WORKER_TEST_COMMAND_POLICIES)),
        default_value="none",
    ),
)
PROJECT_CONFIG_KEY_SCHEMA += tuple(
    ConfigKeyHelp(
        f"agent_logging.{key}",
        "Agent command logging setting.",
        "boolean"
        if key
        in {
            "enabled",
            "capture_taskledger_cli",
            "capture_managed_shell",
            "capture_visible_stdout",
            "capture_visible_stderr",
            "capture_visible_combined",
            "capture_payload_metadata",
            "store_full_output_artifacts",
            "fail_on_logging_error",
            "capture_safe_read_only",
            "capture_human_oriented",
        }
        else "integer"
        if key in {"max_inline_chars", "max_artifact_bytes"}
        else "array[string]",
        default_value=getattr(_DEFAULT_CONFIG.agent_logging, key, None),
    )
    for key in sorted(AGENT_LOGGING_CONFIG_KEYS)
)
PROJECT_CONFIG_KEY_SCHEMA += tuple(
    ConfigKeyHelp(
        f"event_logging.{key}",
        "Task lifecycle event logging setting.",
        "boolean",
        default_value=getattr(_DEFAULT_CONFIG.event_logging, key, None),
    )
    for key in sorted(EVENT_LOGGING_CONFIG_KEYS)
    if key != "enabled"
)
PROJECT_CONFIG_KEY_SCHEMA += tuple(
    ConfigKeyHelp(
        f"worker_pipeline.{key}",
        "Worker pipeline setting.",
        "table" if key == "steps" else "boolean" if key == "enabled" else "string",
    )
    for key in sorted(
        WORKER_PIPELINE_CONFIG_KEYS - {"enabled", "name", "mode", "steps"}
    )
)
PROJECT_CONFIG_KEY_SCHEMA += tuple(
    ConfigKeyHelp(
        f"worker_pipeline.steps[].{key}",
        "Worker step setting.",
        "string",
    )
    for key in sorted(
        WORKER_STEP_CONFIG_KEYS
        - {
            "id",
            "label",
            "lifecycle_stage",
            "base_context",
            "actor_role",
            "kind",
            "description",
            "required_output",
            "must_not",
            "todo_tag",
            "test_command_policy",
        }
    )
)
