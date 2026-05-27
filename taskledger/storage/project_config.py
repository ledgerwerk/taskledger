from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from taskledger.errors import LaunchError
from taskledger.storage.project_identity import normalize_project_name
from taskledger.storage.toml_edit import (
    is_toml_key_line as _is_toml_key_line,
)
from taskledger.storage.toml_edit import (
    join_toml_lines as _join_lines,
)
from taskledger.storage.worker_pipeline_config import (
    WorkerPipelineConfig,
    parse_worker_pipeline,
    validate_worker_pipeline,
)

if TYPE_CHECKING:
    from taskledger.storage.paths import ProjectPaths

try:
    tomllib = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    tomllib = importlib.import_module("tomli")

LOCATION_CONFIG_KEYS = frozenset({"config_version", "taskledger_dir"})
IDENTITY_CONFIG_KEYS = frozenset({"project_uuid"})
PROJECT_METADATA_CONFIG_KEYS = frozenset({"project_name"})
LEDGER_CONFIG_KEYS = frozenset(
    {
        "ledger_ref",
        "ledger_parent_ref",
        "ledger_next_task_number",
        "ledger_branch_guard",
    }
)
WORKFLOW_CONFIG_KEYS = frozenset(
    {
        "default_memory_update_mode",
        "default_file_render_mode",
        "default_save_run_reports",
        "default_source_max_chars",
        "default_total_source_max_chars",
        "default_source_head_lines",
        "default_source_tail_lines",
        "default_context_order",
        "workflow_schema",
        "project_context",
        "artifact_rules",
        "default_artifact_order",
        "prompt_profiles",
        "agent_logging",
        "event_logging",
        "worker_pipeline",
    }
)
SYNC_CONFIG_KEYS = frozenset({"sync"})
AGENT_LOGGING_CONFIG_KEYS = frozenset(
    {
        "enabled",
        "capture_taskledger_cli",
        "capture_managed_shell",
        "capture_visible_stdout",
        "capture_visible_stderr",
        "capture_visible_combined",
        "capture_payload_metadata",
        "max_inline_chars",
        "store_full_output_artifacts",
        "max_artifact_bytes",
        "fail_on_logging_error",
        "redact_patterns",
        "capture_safe_read_only",
        "capture_human_oriented",
    }
)
EVENT_LOGGING_CONFIG_KEYS = frozenset({"enabled"})
SUPPORTED_PROJECT_CONFIG_KEYS = (
    LOCATION_CONFIG_KEYS
    | IDENTITY_CONFIG_KEYS
    | PROJECT_METADATA_CONFIG_KEYS
    | LEDGER_CONFIG_KEYS
    | WORKFLOW_CONFIG_KEYS
    | SYNC_CONFIG_KEYS
)
MemoryUpdateMode = Literal["replace", "append", "prepend"]
FileRenderMode = Literal["content", "reference"]
DEFAULT_PROJECT_SOURCE_MAX_CHARS = 12000
DEFAULT_PROJECT_TOTAL_SOURCE_MAX_CHARS = 48000
DEFAULT_PROJECT_SOURCE_HEAD_LINES = 200
DEFAULT_PROJECT_SOURCE_TAIL_LINES = 50
ARTIFACT_MEMORY_REF_FIELDS = (
    "analysis_memory_ref",
    "state_memory_ref",
    "plan_memory_ref",
    "implementation_memory_ref",
    "validation_memory_ref",
    "save_target_ref",
)

VALID_PROFILE_VALUES = frozenset({"compact", "balanced", "strict", "exploratory"})
VALID_QUESTION_POLICY_VALUES = frozenset(
    {"ask_when_missing", "always_before_plan", "minimal"}
)
VALID_TODO_GRANULARITY_VALUES = frozenset({"minimal", "implementation_steps", "atomic"})
VALID_PLAN_BODY_DETAIL_VALUES = frozenset({"terse", "normal", "detailed"})
MAX_EXTRA_GUIDANCE_CHARS = 4000
CONFIG_KEY_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
PROMPT_PROFILE_KEYS = frozenset(
    {
        "profile",
        "question_policy",
        "max_required_questions",
        "min_acceptance_criteria",
        "todo_granularity",
        "require_files",
        "require_test_commands",
        "require_expected_outputs",
        "require_validation_hints",
        "plan_body_detail",
        "required_question_topics",
        "extra_guidance",
    }
)


@dataclass(slots=True, frozen=True)
class PromptProfile:
    name: str = "planning"
    profile: str = "balanced"
    question_policy: str = "ask_when_missing"
    max_required_questions: int = 5
    min_acceptance_criteria: int = 1
    todo_granularity: str = "implementation_steps"
    require_files: bool = True
    require_test_commands: bool = True
    require_expected_outputs: bool = True
    require_validation_hints: bool = True
    plan_body_detail: str = "normal"
    required_question_topics: tuple[str, ...] = ()
    extra_guidance: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "profile": self.profile,
            "question_policy": self.question_policy,
            "max_required_questions": self.max_required_questions,
            "min_acceptance_criteria": self.min_acceptance_criteria,
            "todo_granularity": self.todo_granularity,
            "require_files": self.require_files,
            "require_test_commands": self.require_test_commands,
            "require_expected_outputs": self.require_expected_outputs,
            "require_validation_hints": self.require_validation_hints,
            "plan_body_detail": self.plan_body_detail,
            "required_question_topics": list(self.required_question_topics),
            "extra_guidance": self.extra_guidance,
        }


