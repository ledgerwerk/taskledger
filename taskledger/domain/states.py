from __future__ import annotations

from typing import Literal, cast

from taskledger.errors import LaunchError

TASKLEDGER_SCHEMA_VERSION = 1
TASKLEDGER_V2_FILE_VERSION = "v2"
TASKLEDGER_STORAGE_LAYOUT_VERSION = 3
TASKLEDGER_RECORD_SCHEMA_VERSION = TASKLEDGER_SCHEMA_VERSION
TASKLEDGER_TASK_FILE_VERSION = TASKLEDGER_V2_FILE_VERSION
OBJECT_TYPES = frozenset(
    {
        "task",
        "plan",
        "question",
        "run",
        "validation",
        "change",
        "code_review",
        "intro",
        "lock",
        "event",
        "todo",
        "todos",
        "link",
        "links",
        "requirement",
        "requirements",
        "handoff",
        "release",
        "bdd_feature",
        "bdd_rule",
        "bdd_example",
        "bdd_report",
    }
)

ActorType = Literal["agent", "user", "system"]
ActorRole = Literal["planner", "implementer", "validator", "reviewer", "operator"]
HarnessKind = Literal["agent_harness", "manual", "ci", "unknown"]
HandoffMode = Literal["planning", "implementation", "validation", "review", "full"]
ContextFor = Literal[
    "planner",
    "implementer",
    "validator",
    "reviewer",
    "spec-reviewer",
    "code-reviewer",
    "full",
]
ContextScope = Literal["task", "todo", "run"]
ContextFormat = Literal["markdown", "json", "text"]
HandoffStatus = Literal["open", "claimed", "closed", "cancelled"]
LockPolicy = Literal["none", "retain", "release", "transfer"]
TodoSource = Literal["user", "planner", "implementer", "plan"]
TaskType = Literal["managed", "recorded"]
TASK_TYPES = frozenset({"managed", "recorded"})

TaskStatusStage = Literal[
    "draft",
    "planning",
    "plan_review",
    "approved",
    "implementing",
    "implemented",
    "validating",
    "done",
    "failed_validation",
    "cancelled",
]
ActiveTaskStatusStage = Literal["planning", "implementing", "validating"]
RunType = Literal["planning", "implementation", "validation"]
PlanStatus = Literal["draft", "proposed", "accepted", "superseded", "rejected"]
QuestionStatus = Literal["open", "answered", "dismissed"]
RunStatus = Literal[
    "running", "paused", "finished", "passed", "failed", "blocked", "aborted"
]
ValidationResult = Literal["passed", "failed", "blocked"]
ValidationCheckStatus = Literal["pass", "fail", "warn", "not_run"]
FileLinkKind = Literal["code", "test", "doc", "config", "dir", "other", "artifact"]
TodoStatus = Literal["open", "active", "done", "blocked", "skipped"]
EventName = Literal[
    "task.created",
    "task.updated",
    "task.cancelled",
    "task.uncancelled",
    "stage.entered",
    "stage.completed",
    "stage.failed",
    "plan.started",
    "plan.proposed",
    "plan.approved",
    "plan.rejected",
    "plan.command",
    "question.added",
    "question.answered",
    "question.dismissed",
    "implementation.started",
    "implementation.logged",
    "implementation.finished",
    "validation.started",
    "validation.finished",
    "change.logged",
    "todo.added",
    "todo.toggled",
    "todo.started",
    "todo.blocked",
    "todo.skipped",
    "todo.completed",
    "lock.acquired",
    "lock.released",
    "lock.broken",
    "lock.transferred",
    "handoff.created",
    "handoff.claimed",
    "handoff.closed",
    "handoff.cancelled",
    "release.tagged",
    "run.paused",
    "run.resumed",
    "actor.resolved",
    "doctor.reindexed",
    "task.recorded",
    "code_review.recorded",
    "file.linked",
    "file.baseline_refreshed",
]

