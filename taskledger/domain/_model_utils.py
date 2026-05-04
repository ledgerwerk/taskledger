from __future__ import annotations

from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
    TaskStatusStage,
    normalize_task_status_stage,
)
from taskledger.errors import LaunchError
from taskledger.timeutils import utc_now_iso


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_parent_relation(value: object) -> str | None:
    relation = _optional_string(value)
    if relation is None:
        return None
    if relation != "follow_up":
        raise LaunchError(f"Unsupported task parent_relation: {relation}")
    return relation


def _optional_list_string(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, str)] or None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _string_value(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise LaunchError(f"Missing or invalid '{key}' value.")
    return value


def _int_value(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise LaunchError(f"Missing or invalid '{key}' value.")
    return value


def _first_string(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, str):
            return item
    return None


def _plan_id(version: int) -> str:
    return f"plan-v{version}"


def _plan_version_from_id(value: str | None) -> int | None:
    if value is None or not value.startswith("plan-v"):
        return None
    suffix = value.removeprefix("plan-v")
    return int(suffix) if suffix.isdigit() else None


def _plan_version_value(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return _plan_version_from_id(value)
    return None


def _lock_stage_from_data(data: dict[str, object]) -> TaskStatusStage:
    stage = _optional_string(data.get("stage"))
    if stage is None:
        run_type = _optional_string(data.get("run_type"))
        stage = {
            "planning": "planning",
            "implementation": "implementing",
            "validation": "validating",
        }.get(run_type or "")
    if stage is None:
        raise LaunchError("Missing or invalid 'stage' value.")
    return normalize_task_status_stage(stage)


def _generated_event_id() -> str:
    timestamp = utc_now_iso().replace(":", "").replace("-", "").replace("+00:00", "Z")
    return f"evt-{timestamp}"


def _require_contract(data: dict[str, object], *, expected_object_type: str) -> None:
    version = data.get("schema_version")
    if not isinstance(version, int) or version > TASKLEDGER_SCHEMA_VERSION:
        raise LaunchError(
            "Unsupported schema version: "
            f"expected <= {TASKLEDGER_SCHEMA_VERSION}, got {version!r}."
        )
    object_type = _optional_string(data.get("object_type"))
    if object_type != expected_object_type:
        raise LaunchError(
            "Missing or invalid 'object_type': "
            f"expected {expected_object_type!r}, got {object_type!r}."
        )
    if "file_version" in data:
        _require_v2_file_version(data)


def _int_or_default(value: object, default: int) -> int:
    return value if isinstance(value, int) else default


def _require_v2_file_version(data: dict[str, object]) -> None:
    version = _optional_string(data.get("file_version"))
    if version != TASKLEDGER_V2_FILE_VERSION:
        raise LaunchError(
            "Unsupported file version: "
            f"expected {TASKLEDGER_V2_FILE_VERSION}, got {version!r}."
        )


def _require_sidecar_contract(
    data: dict[str, object], *, expected_object_type: str
) -> None:
    """Enforce version compatibility for sidecar models read from v2 files.

    When schema_version or object_type are present, validate them.
    When absent (legacy YAML sidecar reads), skip enforcement.
    """
    version = data.get("schema_version")
    if isinstance(version, int) and version > TASKLEDGER_SCHEMA_VERSION:
        raise LaunchError(
            f"Record schema too new: {version} "
            f"(current max: {TASKLEDGER_SCHEMA_VERSION}). "
            "Please upgrade taskledger."
        )
    obj_type = _optional_string(data.get("object_type"))
    if obj_type is not None and obj_type != expected_object_type:
        raise LaunchError(
            f"Invalid object_type: expected {expected_object_type!r}, got {obj_type!r}."
        )
    file_ver = _optional_string(data.get("file_version"))
    if file_ver is not None and file_ver != TASKLEDGER_V2_FILE_VERSION:
        raise LaunchError(
            "Unsupported file version: "
            f"expected {TASKLEDGER_V2_FILE_VERSION}, got {file_ver!r}."
        )