@dataclass(slots=True, frozen=True)
class AgentLoggingConfig:
    enabled: bool = False
    capture_taskledger_cli: bool = True
    capture_managed_shell: bool = True
    capture_visible_stdout: bool = True
    capture_visible_stderr: bool = True
    capture_visible_combined: bool = True
    capture_payload_metadata: bool = True
    max_inline_chars: int = 4000
    store_full_output_artifacts: bool = True
    max_artifact_bytes: int | None = 2_000_000
    fail_on_logging_error: bool = False
    redact_patterns: tuple[str, ...] = ()
    capture_safe_read_only: bool = True
    capture_human_oriented: bool = True


@dataclass(slots=True, frozen=True)
class EventLoggingConfig:
    enabled: bool = False


@dataclass(slots=True, frozen=True)
class GitSyncProjectConfig:
    repo: str | None = None
    project_path: str | None = None
    remote: str = "origin"
    branch: str = "main"
    allow_active_locks: bool = False
    hooks: bool = False


@dataclass(slots=True, frozen=True)
class ProjectArtifactRule:
    name: str
    depends_on: tuple[str, ...] = ()
    memory_ref_field: str | None = None
    label: str | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "depends_on": list(self.depends_on),
            "memory_ref_field": self.memory_ref_field,
            "label": self.label,
            "description": self.description,
        }


@dataclass(slots=True, frozen=True)
class ProjectConfig:
    default_memory_update_mode: MemoryUpdateMode = "replace"
    default_file_render_mode: FileRenderMode = "content"
    default_save_run_reports: bool = True
    default_source_max_chars: int | None = DEFAULT_PROJECT_SOURCE_MAX_CHARS
    default_total_source_max_chars: int | None = DEFAULT_PROJECT_TOTAL_SOURCE_MAX_CHARS
    default_source_head_lines: int | None = DEFAULT_PROJECT_SOURCE_HEAD_LINES
    default_source_tail_lines: int | None = DEFAULT_PROJECT_SOURCE_TAIL_LINES
    default_context_order: tuple[str, ...] = (
        "memory",
        "file",
        "item",
        "inline",
        "loop_artifact",
    )
    workflow_schema: str | None = None
    project_context: str | None = None
    artifact_rules: tuple[ProjectArtifactRule, ...] = ()
    default_artifact_order: tuple[str, ...] = ()
    prompt_profile: PromptProfile | None = None
    agent_logging: AgentLoggingConfig = AgentLoggingConfig()
    event_logging: EventLoggingConfig = EventLoggingConfig()
    worker_pipeline: WorkerPipelineConfig | None = None
    sync_git: GitSyncProjectConfig = GitSyncProjectConfig()


def render_default_taskledger_toml(
    taskledger_dir: str = ".taskledger",
    config_version: int = 2,
    ledger_ref: str = "main",
    ledger_parent_ref: str = "",
    ledger_next_task_number: int = 1,
    project_uuid: str | None = None,
    project_name: str | None = None,
) -> str:
    normalized_project_name = (
        normalize_project_name(project_name) if project_name is not None else None
    )
    identity_block = ""
    if project_uuid is not None or normalized_project_name is not None:
        identity_lines = [
            "",
            "# Stable project identity. Commit this with your source tree.",
        ]
        if project_uuid is not None:
            identity_lines.append(f'project_uuid = "{project_uuid}"')
        if normalized_project_name is not None:
            identity_lines.append(f'project_name = "{normalized_project_name}"')
        identity_block = "\n".join(identity_lines) + "\n"
    ledger_block = ""
    if config_version >= 2:
        ledger_block = (
            "\n"
            "# Taskledger branch-scoped state."
            " This block is intentionally safe to commit.\n"
            f"ledger_ref = {ledger_ref!r}\n"
            f"ledger_parent_ref = {ledger_parent_ref!r}\n"
            f"ledger_next_task_number = {ledger_next_task_number}\n"
            'ledger_branch_guard = "off"\n'
        )
    return (
        f"# Project-local taskledger configuration.\n"
        f"# This file lives in the source project root.\n"
        f"config_version = {config_version}\n"
        f"taskledger_dir = {taskledger_dir!r}"
        f"{identity_block}"
        f"{ledger_block}"
        f"\n"
        "# Project-local taskledger overrides.\n"
        "# The source-budget settings below are the active composition defaults.\n"
        "# Lower them for stricter prompts,"
        ".or raise them when a run needs more context.\n"
        "# Supported keys:\n"
        '# default_memory_update_mode = "replace"\n'
        '# default_file_render_mode = "content"\n'
        "# default_save_run_reports = true\n"
        f"# default_source_max_chars = {DEFAULT_PROJECT_SOURCE_MAX_CHARS}\n"
        f"# default_total_source_max_chars"
        f" = {DEFAULT_PROJECT_TOTAL_SOURCE_MAX_CHARS}\n"
        f"# default_source_head_lines"
        f" = {DEFAULT_PROJECT_SOURCE_HEAD_LINES}\n"
        f"# default_source_tail_lines"
        f" = {DEFAULT_PROJECT_SOURCE_TAIL_LINES}\n"
        '# default_context_order = ["memory", "file",'
        ' "item", "inline", "loop_artifact"]\n'
        '# workflow_schema = "opsx-lite"\n'
        '# project_context = "Project-specific workflow guidance."\n'
        '# default_artifact_order = ["analysis", "plan",'
        ' "implementation", "validation"]\n'
        "\n"
        "# Optional project-local planning guidance for agents.\n"
        "# This is advisory and cannot override lifecycle gates.\n"
        "# [prompt_profiles.planning]\n"
        '# profile = "balanced"\n'
        '# question_policy = "ask_when_missing"\n'
        "# max_required_questions = 5\n"
        "# min_acceptance_criteria = 1\n"
        '# todo_granularity = "implementation_steps"\n'
        "# require_files = true\n"
        "# require_test_commands = true\n"
        "# require_expected_outputs = true\n"
        "# require_validation_hints = true\n"
        '# plan_body_detail = "normal"\n'
        '# required_question_topics = ["scope", "tests"]\n'
        '# extra_guidance = "Mention docs and validation evidence in every plan."\n'
        "\n"
        "# Agent command transcript logging (disabled by default).\n"
        "# [agent_logging]\n"
        "# enabled = false\n"
        "# capture_taskledger_cli = true\n"
        "# capture_managed_shell = true\n"
        "# capture_visible_stdout = true\n"
        "# capture_visible_stderr = true\n"
        "# capture_visible_combined = true\n"
        "# capture_payload_metadata = true\n"
        "# max_inline_chars = 4000\n"
        "# store_full_output_artifacts = true\n"
        "# max_artifact_bytes = 2000000\n"
        "# fail_on_logging_error = false\n"
        '# redact_patterns = ["(?i)(api[_-]?key|token|password|secret)=\\\\S+"]\n'
        "# capture_safe_read_only = true\n"
        "# capture_human_oriented = true\n"
        "\n"
        "# Task lifecycle event logging (disabled by default).\n"
        "# Enable only when debugging agent usage or lifecycle behavior.\n"
        "# [event_logging]\n"
        "# enabled = false\n"
        "\n"
        "# Optional sync.git defaults for private external Git state.\n"
        "# [sync.git]\n"
        '# repo = "../taskledger-state"\n'
        '# project_path = "project-a"\n'
        '# remote = "origin"\n'
        '# branch = "main"\n'
        "# allow_active_locks = false\n"
        "# hooks = false\n"
    )


