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
from taskledger.domain.actor import ActorRef, HarnessRef
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
)
from taskledger.errors import LaunchError
from taskledger.timeutils import utc_now_iso


@dataclass(slots=True, frozen=True)
class CodeChangeRecord:
    change_id: str
    task_id: str
    implementation_run: str
    timestamp: str
    kind: str
    path: str
    summary: str
    git_commit: str | None = None
    git_diff_stat: str | None = None
    command: str | None = None
    before_hash: str | None = None
    after_hash: str | None = None
    exit_code: int | None = None
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "change"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "change_id": self.change_id,
            "task_id": self.task_id,
            "implementation_run": self.implementation_run,
            "timestamp": self.timestamp,
            "kind": self.kind,
            "path": self.path,
            "summary": self.summary,
            "git_commit": self.git_commit,
            "git_diff_stat": self.git_diff_stat,
            "command": self.command,
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "exit_code": self.exit_code,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> CodeChangeRecord:
        _require_contract(data, expected_object_type="change")
        return cls(
            change_id=_string_value(data, "change_id"),
            task_id=_string_value(data, "task_id"),
            implementation_run=_string_value(data, "implementation_run"),
            timestamp=_optional_string(data.get("timestamp")) or utc_now_iso(),
            kind=_string_value(data, "kind"),
            path=_string_value(data, "path"),
            summary=_string_value(data, "summary"),
            git_commit=_optional_string(data.get("git_commit")),
            git_diff_stat=_optional_string(data.get("git_diff_stat")),
            command=_optional_string(data.get("command")),
            before_hash=_optional_string(data.get("before_hash")),
            after_hash=_optional_string(data.get("after_hash")),
            exit_code=_optional_int(data.get("exit_code")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )


@dataclass(slots=True, frozen=True)
class AgentCommandLogRecord:
    log_id: str
    ledger_ref: str
    started_at: str
    finished_at: str
    duration_ms: int

    command_kind: Literal["taskledger_cli", "managed_shell"]
    argv: tuple[str, ...]
    command_line: str
    cwd: str

    exit_code: int | None = None
    status: Literal["succeeded", "failed", "unknown"] = "unknown"

    task_id: str | None = None
    run_id: str | None = None
    run_type: str | None = None
    active_stage: str | None = None

    actor: ActorRef | None = None
    harness: HarnessRef | None = None

    json_output: bool = False
    operation_name: str | None = None

    visible_stdout_ref: str | None = None
    visible_stderr_ref: str | None = None
    visible_combined_ref: str | None = None
    visible_stdout_excerpt: str | None = None
    visible_stderr_excerpt: str | None = None
    visible_combined_excerpt: str | None = None

    managed_stdout_ref: str | None = None
    managed_stderr_ref: str | None = None
    managed_combined_ref: str | None = None
    managed_command_exit_code: int | None = None

    payload_ref: str | None = None
    payload_kind: str | None = None
    error_code: str | None = None
    error_summary: str | None = None

    redactions_applied: tuple[str, ...] = ()

    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "agent_command_log"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "log_id": self.log_id,
            "ledger_ref": self.ledger_ref,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "command_kind": self.command_kind,
            "argv": list(self.argv),
            "command_line": self.command_line,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "status": self.status,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "run_type": self.run_type,
            "active_stage": self.active_stage,
            "actor": self.actor.to_dict() if self.actor is not None else None,
            "harness": self.harness.to_dict() if self.harness is not None else None,
            "json_output": self.json_output,
            "operation_name": self.operation_name,
            "visible_stdout_ref": self.visible_stdout_ref,
            "visible_stderr_ref": self.visible_stderr_ref,
            "visible_combined_ref": self.visible_combined_ref,
            "visible_stdout_excerpt": self.visible_stdout_excerpt,
            "visible_stderr_excerpt": self.visible_stderr_excerpt,
            "visible_combined_excerpt": self.visible_combined_excerpt,
            "managed_stdout_ref": self.managed_stdout_ref,
            "managed_stderr_ref": self.managed_stderr_ref,
            "managed_combined_ref": self.managed_combined_ref,
            "managed_command_exit_code": self.managed_command_exit_code,
            "payload_ref": self.payload_ref,
            "payload_kind": self.payload_kind,
            "error_code": self.error_code,
            "error_summary": self.error_summary,
            "redactions_applied": list(self.redactions_applied),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AgentCommandLogRecord:
        _require_contract(data, expected_object_type="agent_command_log")
        command_kind = _string_value(data, "command_kind")
        if command_kind not in {"taskledger_cli", "managed_shell"}:
            raise LaunchError(f"Unsupported command_kind: {command_kind}")
        status = _optional_string(data.get("status")) or "unknown"
        if status not in {"succeeded", "failed", "unknown"}:
            raise LaunchError(f"Unsupported command status: {status}")
        argv = _string_tuple(data.get("argv"))
        command_line = _optional_string(data.get("command_line")) or " ".join(argv)
        command_line = command_line.strip()
        if not command_line:
            raise LaunchError("Missing or invalid 'command_line' value.")
        return cls(
            log_id=_string_value(data, "log_id"),
            ledger_ref=_string_value(data, "ledger_ref"),
            started_at=_string_value(data, "started_at"),
            finished_at=_string_value(data, "finished_at"),
            duration_ms=_int_value(data, "duration_ms"),
            command_kind=cast(
                Literal["taskledger_cli", "managed_shell"],
                command_kind,
            ),
            argv=argv,
            command_line=command_line,
            cwd=_string_value(data, "cwd"),
            exit_code=_optional_int(data.get("exit_code")),
            status=cast(Literal["succeeded", "failed", "unknown"], status),
            task_id=_optional_string(data.get("task_id")),
            run_id=_optional_string(data.get("run_id")),
            run_type=_optional_string(data.get("run_type")),
            active_stage=_optional_string(data.get("active_stage")),
            actor=ActorRef.from_dict(data.get("actor"))
            if data.get("actor") is not None
            else None,
            harness=HarnessRef.from_dict(data.get("harness"))
            if data.get("harness") is not None
            else None,
            json_output=bool(data.get("json_output", False)),
            operation_name=_optional_string(data.get("operation_name")),
            visible_stdout_ref=_optional_string(data.get("visible_stdout_ref")),
            visible_stderr_ref=_optional_string(data.get("visible_stderr_ref")),
            visible_combined_ref=_optional_string(data.get("visible_combined_ref")),
            visible_stdout_excerpt=_optional_string(data.get("visible_stdout_excerpt")),
            visible_stderr_excerpt=_optional_string(data.get("visible_stderr_excerpt")),
            visible_combined_excerpt=_optional_string(
                data.get("visible_combined_excerpt")
            ),
            managed_stdout_ref=_optional_string(data.get("managed_stdout_ref")),
            managed_stderr_ref=_optional_string(data.get("managed_stderr_ref")),
            managed_combined_ref=_optional_string(data.get("managed_combined_ref")),
            managed_command_exit_code=_optional_int(
                data.get("managed_command_exit_code")
            ),
            payload_ref=_optional_string(data.get("payload_ref")),
            payload_kind=_optional_string(data.get("payload_kind")),
            error_code=_optional_string(data.get("error_code")),
            error_summary=_optional_string(data.get("error_summary")),
            redactions_applied=_string_tuple(data.get("redactions_applied")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )
