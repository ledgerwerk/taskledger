from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, cast

from taskledger.domain._model_utils import (
    _int_value,
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

ReviewResult = Literal["pass", "fail", "blocked"]
ReviewSource = Literal["working_tree", "commit", "manual"]


@dataclass(slots=True, frozen=True)
class CodeReviewRecord:
    review_id: str
    task_id: str
    implementation_run: str | None
    reviewed_at: str = field(default_factory=utc_now_iso)
    result: ReviewResult = "blocked"
    source: ReviewSource = "manual"
    body: str = ""
    summary: str | None = None

    reviewer: ActorRef = field(default_factory=ActorRef)
    harness: HarnessRef | None = None
    worker_step_id: str | None = None
    handoff_id: str | None = None
    snapshot_drift: bool | None = None

    git_branch: str | None = None
    git_commit: str | None = None
    git_status_short: str | None = None
    git_diff_stat: str | None = None
    git_staged_diff_stat: str | None = None
    git_changed_paths: tuple[str, ...] = ()
    git_diff_hash: str | None = None

    artifact_refs: tuple[str, ...] = ()

    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "code_review"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "file_version": self.file_version,
            "review_id": self.review_id,
            "task_id": self.task_id,
            "implementation_run": self.implementation_run,
            "reviewed_at": self.reviewed_at,
            "result": self.result,
            "source": self.source,
            "summary": self.summary,
            "body": self.body,
            "reviewer": self.reviewer.to_dict(),
            "harness": self.harness.to_dict() if self.harness is not None else None,
            "worker_step_id": self.worker_step_id,
            "handoff_id": self.handoff_id,
            "snapshot_drift": self.snapshot_drift,
            "git_branch": self.git_branch,
            "git_commit": self.git_commit,
            "git_status_short": self.git_status_short,
            "git_diff_stat": self.git_diff_stat,
            "git_staged_diff_stat": self.git_staged_diff_stat,
            "git_changed_paths": list(self.git_changed_paths),
            "git_diff_hash": self.git_diff_hash,
            "artifact_refs": list(self.artifact_refs),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> CodeReviewRecord:
        _require_contract(data, expected_object_type="code_review")
        result = _optional_string(data.get("result")) or "blocked"
        if result not in {"pass", "fail", "blocked"}:
            raise LaunchError(f"Unsupported code review result: {result}")
        source = _optional_string(data.get("source")) or "manual"
        if source not in {"working_tree", "commit", "manual"}:
            raise LaunchError(f"Unsupported code review source: {source}")
        raw_snapshot_drift = data.get("snapshot_drift")
        snapshot_drift = (
            raw_snapshot_drift if isinstance(raw_snapshot_drift, bool) else None
        )
        return cls(
            review_id=_string_value(data, "review_id"),
            task_id=_string_value(data, "task_id"),
            implementation_run=_optional_string(data.get("implementation_run")),
            reviewed_at=_optional_string(data.get("reviewed_at")) or utc_now_iso(),
            result=cast(ReviewResult, result),
            source=cast(ReviewSource, source),
            summary=_optional_string(data.get("summary")),
            body=_optional_string(data.get("body")) or "",
            reviewer=ActorRef.from_dict(data.get("reviewer")),
            harness=HarnessRef.from_dict(data.get("harness"))
            if data.get("harness") is not None
            else None,
            worker_step_id=_optional_string(data.get("worker_step_id")),
            handoff_id=_optional_string(data.get("handoff_id")),
            snapshot_drift=snapshot_drift,
            git_branch=_optional_string(data.get("git_branch")),
            git_commit=_optional_string(data.get("git_commit")),
            git_status_short=_optional_string(data.get("git_status_short")),
            git_diff_stat=_optional_string(data.get("git_diff_stat")),
            git_staged_diff_stat=_optional_string(data.get("git_staged_diff_stat")),
            git_changed_paths=_string_tuple(data.get("git_changed_paths")),
            git_diff_hash=_optional_string(data.get("git_diff_hash")),
            artifact_refs=_string_tuple(data.get("artifact_refs")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_value(data, "schema_version"),
            object_type=_string_value(data, "object_type"),
        )