DEFAULT_TASKLEDGER_TOML = render_default_taskledger_toml()
DEFAULT_PROJECT_TOML = DEFAULT_TASKLEDGER_TOML
_DEFAULT_CONFIG = ProjectConfig()


def update_taskledger_dir(config_path: Path, taskledger_dir: str) -> None:
    if not config_path.exists():
        raise LaunchError(f"Project config does not exist: {config_path}")
    try:
        current_text = config_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise LaunchError(f"Failed to read {config_path}: {exc}") from exc
    updated_text = _apply_taskledger_dir_patch(current_text, taskledger_dir)
    from taskledger.storage.atomic import atomic_write_text

    atomic_write_text(config_path, updated_text)


def get_project_config_value(config_path: Path, dotted_key: str) -> object:
    document = load_project_config_document(config_path)
    segments = _parse_project_config_key_path(dotted_key)
    return _read_project_config_path(document, segments)


def set_project_config_value(config_path: Path, dotted_key: str, value: object) -> None:
    if not config_path.exists():
        raise LaunchError(f"Project config does not exist: {config_path}")
    try:
        current_text = config_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise LaunchError(f"Failed to read {config_path}: {exc}") from exc

    existing_document = (
        load_project_config_document(config_path) if current_text else {}
    )
    segments = _parse_project_config_key_path(dotted_key)
    _ensure_mutable_project_config_key_path(segments)
    updated_document = _copy_project_config_document(existing_document)
    _set_project_config_path(updated_document, segments, value)
    _validate_project_config_overrides(updated_document, config_path)

    updated_text = _apply_project_config_value_patch(
        current_text,
        key_path=segments,
        value=value,
    )
    from taskledger.storage.atomic import atomic_write_text

    atomic_write_text(config_path, updated_text)
    load_project_config_document(config_path)


def load_project_config_overrides(paths: ProjectPaths) -> dict[str, object]:
    data = load_project_config_document(paths.config_path)
    return {key: value for key, value in data.items() if key in WORKFLOW_CONFIG_KEYS}


def load_worker_pipeline_config(workspace_root: Path) -> WorkerPipelineConfig | None:
    from taskledger.storage.paths import resolve_project_paths

    paths = resolve_project_paths(workspace_root)
    overrides = load_project_config_overrides(paths)
    return merge_project_config(overrides).worker_pipeline


def _apply_taskledger_dir_patch(text: str, taskledger_dir: str) -> str:
    lines = text.split("\n") if text else []
    rendered = repr(taskledger_dir)
    found = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("taskledger_dir") and _is_toml_key_line(
            stripped, "taskledger_dir"
        ):
            new_lines.append(f"taskledger_dir = {rendered}")
            found = True
        else:
            new_lines.append(line)
    if found:
        return _join_lines(new_lines)

    insert_at = 0
    for idx, line in enumerate(new_lines):
        stripped = line.strip()
        if stripped.startswith("config_version") and _is_toml_key_line(
            stripped, "config_version"
        ):
            insert_at = idx + 1
            break
    new_lines.insert(insert_at, f"taskledger_dir = {rendered}")
    return _join_lines(new_lines)


def _parse_project_config_key_path(dotted_key: str) -> tuple[str, ...]:
    normalized = dotted_key.strip()
    if not normalized:
        raise LaunchError("Config key cannot be empty.")
    segments = tuple(segment.strip() for segment in normalized.split("."))
    if not all(segments):
        raise LaunchError(f"Invalid config key path: {dotted_key!r}")
    invalid = [
        segment
        for segment in segments
        if not CONFIG_KEY_SEGMENT_PATTERN.fullmatch(segment)
    ]
    if invalid:
        raise LaunchError(
            "Config key segments may only contain letters, digits, '_', or '-'."
        )
    return segments


