"""Implementation check records for verification commands (pytest, ruff, mypy, etc.)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from taskledger.domain._model_utils import (
    _int_value,
    _optional_int,
    _optional_string,
    _require_contract,
    _string_tuple,
    _string_value,
)
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
)
from taskledger.errors import LaunchError
from taskledger.timeutils import utc_now_iso


@dataclass(slots=True, frozen=True)
class ImplementationCheckRecord:
    check_id: str
    task_id: str
    implementation_run: str
    timestamp: str
    command: str
    argv: tuple[str, ...] = ()
    exit_code: int | None = None
    cwd: str | None = None
    workspace_git_commit: str | None = None
    workspace_content_hash: str | None = None
    workspace_paths_hash: str | None = None
    workspace_entry_count: int | None = None
    workspace_snapshot_format: str | None = None
    status: Literal["passed", "failed", "unknown"] = "unknown"
    category: Literal[
        "test", "lint", "format", "typecheck", "build", "security", "other"
    ] = "other"
    summary: str | None = None
    stdout_ref: str | None = None
    stderr_ref: str | None = None
    combined_ref: str | None = None
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "implementation_check"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "check_id": self.check_id,
            "task_id": self.task_id,
            "implementation_run": self.implementation_run,
            "timestamp": self.timestamp,
            "command": self.command,
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "cwd": self.cwd,
            "workspace_git_commit": self.workspace_git_commit,
            "workspace_content_hash": self.workspace_content_hash,
            "workspace_paths_hash": self.workspace_paths_hash,
            "workspace_entry_count": self.workspace_entry_count,
            "workspace_snapshot_format": self.workspace_snapshot_format,
            "status": self.status,
            "category": self.category,
            "summary": self.summary,
            "stdout_ref": self.stdout_ref,
            "stderr_ref": self.stderr_ref,
            "combined_ref": self.combined_ref,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ImplementationCheckRecord:
        _require_contract(data, expected_object_type="implementation_check")
        status = _optional_string(data.get("status")) or "unknown"
        if status not in {"passed", "failed", "unknown"}:
            raise LaunchError(f"Unsupported check status: {status}")
        category = _optional_string(data.get("category")) or "other"
        if category not in {
            "test",
            "lint",
            "format",
            "typecheck",
            "build",
            "security",
            "other",
        }:
            raise LaunchError(f"Unsupported check category: {category}")
        return cls(
            check_id=_string_value(data, "check_id"),
            task_id=_string_value(data, "task_id"),
            implementation_run=_string_value(data, "implementation_run"),
            timestamp=_optional_string(data.get("timestamp")) or utc_now_iso(),
            command=_string_value(data, "command"),
            argv=_string_tuple(data.get("argv")),
            cwd=_optional_string(data.get("cwd")),
            workspace_git_commit=_optional_string(data.get("workspace_git_commit")),
            workspace_content_hash=_optional_string(data.get("workspace_content_hash")),
            workspace_paths_hash=_optional_string(data.get("workspace_paths_hash")),
            workspace_entry_count=_optional_int(data.get("workspace_entry_count")),
            workspace_snapshot_format=_optional_string(
                data.get("workspace_snapshot_format")
            ),
            exit_code=_optional_int(data.get("exit_code")),
            status=cast(Literal["passed", "failed", "unknown"], status),
            category=cast(
                Literal[
                    "test",
                    "lint",
                    "format",
                    "typecheck",
                    "build",
                    "security",
                    "other",
                ],
                category,
            ),
            summary=_optional_string(data.get("summary")),
            stdout_ref=_optional_string(data.get("stdout_ref")),
            stderr_ref=_optional_string(data.get("stderr_ref")),
            combined_ref=_optional_string(data.get("combined_ref")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )
