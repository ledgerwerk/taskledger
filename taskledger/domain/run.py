from __future__ import annotations

from dataclasses import dataclass, field

from taskledger.domain._model_utils import (
    _dict_list,
    _int_value,
    _optional_int,
    _optional_string,
    _plan_id,
    _plan_version_value,
    _require_contract,
    _string_tuple,
    _string_value,
)
from taskledger.domain.actor import ActorRef, HarnessRef
from taskledger.domain.sidecars import ValidationCheck
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
    RunStatus,
    RunType,
    ValidationResult,
    normalize_run_status,
    normalize_run_type,
    normalize_validation_result,
)
from taskledger.timeutils import utc_now_iso


@dataclass(slots=True, frozen=True)
class TaskRunRecord:
    run_id: str
    task_id: str
    run_type: RunType
    status: RunStatus = "running"
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None
    actor: ActorRef = field(default_factory=ActorRef)
    harness: HarnessRef | None = None
    based_on_plan_version: int | None = None
    based_on_implementation_run: str | None = None
    resumes_run_id: str | None = None
    summary: str | None = None
    worklog: tuple[str, ...] = ()
    deviations_from_plan: tuple[str, ...] = ()
    change_refs: tuple[str, ...] = ()
    check_refs: tuple[str, ...] = ()
    todo_updates: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    checks: tuple[ValidationCheck, ...] = ()
    evidence: tuple[str, ...] = ()
    recommendation: str | None = None
    result: ValidationResult | None = None
    handoff_refs: tuple[str, ...] = ()
    actor_history: tuple[ActorRef, ...] = ()
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    based_on_plan: str | None = None
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "run"
    workspace_git_commit: str | None = None
    workspace_dirty: bool | None = None
    workspace_diff_hash: str | None = None
    workspace_status_hash: str | None = None
    workspace_snapshot_at: str | None = None
    workspace_content_hash: str | None = None
    workspace_paths_hash: str | None = None
    workspace_entry_count: int | None = None
    workspace_snapshot_format: str | None = None
    workspace_snapshot_ref: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "run_type": self.run_type,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "actor": self.actor.to_dict(),
            "harness": self.harness.to_dict() if self.harness is not None else None,
            "based_on_plan": self.based_on_plan or self.plan_ref,
            "based_on_plan_version": self.based_on_plan_version,
            "based_on_implementation_run": self.based_on_implementation_run,
            "resumes_run_id": self.resumes_run_id,
            "summary": self.summary,
            "worklog": list(self.worklog),
            "deviations_from_plan": list(self.deviations_from_plan),
            "change_refs": list(self.change_refs),
            "check_refs": list(self.check_refs),
            "todo_updates": list(self.todo_updates),
            "artifact_refs": list(self.artifact_refs),
            "checks": [item.to_dict() for item in self.checks],
            "evidence": list(self.evidence),
            "recommendation": self.recommendation,
            "result": self.result,
            "handoff_refs": list(self.handoff_refs),
            "actor_history": [item.to_dict() for item in self.actor_history],
            "workspace_git_commit": self.workspace_git_commit,
            "workspace_dirty": self.workspace_dirty,
            "workspace_diff_hash": self.workspace_diff_hash,
            "workspace_status_hash": self.workspace_status_hash,
            "workspace_snapshot_at": self.workspace_snapshot_at,
            "workspace_content_hash": self.workspace_content_hash,
            "workspace_paths_hash": self.workspace_paths_hash,
            "workspace_entry_count": self.workspace_entry_count,
            "workspace_snapshot_format": self.workspace_snapshot_format,
            "workspace_snapshot_ref": self.workspace_snapshot_ref,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TaskRunRecord:
        _require_contract(data, expected_object_type="run")
        result = _optional_string(data.get("result"))
        return cls(
            run_id=_string_value(data, "run_id"),
            task_id=_string_value(data, "task_id"),
            run_type=normalize_run_type(_string_value(data, "run_type")),
            status=normalize_run_status(_string_value(data, "status")),
            started_at=_optional_string(data.get("started_at")) or utc_now_iso(),
            finished_at=_optional_string(data.get("finished_at")),
            actor=ActorRef.from_dict(data.get("actor")),
            harness=HarnessRef.from_dict(data.get("harness"))
            if data.get("harness") is not None
            else None,
            based_on_plan_version=_optional_int(data.get("based_on_plan_version"))
            or _plan_version_value(data.get("based_on_plan")),
            based_on_implementation_run=_optional_string(
                data.get("based_on_implementation_run")
            ),
            resumes_run_id=_optional_string(data.get("resumes_run_id")),
            summary=_optional_string(data.get("summary")),
            worklog=_string_tuple(data.get("worklog")),
            deviations_from_plan=_string_tuple(data.get("deviations_from_plan")),
            change_refs=_string_tuple(data.get("change_refs")),
            check_refs=_string_tuple(data.get("check_refs")),
            todo_updates=_string_tuple(data.get("todo_updates")),
            artifact_refs=_string_tuple(data.get("artifact_refs")),
            checks=tuple(
                ValidationCheck.from_dict(item)
                for item in _dict_list(data.get("checks"))
            ),
            evidence=_string_tuple(data.get("evidence")),
            recommendation=_optional_string(data.get("recommendation")),
            result=normalize_validation_result(result) if result is not None else None,
            handoff_refs=_string_tuple(data.get("handoff_refs")),
            actor_history=tuple(
                ActorRef.from_dict(item)
                for item in _dict_list(data.get("actor_history"))
            ),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            based_on_plan=_optional_string(data.get("based_on_plan")),
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
            workspace_git_commit=_optional_string(data.get("workspace_git_commit")),
            workspace_dirty=(
                bool(data.get("workspace_dirty"))
                if data.get("workspace_dirty") is not None
                else None
            ),
            workspace_diff_hash=_optional_string(data.get("workspace_diff_hash")),
            workspace_status_hash=_optional_string(data.get("workspace_status_hash")),
            workspace_snapshot_at=_optional_string(data.get("workspace_snapshot_at")),
            workspace_content_hash=_optional_string(data.get("workspace_content_hash")),
            workspace_paths_hash=_optional_string(data.get("workspace_paths_hash")),
            workspace_entry_count=_optional_int(data.get("workspace_entry_count")),
            workspace_snapshot_format=_optional_string(
                data.get("workspace_snapshot_format")
            ),
            workspace_snapshot_ref=_optional_string(data.get("workspace_snapshot_ref")),
        )

    @property
    def plan_ref(self) -> str | None:
        if self.based_on_plan_version is None:
            return None
        return _plan_id(self.based_on_plan_version)