def _ensure_mutable_project_config_key_path(path: tuple[str, ...]) -> None:
    top_level_key = path[0]
    reserved_keys = (
        LOCATION_CONFIG_KEYS
        | IDENTITY_CONFIG_KEYS
        | PROJECT_METADATA_CONFIG_KEYS
        | LEDGER_CONFIG_KEYS
    )
    if top_level_key not in reserved_keys:
        return

    key_path = ".".join(path)
    if top_level_key == "taskledger_dir":
        raise LaunchError(
            "config set cannot edit taskledger_dir. Use `taskledger storage move`.",
        )
    if top_level_key in LEDGER_CONFIG_KEYS:
        raise LaunchError(
            "config set cannot edit ledger_* keys directly. "
            "Use `taskledger ledger` commands.",
        )
    raise LaunchError(
        f"config set cannot edit reserved project key: {key_path}",
    )


def _copy_project_config_document(document: dict[str, object]) -> dict[str, object]:
    copied: dict[str, object] = {}
    for key, value in document.items():
        copied[key] = _copy_project_config_value(value)
    return copied


def _copy_project_config_value(value: object) -> object:
    if isinstance(value, dict):
        copied: dict[str, object] = {}
        for key, nested in value.items():
            if isinstance(key, str):
                copied[key] = _copy_project_config_value(nested)
        return copied
    if isinstance(value, list):
        return [_copy_project_config_value(item) for item in value]
    return value


def _read_project_config_path(
    document: dict[str, object],
    path: tuple[str, ...],
) -> object:
    current: object = document
    traversed: list[str] = []
    for segment in path:
        traversed.append(segment)
        if not isinstance(current, dict):
            joined = ".".join(traversed[:-1])
            raise LaunchError(f"Config key path is not a table: {joined}")
        if segment not in current:
            raise LaunchError(f"Config key not found: {'.'.join(path)}")
        current = current[segment]
    return current


def _set_project_config_path(
    document: dict[str, object],
    path: tuple[str, ...],
    value: object,
) -> None:
    current: dict[str, object] = document
    traversed: list[str] = []
    for segment in path[:-1]:
        traversed.append(segment)
        nested = current.get(segment)
        if nested is None:
            next_nested: dict[str, object] = {}
            current[segment] = next_nested
            current = next_nested
            continue
        if not isinstance(nested, dict):
            raise LaunchError(f"Config key path is not a table: {'.'.join(traversed)}")
        current = nested
    current[path[-1]] = value


def _apply_project_config_value_patch(
    text: str,
    *,
    key_path: tuple[str, ...],
    value: object,
) -> str:
    section = key_path[:-1]
    key = key_path[-1]
    value_text = _render_toml_value(value)
    assignment = f"{_render_toml_key_segment(key)} = {value_text}"

    lines = text.split("\n") if text else []
    if not lines:
        if section:
            return _join_lines([f"[{_render_toml_section_path(section)}]", assignment])
        return _join_lines([assignment])

    current_section: tuple[str, ...] = ()
    target_section_found = not section
    replaced = False
    section_end_idx: int | None = None
    first_header_idx: int | None = None

    for idx, line in enumerate(lines):
        parsed = _parse_toml_table_header(line)
        if parsed is not None:
            if first_header_idx is None:
                first_header_idx = idx
            if section and current_section == section and section_end_idx is None:
                section_end_idx = idx
            current_section = parsed
            if section and current_section == section:
                target_section_found = True
                section_end_idx = None
            continue

        if current_section == section and _toml_assignment_matches(line, key):
            lines[idx] = assignment
            replaced = True

    if section and target_section_found and section_end_idx is None:
        section_end_idx = len(lines)

    if replaced:
        return _join_lines(lines)

    if section:
        if target_section_found:
            assert section_end_idx is not None
            lines.insert(section_end_idx, assignment)
            return _join_lines(lines)
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{_render_toml_section_path(section)}]")
        lines.append(assignment)
        return _join_lines(lines)

    insert_at = first_header_idx if first_header_idx is not None else len(lines)
    lines.insert(insert_at, assignment)
    return _join_lines(lines)


def _parse_toml_table_header(line: str) -> tuple[str, ...] | None:
    stripped = line.lstrip()
    if not stripped.startswith("["):
        return None
    if stripped.startswith("[["):
        return None
    closing_idx = stripped.find("]")
    if closing_idx <= 0:
        return None
    trailing = stripped[closing_idx + 1 :].strip()
    if trailing and not trailing.startswith("#"):
        return None
    inner = stripped[1:closing_idx].strip()
    if not inner:
        return None
    parts = [part.strip() for part in inner.split(".")]
    segments: list[str] = []
    for part in parts:
        if not part:
            return None
        if len(part) >= 2 and (
            (part.startswith('"') and part.endswith('"'))
            or (part.startswith("'") and part.endswith("'"))
        ):
            segments.append(part[1:-1])
        else:
            segments.append(part)
    return tuple(segments)


def _toml_assignment_matches(line: str, key: str) -> bool:
    stripped = line.strip()
    if _is_toml_key_line(stripped, key):
        return True
    quoted = f'"{key}"'
    return _is_toml_key_line(stripped, quoted)


def _render_toml_section_path(path: tuple[str, ...]) -> str:
    return ".".join(_render_toml_key_segment(segment) for segment in path)


def _render_toml_key_segment(segment: str) -> str:
    if CONFIG_KEY_SEGMENT_PATTERN.fullmatch(segment):
        return segment
    escaped = segment.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    if isinstance(value, list):
        rendered = ", ".join(_render_toml_value(item) for item in value)
        return f"[{rendered}]"
    if isinstance(value, tuple):
        rendered = ", ".join(_render_toml_value(item) for item in value)
        return f"[{rendered}]"
    if isinstance(value, dict):
        parts: list[str] = []
        for key, nested in value.items():
            if not isinstance(key, str):
                raise LaunchError("Config table keys must be strings.")
            parts.append(
                f"{_render_toml_key_segment(key)} = {_render_toml_value(nested)}"
            )
        return "{ " + ", ".join(parts) + " }"
    raise LaunchError(
        "Config values must be TOML-compatible scalars, arrays, or inline tables."
    )