ACTIVE_TASK_STAGES = frozenset({"planning", "implementing", "validating"})
DURABLE_TASK_STATUSES = frozenset(
    {
        "draft",
        "plan_review",
        "approved",
        "implemented",
        "failed_validation",
        "done",
        "cancelled",
    }
)
RUN_TYPES = frozenset({"planning", "implementation", "validation"})
RUN_STATUSES = frozenset(
    {"running", "paused", "finished", "passed", "failed", "blocked", "aborted"}
)
VALIDATION_CHECK_STATUSES = frozenset({"pass", "fail", "warn", "not_run"})
IMPLEMENTABLE_TASK_STAGES = frozenset({"approved", "failed_validation"})
CANCELLABLE_TASK_STAGES = frozenset(ACTIVE_TASK_STAGES) | {
    "draft",
    "plan_review",
    "approved",
    "implemented",
    "failed_validation",
}

ALLOWED_STAGE_TRANSITIONS: dict[TaskStatusStage, frozenset[TaskStatusStage]] = {
    "draft": frozenset({"plan_review", "cancelled"}),
    "planning": frozenset({"plan_review", "cancelled"}),
    "plan_review": frozenset({"draft", "approved", "cancelled"}),
    "approved": frozenset({"implemented", "cancelled"}),
    "implementing": frozenset({"implemented", "cancelled"}),
    "implemented": frozenset({"done", "failed_validation", "cancelled"}),
    "validating": frozenset({"done", "failed_validation", "cancelled"}),
    "failed_validation": frozenset(
        {"implementing", "approved", "plan_review", "cancelled"}
    ),
    "done": frozenset(),
    "cancelled": frozenset(),
}

EXIT_CODE_SUCCESS = 0
EXIT_CODE_GENERIC_FAILURE = 1
EXIT_CODE_BAD_INPUT = 2
EXIT_CODE_WORKFLOW_REJECTION = 3
EXIT_CODE_LOCK_CONFLICT = 4
EXIT_CODE_MISSING = 5
EXIT_CODE_DATA_INTEGRITY = 6
EXIT_CODE_STORAGE_ERROR = 6
EXIT_CODE_VALIDATION_FAILED = 7
EXIT_CODE_INVALID_TRANSITION = EXIT_CODE_WORKFLOW_REJECTION
EXIT_CODE_APPROVAL_REQUIRED = EXIT_CODE_WORKFLOW_REJECTION
EXIT_CODE_DEPENDENCY_BLOCKED = EXIT_CODE_WORKFLOW_REJECTION
EXIT_CODE_STALE_LOCK_REQUIRES_BREAK = EXIT_CODE_LOCK_CONFLICT
EXIT_CODE_INDEX_REBUILD_FAILED = EXIT_CODE_STORAGE_ERROR


def is_active_stage(stage: TaskStatusStage) -> bool:
    return stage in ACTIVE_TASK_STAGES


def can_transition(current: TaskStatusStage, target: TaskStatusStage) -> bool:
    return target in ALLOWED_STAGE_TRANSITIONS[current]


def require_transition(current: TaskStatusStage, target: TaskStatusStage) -> None:
    if can_transition(current, target):
        return
    raise LaunchError(f"Invalid stage transition: {current} -> {target}")


def normalize_task_status_stage(value: str) -> TaskStatusStage:
    if value not in ALLOWED_STAGE_TRANSITIONS:
        raise LaunchError(f"Unsupported task stage: {value}")
    return value


def normalize_run_type(value: str) -> RunType:
    if value not in {"planning", "implementation", "validation"}:
        raise LaunchError(f"Unsupported run type: {value}")
    return cast(RunType, value)


def normalize_plan_status(value: str) -> PlanStatus:
    if value not in {"draft", "proposed", "accepted", "superseded", "rejected"}:
        raise LaunchError(f"Unsupported plan status: {value}")
    return cast(PlanStatus, value)


def normalize_question_status(value: str) -> QuestionStatus:
    if value not in {"open", "answered", "dismissed"}:
        raise LaunchError(f"Unsupported question status: {value}")
    return cast(QuestionStatus, value)


