"""BDD domain models for task-local behavior-driven development sidecars."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from taskledger.domain._model_utils import (
    _int_or_default,
    _optional_string,
    _string_tuple,
    _string_value,
)
from taskledger.domain.states import (
    TASKLEDGER_SCHEMA_VERSION,
    TASKLEDGER_V2_FILE_VERSION,
)
from taskledger.errors import LaunchError
from taskledger.timeutils import utc_now_iso

BddExampleStatus = Literal[
    "discovered",
    "formulated",
    "linked",
    "automated",
    "validated",
    "archived",
]

BddAutomationStatus = Literal[
    "pending",
    "linked",
    "automated",
]

BDD_EXAMPLE_STATUSES = frozenset(
    {"discovered", "formulated", "linked", "automated", "validated", "archived"}
)
BDD_AUTOMATION_STATUSES = frozenset({"pending", "linked", "automated"})


def normalize_bdd_example_status(value: str) -> BddExampleStatus:
    """Normalize and validate a BDD example status string."""
    if value not in BDD_EXAMPLE_STATUSES:
        raise LaunchError(f"Unsupported BDD example status: {value}")
    return value  # type: ignore[return-value]


def normalize_bdd_automation_status(value: str) -> BddAutomationStatus:
    """Normalize and validate a BDD automation status string."""
    if value not in BDD_AUTOMATION_STATUSES:
        raise LaunchError(f"Unsupported BDD automation status: {value}")
    return value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class BddAutomationRef:
    """Reference to automation for a BDD example."""

    status: BddAutomationStatus = "pending"
    feature_file: str = ""
    scenario: str = ""
    pytest_path: str = ""
    pytest_nodeid: str = ""
    command: str = ""
    report_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "feature_file": self.feature_file,
            "scenario": self.scenario,
            "pytest_path": self.pytest_path,
            "pytest_nodeid": self.pytest_nodeid,
            "command": self.command,
            "report_path": self.report_path,
        }

    @classmethod
    def from_dict(cls, data: object) -> BddAutomationRef:
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise LaunchError("Invalid BDD automation ref: expected mapping.")
        return cls(
            status=normalize_bdd_automation_status(
                _optional_string(data.get("status")) or "pending"
            ),
            feature_file=_optional_string(data.get("feature_file")) or "",
            scenario=_optional_string(data.get("scenario")) or "",
            pytest_path=_optional_string(data.get("pytest_path")) or "",
            pytest_nodeid=_optional_string(data.get("pytest_nodeid")) or "",
            command=_optional_string(data.get("command")) or "",
            report_path=_optional_string(data.get("report_path")) or "",
        )


@dataclass(frozen=True, slots=True)
class BddFeatureRecord:
    """A BDD feature record for a task."""

    id: str
    task_id: str
    title: str
    description: str = ""
    tags: tuple[str, ...] = ()
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "bdd_feature"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "file_version": self.file_version,
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: object) -> BddFeatureRecord:
        if not isinstance(data, dict):
            raise LaunchError("Invalid BDD feature: expected mapping.")
        if _optional_string(data.get("object_type")) not in (None, "bdd_feature"):
            raise LaunchError(
                f"Invalid BDD feature object_type: {data.get('object_type')}"
            )
        return cls(
            id=_string_value(data, "id"),
            task_id=_string_value(data, "task_id"),
            title=_string_value(data, "title"),
            description=_optional_string(data.get("description")) or "",
            tags=_string_tuple(data.get("tags")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_or_default(
                data.get("schema_version"), TASKLEDGER_SCHEMA_VERSION
            ),
            object_type=_optional_string(data.get("object_type")) or "bdd_feature",
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            updated_at=_optional_string(data.get("updated_at")) or utc_now_iso(),
        )


@dataclass(frozen=True, slots=True)
class BddRuleRecord:
    """A BDD rule record for a task."""

    id: str
    task_id: str
    title: str
    description: str = ""
    feature_id: str = "bdd"
    tags: tuple[str, ...] = ()
    source: str = "user"
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "bdd_rule"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "feature_id": self.feature_id,
            "tags": list(self.tags),
            "source": self.source,
            "file_version": self.file_version,
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: object) -> BddRuleRecord:
        if not isinstance(data, dict):
            raise LaunchError("Invalid BDD rule: expected mapping.")
        if _optional_string(data.get("object_type")) not in (None, "bdd_rule"):
            raise LaunchError(
                f"Invalid BDD rule object_type: {data.get('object_type')}"
            )
        return cls(
            id=_string_value(data, "id"),
            task_id=_string_value(data, "task_id"),
            title=_string_value(data, "title"),
            description=_optional_string(data.get("description")) or "",
            feature_id=_optional_string(data.get("feature_id")) or "bdd",
            tags=_string_tuple(data.get("tags")),
            source=_optional_string(data.get("source")) or "user",
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_or_default(
                data.get("schema_version"), TASKLEDGER_SCHEMA_VERSION
            ),
            object_type=_optional_string(data.get("object_type")) or "bdd_rule",
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            updated_at=_optional_string(data.get("updated_at")) or utc_now_iso(),
        )


@dataclass(frozen=True, slots=True)
class BddExampleRecord:
    """A BDD example/scenario record for a task."""

    id: str
    task_id: str
    title: str
    rule_id: str | None = None
    status: BddExampleStatus = "discovered"
    given: tuple[str, ...] = ()
    when: tuple[str, ...] = ()
    then: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    question_refs: tuple[str, ...] = ()
    todo_refs: tuple[str, ...] = ()
    file_refs: tuple[str, ...] = ()
    archledger_refs: tuple[str, ...] = ()
    automation: BddAutomationRef = field(default_factory=BddAutomationRef)
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "bdd_example"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "title": self.title,
            "rule_id": self.rule_id,
            "status": self.status,
            "given": list(self.given),
            "when": list(self.when),
            "then": list(self.then),
            "tags": list(self.tags),
            "acceptance_criteria": list(self.acceptance_criteria),
            "question_refs": list(self.question_refs),
            "todo_refs": list(self.todo_refs),
            "file_refs": list(self.file_refs),
            "archledger_refs": list(self.archledger_refs),
            "automation": self.automation.to_dict(),
            "file_version": self.file_version,
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: object) -> BddExampleRecord:
        if not isinstance(data, dict):
            raise LaunchError("Invalid BDD example: expected mapping.")
        if _optional_string(data.get("object_type")) not in (None, "bdd_example"):
            raise LaunchError(
                f"Invalid BDD example object_type: {data.get('object_type')}"
            )
        status_raw = _optional_string(data.get("status")) or "discovered"
        status = normalize_bdd_example_status(status_raw)
        return cls(
            id=_string_value(data, "id"),
            task_id=_string_value(data, "task_id"),
            title=_string_value(data, "title"),
            rule_id=_optional_string(data.get("rule_id")),
            status=status,
            given=_string_tuple(data.get("given")),
            when=_string_tuple(data.get("when")),
            then=_string_tuple(data.get("then")),
            tags=_string_tuple(data.get("tags")),
            acceptance_criteria=_string_tuple(data.get("acceptance_criteria")),
            question_refs=_string_tuple(data.get("question_refs")),
            todo_refs=_string_tuple(data.get("todo_refs")),
            file_refs=_string_tuple(data.get("file_refs")),
            archledger_refs=_string_tuple(data.get("archledger_refs")),
            automation=BddAutomationRef.from_dict(data.get("automation")),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_or_default(
                data.get("schema_version"), TASKLEDGER_SCHEMA_VERSION
            ),
            object_type=_optional_string(data.get("object_type")) or "bdd_example",
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
            updated_at=_optional_string(data.get("updated_at")) or utc_now_iso(),
        )


@dataclass(frozen=True, slots=True)
class BddReportRecord:
    """A BDD report record imported from Cucumber/JUnit output."""

    id: str
    task_id: str
    source_path: str
    format: str  # cucumber-json | junit-xml
    command: str = ""
    imported_at: str = ""
    result: str = "unknown"  # passed | failed | unknown
    example_results: tuple[dict[str, object], ...] = ()
    validation_check_refs: tuple[str, ...] = ()
    unmatched_count: int = 0
    has_unmatched_failures: bool = False
    file_version: str = TASKLEDGER_V2_FILE_VERSION
    schema_version: int = TASKLEDGER_SCHEMA_VERSION
    object_type: str = "bdd_report"
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "source_path": self.source_path,
            "format": self.format,
            "command": self.command,
            "imported_at": self.imported_at,
            "result": self.result,
            "example_results": list(self.example_results),
            "validation_check_refs": list(self.validation_check_refs),
            "unmatched_count": self.unmatched_count,
            "has_unmatched_failures": self.has_unmatched_failures,
            "file_version": self.file_version,
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: object) -> BddReportRecord:
        if not isinstance(data, dict):
            raise LaunchError("Invalid BDD report: expected mapping.")
        if _optional_string(data.get("object_type")) not in (None, "bdd_report"):
            raise LaunchError(
                f"Invalid BDD report object_type: {data.get('object_type')}"
            )
        example_results_raw = data.get("example_results", [])
        if not isinstance(example_results_raw, list):
            raise LaunchError("Invalid BDD report: example_results must be a list.")
        example_results: list[dict[str, object]] = []
        for item in example_results_raw:
            if not isinstance(item, dict):
                raise LaunchError(
                    "Invalid BDD report: each example_result must be a mapping."
                )
            example_results.append(item)
        return cls(
            id=_string_value(data, "id"),
            task_id=_string_value(data, "task_id"),
            source_path=_string_value(data, "source_path"),
            format=_string_value(data, "format"),
            command=_optional_string(data.get("command")) or "",
            imported_at=_optional_string(data.get("imported_at")) or utc_now_iso(),
            result=_optional_string(data.get("result")) or "unknown",
            example_results=tuple(example_results),
            validation_check_refs=_string_tuple(data.get("validation_check_refs")),
            unmatched_count=_int_or_default(data.get("unmatched_count"), 0),
            has_unmatched_failures=bool(data.get("has_unmatched_failures", False)),
            file_version=_optional_string(data.get("file_version"))
            or TASKLEDGER_V2_FILE_VERSION,
            schema_version=_int_or_default(
                data.get("schema_version"), TASKLEDGER_SCHEMA_VERSION
            ),
            object_type=_optional_string(data.get("object_type")) or "bdd_report",
            created_at=_optional_string(data.get("created_at")) or utc_now_iso(),
        )