def load_project_config_document(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise LaunchError(f"Failed to read {path}: {exc}") from exc
    if not text:
        return {}
    try:
        data = tomllib.loads(text)
    except Exception as exc:  # pragma: no cover - tomllib type varies by runtime
        raise LaunchError(f"Invalid project config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise LaunchError(f"Invalid project config {path}: expected a TOML table.")
    _validate_project_config_overrides(data, path)
    return data


def merge_project_config(
    overrides: dict[str, object], *, base: ProjectConfig | None = None
) -> ProjectConfig:
    if base is None:
        base = _DEFAULT_CONFIG
    default_memory_update_mode = overrides.get(
        "default_memory_update_mode", base.default_memory_update_mode
    )
    default_file_render_mode = overrides.get(
        "default_file_render_mode",
        base.default_file_render_mode,
    )
    default_save_run_reports = overrides.get(
        "default_save_run_reports", base.default_save_run_reports
    )
    default_source_max_chars = overrides.get(
        "default_source_max_chars", base.default_source_max_chars
    )
    default_total_source_max_chars = overrides.get(
        "default_total_source_max_chars", base.default_total_source_max_chars
    )
    default_source_head_lines = overrides.get(
        "default_source_head_lines", base.default_source_head_lines
    )
    default_source_tail_lines = overrides.get(
        "default_source_tail_lines", base.default_source_tail_lines
    )
    default_context_order = overrides.get(
        "default_context_order", list(base.default_context_order)
    )
    workflow_schema = overrides.get("workflow_schema", base.workflow_schema)
    project_context = overrides.get("project_context", base.project_context)
    artifact_rules = _artifact_rules_from_overrides(
        overrides.get("artifact_rules"),
        base.artifact_rules,
    )
    default_artifact_order = overrides.get(
        "default_artifact_order",
        list(base.default_artifact_order),
    )
    if not isinstance(default_memory_update_mode, str):
        raise LaunchError("Project config default_memory_update_mode must be a string.")
    if default_memory_update_mode not in {"replace", "append", "prepend"}:
        raise LaunchError(
            "Project config default_memory_update_mode must be "
            "replace, append, or prepend."
        )
    if not isinstance(default_file_render_mode, str):
        raise LaunchError("Project config default_file_render_mode must be a string.")
    if default_file_render_mode not in {"content", "reference"}:
        raise LaunchError(
            "Project config default_file_render_mode must be content or reference."
        )
    if not isinstance(default_save_run_reports, bool):
        raise LaunchError("Project config default_save_run_reports must be a boolean.")
    for value, label in (
        (default_source_max_chars, "default_source_max_chars"),
        (default_total_source_max_chars, "default_total_source_max_chars"),
        (default_source_head_lines, "default_source_head_lines"),
        (default_source_tail_lines, "default_source_tail_lines"),
    ):
        if value is not None and (not isinstance(value, int) or value <= 0):
            raise LaunchError(f"Project config {label} must be a positive integer.")
    if not isinstance(default_context_order, list) or not all(
        isinstance(item, str) for item in default_context_order
    ):
        raise LaunchError(
            "Project config default_context_order must be a list of strings."
        )
    if workflow_schema is not None and not isinstance(workflow_schema, str):
        raise LaunchError("Project config workflow_schema must be a string.")
    if project_context is not None and not isinstance(project_context, str):
        raise LaunchError("Project config project_context must be a string.")
    if not isinstance(default_artifact_order, list) or not all(
        isinstance(item, str) for item in default_artifact_order
    ):
        raise LaunchError(
            "Project config default_artifact_order must be a list of strings."
        )
    _validate_artifact_order_and_dependencies(
        artifact_rules,
        default_artifact_order=tuple(default_artifact_order),
    )
    prompt_profile = _parse_prompt_profile(
        overrides.get("prompt_profiles"), base.prompt_profile
    )
    agent_logging = _parse_agent_logging(
        overrides.get("agent_logging"),
        base.agent_logging,
    )
    event_logging = _parse_event_logging(
        overrides.get("event_logging"),
        base.event_logging,
    )
    worker_pipeline = parse_worker_pipeline(
        overrides.get("worker_pipeline"),
        base.worker_pipeline,
    )
    sync_git = _parse_sync_git_config(overrides.get("sync"), base.sync_git)
    return ProjectConfig(
        default_memory_update_mode=cast(
            MemoryUpdateMode,
            default_memory_update_mode,
        ),
        default_file_render_mode=cast(FileRenderMode, default_file_render_mode),
        default_save_run_reports=default_save_run_reports,
        default_source_max_chars=cast(int | None, default_source_max_chars),
        default_total_source_max_chars=cast(int | None, default_total_source_max_chars),
        default_source_head_lines=cast(int | None, default_source_head_lines),
        default_source_tail_lines=cast(int | None, default_source_tail_lines),
        default_context_order=tuple(default_context_order),
        workflow_schema=workflow_schema,
        project_context=project_context,
        artifact_rules=artifact_rules,
        default_artifact_order=tuple(default_artifact_order),
        prompt_profile=prompt_profile,
        agent_logging=agent_logging,
        event_logging=event_logging,
        worker_pipeline=worker_pipeline,
        sync_git=sync_git,
    )


def _validate_project_config_overrides(data: dict[str, object], path: Path) -> None:
    for key in data:
        if key not in SUPPORTED_PROJECT_CONFIG_KEYS:
            raise LaunchError(f"Unsupported project config key '{key}' in {path}")
    config_version = data.get("config_version")
    if config_version is not None and config_version not in (1, 2):
        raise LaunchError(
            f"Project config key 'config_version' must be 1 or 2 in {path}"
        )
    taskledger_dir = data.get("taskledger_dir")
    if taskledger_dir is not None and not isinstance(taskledger_dir, str):
        raise LaunchError(
            f"Project config key 'taskledger_dir' must be a string in {path}"
        )
    project_name = data.get("project_name")
    if project_name is not None:
        try:
            normalize_project_name(project_name)
        except LaunchError as exc:
            raise LaunchError(
                f"Project config key 'project_name' is invalid in {path}: {exc}"
            ) from exc
    artifact_rules = data.get("artifact_rules")
    if artifact_rules is not None:
        if not isinstance(artifact_rules, dict):
            raise LaunchError(
                f"Project config key 'artifact_rules' must be a table in {path}"
            )
        parsed_rules = _artifact_rules_from_mapping(artifact_rules, path=path)
        default_order = data.get("default_artifact_order")
        default_artifact_order = (
            tuple(default_order) if isinstance(default_order, list) else ()
        )
        _validate_artifact_order_and_dependencies(
            parsed_rules,
            default_artifact_order=default_artifact_order,
            path=path,
        )
    prompt_profiles = data.get("prompt_profiles")
    if prompt_profiles is not None:
        if not isinstance(prompt_profiles, dict):
            raise LaunchError(
                f"Project config key 'prompt_profiles' must be a table in {path}"
            )
        for profile_name, profile_data in prompt_profiles.items():
            if not isinstance(profile_data, dict):
                raise LaunchError(
                    f"Project config prompt_profiles.{profile_name} "
                    f"must be a table in {path}"
                )
            _validate_prompt_profile(profile_name, profile_data, path)
    _validate_agent_logging(data.get("agent_logging"), path)
    _validate_event_logging(data.get("event_logging"), path)
    validate_worker_pipeline(data.get("worker_pipeline"), path)
    _validate_sync_config(data.get("sync"), path)


def _validate_sync_config(raw: object, path: Path) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise LaunchError(f"Project config key 'sync' must be a table in {path}")
    sync_git = raw.get("git")
    if sync_git is None:
        return
    if not isinstance(sync_git, dict):
        raise LaunchError(f"Project config key 'sync.git' must be a table in {path}")
    allowed = {
        "repo",
        "project_path",
        "remote",
        "branch",
        "allow_active_locks",
        "hooks",
    }
    for key in sync_git:
        if key not in allowed:
            raise LaunchError(f"Unknown sync.git key '{key}' in {path}")
    for key in ("repo", "project_path", "remote", "branch"):
        value = sync_git.get(key)
        if value is not None and not isinstance(value, str):
            raise LaunchError(f"sync.git.{key} must be a string in {path}")
    project_path = sync_git.get("project_path")
    if isinstance(project_path, str):
        candidate = Path(project_path)
        if (
            candidate.is_absolute()
            or project_path.startswith("/")
            or ".." in candidate.parts
        ):
            raise LaunchError(
                "sync.git.project_path must be relative and must not escape repo "
                f"in {path}"
            )
    for key in ("allow_active_locks", "hooks"):
        value = sync_git.get(key)
        if value is not None and not isinstance(value, bool):
            raise LaunchError(f"sync.git.{key} must be a boolean in {path}")


def _parse_sync_git_config(
    raw: object,
    base: GitSyncProjectConfig,
) -> GitSyncProjectConfig:
    if raw is None or not isinstance(raw, dict):
        return base
    sync_git_raw = raw.get("git")
    if not isinstance(sync_git_raw, dict):
        return base
    return GitSyncProjectConfig(
        repo=(
            sync_git_raw["repo"]
            if isinstance(sync_git_raw.get("repo"), str)
            else base.repo
        ),
        project_path=(
            sync_git_raw["project_path"]
            if isinstance(sync_git_raw.get("project_path"), str)
            else base.project_path
        ),
        remote=(
            sync_git_raw["remote"]
            if isinstance(sync_git_raw.get("remote"), str)
            else base.remote
        ),
        branch=(
            sync_git_raw["branch"]
            if isinstance(sync_git_raw.get("branch"), str)
            else base.branch
        ),
        allow_active_locks=(
            sync_git_raw["allow_active_locks"]
            if isinstance(sync_git_raw.get("allow_active_locks"), bool)
            else base.allow_active_locks
        ),
        hooks=(
            sync_git_raw["hooks"]
            if isinstance(sync_git_raw.get("hooks"), bool)
            else base.hooks
        ),
    )


def _artifact_rules_from_overrides(
    raw_rules: object,
    base_rules: tuple[ProjectArtifactRule, ...],
) -> tuple[ProjectArtifactRule, ...]:
    if raw_rules is None:
        return base_rules
    if not isinstance(raw_rules, dict):
        raise LaunchError("Project config artifact_rules must be a table.")
    return _artifact_rules_from_mapping(raw_rules)


def _artifact_rules_from_mapping(
    raw_rules: dict[str, object],
    *,
    path: Path | None = None,
) -> tuple[ProjectArtifactRule, ...]:
    rules: list[ProjectArtifactRule] = []
    for name, value in raw_rules.items():
        if not isinstance(value, dict):
            raise LaunchError(_artifact_rule_error(name, "must be a table", path=path))
        for key in value:
            if key not in {"depends_on", "memory_ref_field", "label", "description"}:
                raise LaunchError(
                    _artifact_rule_error(
                        name,
                        f"has unsupported key '{key}'",
                        path=path,
                    )
                )
        depends_on = value.get("depends_on", [])
        if not isinstance(depends_on, list) or not all(
            isinstance(item, str) for item in depends_on
        ):
            raise LaunchError(
                _artifact_rule_error(
                    name,
                    "depends_on must be a list of strings",
                    path=path,
                )
            )
        memory_ref_field = value.get("memory_ref_field")
        if memory_ref_field is not None and (
            not isinstance(memory_ref_field, str)
            or memory_ref_field not in ARTIFACT_MEMORY_REF_FIELDS
        ):
            allowed = ", ".join(ARTIFACT_MEMORY_REF_FIELDS)
            raise LaunchError(
                _artifact_rule_error(
                    name,
                    f"memory_ref_field must be one of: {allowed}",
                    path=path,
                )
            )
        label = value.get("label")
        if label is not None and not isinstance(label, str):
            raise LaunchError(
                _artifact_rule_error(name, "label must be a string", path=path)
            )
        description = value.get("description")
        if description is not None and not isinstance(description, str):
            raise LaunchError(
                _artifact_rule_error(name, "description must be a string", path=path)
            )
        rules.append(
            ProjectArtifactRule(
                name=name,
                depends_on=tuple(depends_on),
                memory_ref_field=memory_ref_field,
                label=label,
                description=description,
            )
        )
    return tuple(rules)


def _validate_artifact_order_and_dependencies(
    artifact_rules: tuple[ProjectArtifactRule, ...],
    *,
    default_artifact_order: tuple[str, ...],
    path: Path | None = None,
) -> None:
    if not artifact_rules:
        return
    names = {rule.name for rule in artifact_rules}
    if len(names) != len(artifact_rules):
        raise LaunchError(
            _project_config_error("Artifact rule names must be unique.", path)
        )
    for rule in artifact_rules:
        for dependency in rule.depends_on:
            if dependency not in names:
                raise LaunchError(
                    _project_config_error(
                        "Artifact rule "
                        f"'{rule.name}' depends on unknown artifact "
                        f"'{dependency}'.",
                        path,
                    )
                )
    if default_artifact_order:
        unknown = [name for name in default_artifact_order if name not in names]
        if unknown:
            raise LaunchError(
                _project_config_error(
                    "default_artifact_order references unknown artifacts: "
                    + ", ".join(sorted(unknown)),
                    path,
                )
            )


def _artifact_rule_error(name: str, message: str, *, path: Path | None) -> str:
    return _project_config_error(f"Artifact rule '{name}' {message}.", path)


def _project_config_error(message: str, path: Path | None) -> str:
    if path is None:
        return message
    return f"{message} in {path}"


def _validate_prompt_profile(name: str, data: dict[str, object], path: Path) -> None:
    unknown_keys = set(data.keys()) - PROMPT_PROFILE_KEYS
    if unknown_keys:
        sorted_keys = ", ".join(sorted(unknown_keys))
        raise LaunchError(
            f"Unknown prompt profile keys in {path}: "
            f"prompt_profiles.{name}: {sorted_keys}"
        )
    profile = data.get("profile")
    if profile is not None and profile not in VALID_PROFILE_VALUES:
        raise LaunchError(
            f"Invalid profile value '{profile}' in prompt_profiles.{name} in {path}. "
            f"Valid: {', '.join(sorted(VALID_PROFILE_VALUES))}"
        )
    question_policy = data.get("question_policy")
    if (
        question_policy is not None
        and question_policy not in VALID_QUESTION_POLICY_VALUES
    ):
        raise LaunchError(
            f"Invalid question_policy '{question_policy}' "
            f"in prompt_profiles.{name} in {path}. "
            f"Valid: {', '.join(sorted(VALID_QUESTION_POLICY_VALUES))}"
        )
    todo_granularity = data.get("todo_granularity")
    if (
        todo_granularity is not None
        and todo_granularity not in VALID_TODO_GRANULARITY_VALUES
    ):
        raise LaunchError(
            f"Invalid todo_granularity '{todo_granularity}' "
            f"in prompt_profiles.{name} in {path}. "
            f"Valid: {', '.join(sorted(VALID_TODO_GRANULARITY_VALUES))}"
        )
    plan_body_detail = data.get("plan_body_detail")
    if (
        plan_body_detail is not None
        and plan_body_detail not in VALID_PLAN_BODY_DETAIL_VALUES
    ):
        raise LaunchError(
            f"Invalid plan_body_detail '{plan_body_detail}' "
            f"in prompt_profiles.{name} in {path}. "
            f"Valid: {', '.join(sorted(VALID_PLAN_BODY_DETAIL_VALUES))}"
        )
    for int_key in ("max_required_questions", "min_acceptance_criteria"):
        val = data.get(int_key)
        if val is not None and not isinstance(val, int):
            raise LaunchError(
                f"prompt_profiles.{name}.{int_key} must be an integer in {path}"
            )
        if val is not None and val < 1:
            raise LaunchError(
                f"prompt_profiles.{name}.{int_key} must be positive in {path}"
            )
    for bool_key in (
        "require_files",
        "require_test_commands",
        "require_expected_outputs",
        "require_validation_hints",
    ):
        val = data.get(bool_key)
        if val is not None and not isinstance(val, bool):
            raise LaunchError(
                f"prompt_profiles.{name}.{bool_key} must be a boolean in {path}"
            )
    topics = data.get("required_question_topics")
    if topics is not None:
        if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
            raise LaunchError(
                f"prompt_profiles.{name}.required_question_topics "
                f"must be a list of strings in {path}"
            )
    extra = data.get("extra_guidance")
    if extra is not None:
        if not isinstance(extra, str):
            raise LaunchError(
                f"prompt_profiles.{name}.extra_guidance must be a string in {path}"
            )
        if len(extra) > MAX_EXTRA_GUIDANCE_CHARS:
            raise LaunchError(
                f"prompt_profiles.{name}.extra_guidance exceeds "
                f"{MAX_EXTRA_GUIDANCE_CHARS} characters in {path}"
            )


def _parse_prompt_profile(
    raw: object, base: PromptProfile | None
) -> PromptProfile | None:
    if raw is None:
        return base
    if not isinstance(raw, dict):
        return base
    planning = raw.get("planning")
    if planning is None:
        return base
    if not isinstance(planning, dict):
        return base
    topics_raw = planning.get("required_question_topics")
    topics: tuple[str, ...] = ()
    if isinstance(topics_raw, (list, tuple)):
        topics = tuple(str(t) for t in topics_raw)
    return PromptProfile(
        name="planning",
        profile=str(planning.get("profile", "balanced")),
        question_policy=str(planning.get("question_policy", "ask_when_missing")),
        max_required_questions=int(planning.get("max_required_questions", 5)),
        min_acceptance_criteria=int(planning.get("min_acceptance_criteria", 1)),
        todo_granularity=str(planning.get("todo_granularity", "implementation_steps")),
        require_files=bool(planning.get("require_files", True)),
        require_test_commands=bool(planning.get("require_test_commands", True)),
        require_expected_outputs=bool(planning.get("require_expected_outputs", True)),
        require_validation_hints=bool(planning.get("require_validation_hints", True)),
        plan_body_detail=str(planning.get("plan_body_detail", "normal")),
        required_question_topics=topics,
        extra_guidance=(
            str(planning["extra_guidance"]) if "extra_guidance" in planning else None
        ),
    )


def _validate_agent_logging(raw: object, path: Path) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise LaunchError(
            f"Project config key 'agent_logging' must be a table in {path}"
        )
    unknown = set(raw.keys()) - AGENT_LOGGING_CONFIG_KEYS
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise LaunchError(f"Unknown agent_logging keys in {path}: {joined}")

    for key in (
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
    ):
        value = raw.get(key)
        if value is not None and not isinstance(value, bool):
            raise LaunchError(f"agent_logging.{key} must be a boolean in {path}")

    max_inline = raw.get("max_inline_chars")
    if max_inline is not None and (not isinstance(max_inline, int) or max_inline <= 0):
        raise LaunchError(
            f"agent_logging.max_inline_chars must be a positive integer in {path}"
        )

    max_artifact_bytes = raw.get("max_artifact_bytes")
    if max_artifact_bytes is not None and (
        not isinstance(max_artifact_bytes, int) or max_artifact_bytes <= 0
    ):
        raise LaunchError(
            f"agent_logging.max_artifact_bytes must be a positive integer in {path}"
        )

    redact_patterns = raw.get("redact_patterns")
    if redact_patterns is None:
        return
    if not isinstance(redact_patterns, list) or not all(
        isinstance(item, str) for item in redact_patterns
    ):
        raise LaunchError(
            f"agent_logging.redact_patterns must be a list of strings in {path}"
        )
    for pattern in redact_patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise LaunchError(
                f"Invalid regex in agent_logging.redact_patterns in {path}: {exc}"
            ) from exc


def _parse_agent_logging(
    raw: object,
    base: AgentLoggingConfig,
) -> AgentLoggingConfig:
    if raw is None or not isinstance(raw, dict):
        return base
    return AgentLoggingConfig(
        enabled=bool(raw.get("enabled", base.enabled)),
        capture_taskledger_cli=bool(
            raw.get("capture_taskledger_cli", base.capture_taskledger_cli)
        ),
        capture_managed_shell=bool(
            raw.get("capture_managed_shell", base.capture_managed_shell)
        ),
        capture_visible_stdout=bool(
            raw.get("capture_visible_stdout", base.capture_visible_stdout)
        ),
        capture_visible_stderr=bool(
            raw.get("capture_visible_stderr", base.capture_visible_stderr)
        ),
        capture_visible_combined=bool(
            raw.get("capture_visible_combined", base.capture_visible_combined)
        ),
        capture_payload_metadata=bool(
            raw.get("capture_payload_metadata", base.capture_payload_metadata)
        ),
        max_inline_chars=int(raw.get("max_inline_chars", base.max_inline_chars)),
        store_full_output_artifacts=bool(
            raw.get(
                "store_full_output_artifacts",
                base.store_full_output_artifacts,
            )
        ),
        max_artifact_bytes=cast(
            int | None,
            raw.get("max_artifact_bytes", base.max_artifact_bytes),
        ),
        fail_on_logging_error=bool(
            raw.get("fail_on_logging_error", base.fail_on_logging_error)
        ),
        redact_patterns=tuple(
            str(item) for item in raw.get("redact_patterns", base.redact_patterns)
        ),
        capture_safe_read_only=bool(
            raw.get("capture_safe_read_only", base.capture_safe_read_only)
        ),
        capture_human_oriented=bool(
            raw.get("capture_human_oriented", base.capture_human_oriented)
        ),
    )


def _validate_event_logging(raw: object, path: Path) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise LaunchError(
            f"Project config key 'event_logging' must be a table in {path}"
        )
    unknown = set(raw.keys()) - EVENT_LOGGING_CONFIG_KEYS
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise LaunchError(f"Unknown event_logging keys in {path}: {joined}")
    enabled = raw.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise LaunchError(f"event_logging.enabled must be a boolean in {path}")


def _parse_event_logging(
    raw: object,
    base: EventLoggingConfig,
) -> EventLoggingConfig:
    if raw is None or not isinstance(raw, dict):
        return base
    return EventLoggingConfig(
        enabled=bool(raw.get("enabled", base.enabled)),
    )