def normalize_run_status(value: str) -> RunStatus:
    if value not in {
        "running",
        "paused",
        "finished",
        "passed",
        "failed",
        "blocked",
        "aborted",
    }:
        raise LaunchError(f"Unsupported run status: {value}")
    return cast(RunStatus, value)


def normalize_validation_result(value: str) -> ValidationResult:
    if value not in {"passed", "failed", "blocked"}:
        raise LaunchError(f"Unsupported validation result: {value}")
    return cast(ValidationResult, value)


def normalize_validation_check_status(value: str) -> ValidationCheckStatus:
    normalized = "not_run" if value == "skip" else value
    if normalized not in {"pass", "fail", "warn", "not_run"}:
        raise LaunchError(f"Unsupported validation check status: {value}")
    return cast(ValidationCheckStatus, normalized)


def normalize_file_link_kind(value: str) -> FileLinkKind:
    normalized = "dir" if value == "directory" else value
    if normalized not in {"code", "test", "doc", "config", "dir", "other", "artifact"}:
        raise LaunchError(f"Unsupported file link kind: {value}")
    return cast(FileLinkKind, normalized)


def normalize_todo_status(value: str) -> TodoStatus:
    if value not in {"open", "active", "done", "blocked", "skipped"}:
        raise LaunchError(f"Unsupported todo status: {value}")
    return cast(TodoStatus, value)


TODO_STATUSES = frozenset({"open", "active", "done", "blocked", "skipped"})


def normalize_task_type(value: str) -> TaskType:
    if value not in TASK_TYPES:
        raise LaunchError(f"Unsupported task type: {value}")
    return cast(TaskType, value)


def normalize_actor_type(value: str) -> ActorType:
    if value not in {"agent", "user", "system"}:
        raise LaunchError(f"Unsupported actor type: {value!r}")
    return cast(ActorType, value)


def normalize_actor_role(value: str) -> ActorRole:
    if value not in {"planner", "implementer", "validator", "reviewer", "operator"}:
        raise LaunchError(f"Unsupported actor role: {value!r}")
    return cast(ActorRole, value)


def normalize_harness_kind(value: str) -> HarnessKind:
    if value not in {"agent_harness", "manual", "ci", "unknown"}:
        raise LaunchError(f"Unsupported harness kind: {value!r}")
    return cast(HarnessKind, value)


def normalize_handoff_mode(value: str) -> HandoffMode:
    if value not in {"planning", "implementation", "validation", "review", "full"}:
        raise LaunchError(f"Unsupported handoff mode: {value!r}")
    return cast(HandoffMode, value)


def normalize_context_for(value: str) -> ContextFor:
    normalized = {
        "planning": "planner",
        "implementation": "implementer",
        "validation": "validator",
        "review": "reviewer",
        "spec": "spec-reviewer",
        "code": "code-reviewer",
    }.get(value, value)
    if normalized not in {
        "planner",
        "implementer",
        "validator",
        "reviewer",
        "spec-reviewer",
        "code-reviewer",
        "full",
    }:
        raise LaunchError(f"Unsupported context role: {value!r}")
    return cast(ContextFor, normalized)


def normalize_context_scope(value: str) -> ContextScope:
    if value not in {"task", "todo", "run"}:
        raise LaunchError(f"Unsupported context scope: {value!r}")
    return cast(ContextScope, value)


def normalize_context_format(value: str) -> ContextFormat:
    if value not in {"markdown", "json", "text"}:
        raise LaunchError(f"Unsupported context format: {value!r}")
    return cast(ContextFormat, value)


def normalize_handoff_status(value: str) -> HandoffStatus:
    if value not in {"open", "claimed", "closed", "cancelled"}:
        raise LaunchError(f"Unsupported handoff status: {value!r}")
    return cast(HandoffStatus, value)


def normalize_lock_policy(value: str) -> LockPolicy:
    if value not in {"none", "retain", "release", "transfer"}:
        raise LaunchError(f"Unsupported lock policy: {value!r}")
    return cast(LockPolicy, value)
