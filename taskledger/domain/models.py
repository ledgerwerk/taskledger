from __future__ import annotations

from taskledger.domain.active_state import (
    ActiveActorState,
    ActiveHarnessState,
    ActiveTaskState,
)
from taskledger.domain.actor import ActorRef, HarnessRef
from taskledger.domain.change import AgentCommandLogRecord, CodeChangeRecord
from taskledger.domain.event import TaskEvent
from taskledger.domain.handoff import TaskHandoffRecord
from taskledger.domain.lock import TaskLock
from taskledger.domain.plan import PlanRecord
from taskledger.domain.question import QuestionRecord
from taskledger.domain.release import ReleaseRecord
from taskledger.domain.run import TaskRunRecord
from taskledger.domain.sidecars import (
    AcceptanceCriterion,
    CriterionWaiver,
    DependencyRequirement,
    DependencyWaiver,
    FileLink,
    LinkCollection,
    RequirementCollection,
    TaskTodo,
    TodoCollection,
    ValidationCheck,
)

# Compatibility facade: re-export domain record types and selected state symbols.
# ruff: noqa: F401
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
    ActiveTaskStatusStage,
    ContextFor,
    ContextFormat,
    ContextScope,
    FileLinkKind,
    PlanStatus,
    QuestionStatus,
    RunStatus,
    RunType,
    TaskStatusStage,
    TaskType,
    ValidationCheckStatus,
    ValidationResult,
    normalize_actor_role,
    normalize_actor_type,
    normalize_context_for,
    normalize_context_format,
    normalize_context_scope,
    normalize_file_link_kind,
    normalize_handoff_mode,
    normalize_handoff_status,
    normalize_harness_kind,
    normalize_lock_policy,
    normalize_plan_status,
    normalize_question_status,
    normalize_run_status,
    normalize_run_type,
    normalize_task_status_stage,
    normalize_task_type,
    normalize_validation_check_status,
    normalize_validation_result,
)
from taskledger.domain.task import IntroductionRecord, TaskRecord
from taskledger.errors import LaunchError
from taskledger.timeutils import utc_now_iso
