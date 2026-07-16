from __future__ import annotations

from collections.abc import Mapping, Sequence

STORAGE_ERROR_CODES = frozenset(
    {
        "TASKLEDGER_MIGRATION_REQUIRED",
        "TASKLEDGER_REGISTRATION_MISSING",
        "TASKLEDGER_REGISTRATION_CONFLICT",
        "TASKLEDGER_WORKSPACE_ENV_UNSUPPORTED",
        "TASKLEDGER_WORKSPACE_ROOT_CONFLICT",
        "TASKLEDGER_WORKSPACE_PROVIDER_CONFLICT",
        "TASKLEDGER_SIBLING_PROVIDER_REQUIRED",
        "TASKLEDGER_SIBLING_ROOT_MISSING",
        "TASKLEDGER_SIBLING_ROOT_NOT_DIRECTORY",
        "TASKLEDGER_SIBLING_ROOT_UNMARKED",
        "TASKLEDGER_SIBLING_MARKER_INVALID",
        "TASKLEDGER_DIRECT_PATH_MISMATCH",
        "TASKLEDGER_UUID_PATH_MISMATCH",
        "TASKLEDGER_BINDING_MISSING",
        "TASKLEDGER_BINDING_UUID_MISMATCH",
        "TASKLEDGER_BINDING_LEDGER_MISMATCH",
        "TASKLEDGER_BINDING_MOUNT_MISMATCH",
        "TASKLEDGER_STORAGE_LAYOUT_OLD",
        "TASKLEDGER_STATE_SCHEMA_OLD",
        "TASKLEDGER_TASK_ALLOCATION_INVALID",
        "TASKLEDGER_MIGRATION_AMBIGUOUS",
        "TASKLEDGER_DESTINATION_CONFLICT",
        "TASKLEDGER_PARTIAL_MIGRATION",
    }
)


def error_exit_code_for_code(code: str) -> int | None:
    if code == "TASKLEDGER_CANONICAL_SYNC_PATH_FIXED":
        return 2
    if code in STORAGE_ERROR_CODES:
        return 6
    if code == "TASKLEDGER_PROJECT_NOT_FOUND":
        return 5
    return None


class TaskledgerError(Exception):
    """Base class for public taskledger errors."""

    code = "TASKLEDGER_ERROR"
    exit_code = 1
    error_type = "TaskledgerError"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        exit_code: int | None = None,
        error_type: str | None = None,
        remediation: Sequence[str] | None = None,
        details: Mapping[str, object] | None = None,
        data: Mapping[str, object] | None = None,
        task_id: str | None = None,
        blocking_refs: Sequence[str] | None = None,
    ) -> None:
        super().__init__(message)
        prefix = message.split(":", 1)[0]
        inferred_code = prefix if prefix.startswith("TASKLEDGER_") else None
        resolved_code = code if code is not None else inferred_code or self.code
        mapped_exit_code = error_exit_code_for_code(resolved_code)
        resolved_exit_code = exit_code if exit_code is not None else self.exit_code
        if exit_code is None and self.exit_code == 1 and mapped_exit_code is not None:
            resolved_exit_code = mapped_exit_code
        resolved_error_type = error_type if error_type is not None else self.error_type
        resolved_details = dict(details or data or {})
        resolved_blocking_refs = tuple(str(item) for item in (blocking_refs or ()))

        self.code = resolved_code
        self.message = message
        self.exit_code = resolved_exit_code
        self.error_type = resolved_error_type
        self.details = resolved_details
        self.task_id = task_id
        self.blocking_refs = resolved_blocking_refs
        self.remediation = [str(item) for item in remediation or ()]

        self.taskledger_exit_code = resolved_exit_code
        self.taskledger_error_code = resolved_code
        if error_type is not None:
            self.taskledger_error_type = error_type
        else:
            self.taskledger_error_type = resolved_error_type
        self.taskledger_remediation = list(self.remediation)
        self.taskledger_data = self.to_error_payload()

    def to_error_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            payload["details"] = dict(self.details)
        if self.task_id is not None:
            payload["task_id"] = self.task_id
        if self.blocking_refs:
            payload["blocking_refs"] = list(self.blocking_refs)
        return payload


class UnsupportedAgentError(TaskledgerError):
    """Raised when the requested agent is not supported."""

    code = "UNSUPPORTED_AGENT"


class AgentNotInstalledError(TaskledgerError):
    """Raised when the requested agent executable is not available."""

    code = "AGENT_NOT_INSTALLED"


class LaunchError(TaskledgerError):
    """Raised when the child process cannot be prepared or started."""

    code = "LAUNCH_ERROR"
    error_type = "LaunchError"


class OptionalCommandGroupUnavailable(LaunchError):
    code = "OPTIONAL_COMMAND_GROUP_UNAVAILABLE"
    error_type = "OptionalCommandGroupUnavailable"


class NoActiveTask(LaunchError):
    code = "NO_ACTIVE_TASK"
    exit_code = 5
    error_type = "NoActiveTask"

    def __init__(self) -> None:
        super().__init__(
            "No active task is set. Run `taskledger task activate <task-ref>` "
            "or pass `--task <task-ref>`.",
            remediation=[
                "Run `taskledger task list` to find a task.",
                "Run `taskledger task activate <task-ref>` to set the active task.",
                "Or pass `--task <task-ref>` to this command.",
            ],
        )


class InvalidPromptError(TaskledgerError):
    """Raised when prompt input is empty or invalid."""

    code = "INVALID_INPUT"
    exit_code = 2
    error_type = "ValidationError"


class NotFound(TaskledgerError):
    code = "NOT_FOUND"
    exit_code = 5
    error_type = "NotFound"


class ValidationError(TaskledgerError):
    code = "VALIDATION_FAILED"
    exit_code = 7
    error_type = "ValidationError"


class InvalidStageTransition(TaskledgerError):
    code = "INVALID_STAGE_TRANSITION"
    exit_code = 3
    error_type = "InvalidStageTransition"


class ApprovalRequired(TaskledgerError):
    code = "APPROVAL_REQUIRED"
    exit_code = 3
    error_type = "ApprovalRequired"


class DependencyIncomplete(TaskledgerError):
    code = "DEPENDENCY_INCOMPLETE"
    exit_code = 3
    error_type = "DependencyIncomplete"


class LockConflict(LaunchError):
    code = "LOCK_CONFLICT"
    exit_code = 4
    error_type = "LockConflict"


class StaleLockRequiresBreak(TaskledgerError):
    code = "STALE_LOCK_REQUIRES_BREAK"
    exit_code = 4
    error_type = "StaleLockRequiresBreak"


class StorageCorruption(LaunchError):
    code = "STORAGE_CORRUPTION"
    exit_code = 6
    error_type = "StorageCorruption"


class ActiveTaskNotFound(StorageCorruption):
    code = "ACTIVE_TASK_NOT_FOUND"
    error_type = "StorageCorruption"


class IndexRebuildFailed(TaskledgerError):
    code = "INDEX_REBUILD_FAILED"
    exit_code = 6
    error_type = "IndexRebuildFailed"
