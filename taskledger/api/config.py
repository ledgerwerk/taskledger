from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path

from taskledger.errors import LaunchError
from taskledger.storage.paths import resolve_project_paths
from taskledger.storage.project_config import (
    _DEFAULT_CONFIG,
    AGENT_LOGGING_CONFIG_KEYS,
    EVENT_LOGGING_CONFIG_KEYS,
    VALID_PLAN_BODY_DETAIL_VALUES,
    VALID_PROFILE_VALUES,
    VALID_QUESTION_POLICY_VALUES,
    VALID_TODO_GRANULARITY_VALUES,
    get_project_config_value,
    load_project_config_document,
    set_project_config_value,
)
from taskledger.storage.project_context import load_project_context
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

try:
    tomllib = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    tomllib = importlib.import_module("tomli")


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


_CONFIG_KEY_HELP: tuple[ConfigKeyHelp, ...] = (
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
        "default_memory_update_mode",
        "Default memory update strategy for saved artifacts.",
        "string",
        allowed_values=("replace", "append", "prepend"),
        default_value=_DEFAULT_CONFIG.default_memory_update_mode,
    ),
    ConfigKeyHelp(
        "default_file_render_mode",
        "Default file rendering strategy in context output.",
        "string",
        allowed_values=("content", "reference"),
        default_value=_DEFAULT_CONFIG.default_file_render_mode,
    ),
    ConfigKeyHelp(
        "default_save_run_reports",
        "Whether run reports are saved by default.",
        "boolean",
        default_value=_DEFAULT_CONFIG.default_save_run_reports,
    ),
    ConfigKeyHelp(
        "default_source_max_chars",
        "Per-source character budget for context composition.",
        "integer|null",
        default_value=_DEFAULT_CONFIG.default_source_max_chars,
    ),
    ConfigKeyHelp(
        "default_total_source_max_chars",
        "Total source character budget for context composition.",
        "integer|null",
        default_value=_DEFAULT_CONFIG.default_total_source_max_chars,
    ),
    ConfigKeyHelp(
        "default_source_head_lines",
        "Maximum head lines to include per source.",
        "integer|null",
        default_value=_DEFAULT_CONFIG.default_source_head_lines,
    ),
    ConfigKeyHelp(
        "default_source_tail_lines",
        "Maximum tail lines to include per source.",
        "integer|null",
        default_value=_DEFAULT_CONFIG.default_source_tail_lines,
    ),
    ConfigKeyHelp(
        "default_context_order",
        "Default section ordering for composed context output.",
        "array[string]",
        default_value=list(_DEFAULT_CONFIG.default_context_order),
    ),
    ConfigKeyHelp(
        "workflow_schema",
        "Optional project workflow schema label.",
        "string|null",
    ),
    ConfigKeyHelp(
        "project_context",
        "Optional project-level guidance appended to context output.",
        "string|null",
    ),
    ConfigKeyHelp(
        "default_artifact_order",
        "Preferred artifact ordering when rendering reports.",
        "array[string]",
        default_value=list(_DEFAULT_CONFIG.default_artifact_order),
    ),
    ConfigKeyHelp(
        "artifact_rules",
        "Artifact dependency and labeling rule table.",
        "table",
    ),
    ConfigKeyHelp(
        "artifact_rules.<artifact>.depends_on",
        "Artifacts required before this artifact.",
        "array[string]",
    ),
    ConfigKeyHelp(
        "artifact_rules.<artifact>.memory_ref_field",
        "Memory reference field bound to this artifact.",
        "string|null",
    ),
    ConfigKeyHelp(
        "artifact_rules.<artifact>.label",
        "Display label for this artifact.",
        "string|null",
    ),
    ConfigKeyHelp(
        "artifact_rules.<artifact>.description",
        "Description shown for this artifact.",
        "string|null",
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
_CONFIG_KEY_HELP += tuple(
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
_CONFIG_KEY_HELP += tuple(
    ConfigKeyHelp(
        f"event_logging.{key}",
        "Task lifecycle event logging setting.",
        "boolean",
        default_value=getattr(_DEFAULT_CONFIG.event_logging, key, None),
    )
    for key in sorted(EVENT_LOGGING_CONFIG_KEYS)
    if key != "enabled"
)
_CONFIG_KEY_HELP += tuple(
    ConfigKeyHelp(
        f"worker_pipeline.{key}",
        "Worker pipeline setting.",
        "table" if key == "steps" else "boolean" if key == "enabled" else "string",
    )
    for key in sorted(
        WORKER_PIPELINE_CONFIG_KEYS - {"enabled", "name", "mode", "steps"}
    )
)
_CONFIG_KEY_HELP += tuple(
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


def config_list(workspace_root: Path) -> dict[str, object]:
    context = load_project_context(workspace_root)
    if context.mode == "canonical":
        try:
            document = tomllib.loads(context.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LaunchError(
                f"Invalid canonical project config {context.config_path}: {exc}"
            ) from exc
    else:
        document = load_project_config_document(context.config_path)
    return {
        "kind": "project_config",
        "workspace_root": str(context.project_root),
        "config_path": str(context.config_path),
        "config": document,
    }


def config_get(workspace_root: Path, *, key: str) -> dict[str, object]:
    context = load_project_context(workspace_root)
    if context.mode == "canonical":
        document = config_list(workspace_root)["config"]
        value: object = document
        for segment in key.split("."):
            if not isinstance(value, dict) or segment not in value:
                raise LaunchError(f"Config key not found: {key}")
            value = value[segment]
    else:
        value = get_project_config_value(context.config_path, key)
    return {
        "kind": "project_config_value",
        "workspace_root": str(context.project_root),
        "config_path": str(context.config_path),
        "key": key,
        "value": value,
    }


def config_keys(workspace_root: Path) -> dict[str, object]:
    paths = resolve_project_paths(workspace_root)
    keys = [
        entry.to_dict() for entry in sorted(_CONFIG_KEY_HELP, key=lambda item: item.key)
    ]
    return {
        "kind": "project_config_keys",
        "workspace_root": str(paths.workspace_root),
        "config_path": str(paths.config_path),
        "keys": keys,
    }


def config_describe(workspace_root: Path, *, key: str) -> dict[str, object]:
    paths = resolve_project_paths(workspace_root)
    context = load_project_context(workspace_root)
    matched = _match_config_help_entry(key)
    if matched is None:
        raise LaunchError(
            f"Config key help not found: {key}. "
            "Run `taskledger config keys` to list supported key names."
        )
    value: object = None
    has_value = False
    try:
        value = (
            config_get(workspace_root, key=key)["value"]
            if context.mode == "canonical"
            else get_project_config_value(paths.config_path, key)
        )
        has_value = True
    except LaunchError as exc:
        if "Config key not found" not in str(exc):
            raise
    return {
        "kind": "project_config_key_help",
        "workspace_root": str(paths.workspace_root),
        "config_path": str(paths.config_path),
        "key": key,
        "schema_key": matched.key,
        "description": matched.description,
        "value_type": matched.value_type,
        "allowed_values": list(matched.allowed_values),
        "default_value": matched.default_value,
        "mutable": matched.mutable,
        "has_explicit_value": has_value,
        "value": value,
    }


def config_set(workspace_root: Path, *, key: str, value_text: str) -> dict[str, object]:
    context = load_project_context(workspace_root)
    paths = resolve_project_paths(workspace_root)
    value = parse_config_value_text(value_text)
    before: object = None
    try:
        before = config_get(workspace_root, key=key)["value"]
    except LaunchError as exc:
        if "Config key not found" not in str(exc):
            raise
    # Enforce immutability before branching between modes.
    help_entry = _match_config_help_entry(key)
    if help_entry is not None and not help_entry.mutable:
        raise LaunchError(
            f"Config key {key} is immutable. "
            "Use the dedicated repair or topology command."
        )
    if context.mode == "canonical":
        if key in {
            "config_version",
            "taskledger_dir",
            "project_uuid",
            "project_name",
            "ledger_ref",
            "ledger_parent_ref",
            "ledger_next_task_number",
            "ledger_branch_guard",
        }:
            raise LaunchError(
                f"Config key {key} cannot be edited in canonical mode; "
                "topology and ledger state are managed separately."
            )
        from tomlkit import dumps, parse, table

        from taskledger.storage.atomic import atomic_write_text

        try:
            document = parse(context.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LaunchError(
                f"Invalid canonical project config {context.config_path}: {exc}"
            ) from exc
        target = document
        segments = key.split(".")
        for segment in segments[:-1]:
            if segment not in target:
                target[segment] = table()
            target = target[segment]
        target[segments[-1]] = value
        atomic_write_text(context.config_path, dumps(document))
        after = config_get(workspace_root, key=key)["value"]
    else:
        set_project_config_value(paths.config_path, key, value)
        after = get_project_config_value(paths.config_path, key)
    return {
        "kind": "project_config_updated",
        "workspace_root": str(paths.workspace_root),
        "config_path": str(paths.config_path),
        "key": key,
        "previous_value": before,
        "value": after,
    }


def parse_config_value_text(value_text: str) -> object:
    stripped = value_text.strip()
    if not stripped:
        return ""
    try:
        parsed = tomllib.loads(f"value = {stripped}")
    except tomllib.TOMLDecodeError:
        return value_text
    if not isinstance(parsed, dict) or "value" not in parsed:
        raise LaunchError("Failed to parse config value.")
    return parsed["value"]


def _match_config_help_entry(key: str) -> ConfigKeyHelp | None:
    normalized = key.strip()
    if not normalized:
        return None
    for entry in _CONFIG_KEY_HELP:
        if _config_key_matches_pattern(normalized, entry.key):
            return entry
    return None


def _config_key_matches_pattern(key: str, pattern: str) -> bool:
    key_segments = tuple(segment for segment in key.split(".") if segment)
    pattern_segments = tuple(segment for segment in pattern.split(".") if segment)
    if len(key_segments) != len(pattern_segments):
        return False
    for key_segment, pattern_segment in zip(
        key_segments,
        pattern_segments,
        strict=True,
    ):
        if pattern_segment in {"<profile>", "<artifact>", "[]"}:
            continue
        if pattern_segment.endswith("[]"):
            literal = pattern_segment[:-2]
            if key_segment != literal:
                return False
            continue
        if pattern_segment.startswith("<") and pattern_segment.endswith(">"):
            continue
        if key_segment != pattern_segment:
            return False
    return True


__all__ = [
    "config_describe",
    "config_list",
    "config_keys",
    "config_get",
    "config_set",
    "parse_config_value_text",
]
