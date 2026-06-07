"""Tests for BDD domain models."""

from __future__ import annotations

import pytest

from taskledger.domain.bdd import (
    BDD_AUTOMATION_STATUSES,
    BDD_EXAMPLE_STATUSES,
    BddAutomationRef,
    BddExampleRecord,
    BddFeatureRecord,
    BddReportRecord,
    BddRuleRecord,
    normalize_bdd_automation_status,
    normalize_bdd_example_status,
)
from taskledger.errors import LaunchError


class TestBddAutomationRef:
    def test_defaults(self) -> None:
        ref = BddAutomationRef()
        assert ref.status == "pending"
        assert ref.feature_file == ""
        assert ref.scenario == ""
        assert ref.command == ""
        assert ref.report_path == ""

    def test_round_trip(self) -> None:
        ref = BddAutomationRef(
            status="linked",
            feature_file="tests/bdd/features/lifecycle.feature",
            scenario="Agent tries to implement before approval",
            command="pytest -q tests/bdd",
            report_path="reports/cucumber.json",
        )
        d = ref.to_dict()
        restored = BddAutomationRef.from_dict(d)
        assert restored == ref

    def test_from_dict_none(self) -> None:
        ref = BddAutomationRef.from_dict(None)
        assert ref.status == "pending"

    def test_from_dict_invalid_type(self) -> None:
        with pytest.raises(LaunchError, match="expected mapping"):
            BddAutomationRef.from_dict("bad")

    def test_invalid_status(self) -> None:
        with pytest.raises(LaunchError, match="Unsupported BDD automation status"):
            BddAutomationRef.from_dict({"status": "invalid"})


class TestBddFeatureRecord:
    def test_defaults(self) -> None:
        rec = BddFeatureRecord(id="feature-0001", task_id="task-0001", title="Test")
        assert rec.object_type == "bdd_feature"
        assert rec.description == ""
        assert rec.tags == ()

    def test_round_trip(self) -> None:
        rec = BddFeatureRecord(
            id="feature-0001",
            task_id="task-0112",
            title="Task lifecycle gates",
            description="Gates for task lifecycle",
            tags=("lifecycle", "gates"),
        )
        d = rec.to_dict()
        restored = BddFeatureRecord.from_dict(d)
        assert restored == rec
        assert restored.tags == ("lifecycle", "gates")

    def test_from_dict_invalid_type(self) -> None:
        with pytest.raises(LaunchError, match="expected mapping"):
            BddFeatureRecord.from_dict("bad")

    def test_from_dict_wrong_object_type(self) -> None:
        data = {
            "id": "f-1",
            "task_id": "t-1",
            "title": "Test",
            "object_type": "wrong",
        }
        with pytest.raises(LaunchError, match="Invalid BDD feature object_type"):
            BddFeatureRecord.from_dict(data)


class TestBddRuleRecord:
    def test_defaults(self) -> None:
        rec = BddRuleRecord(id="rule-0001", task_id="task-0001", title="Test")
        assert rec.object_type == "bdd_rule"
        assert rec.feature_id == "bdd"
        assert rec.source == "user"

    def test_round_trip(self) -> None:
        rec = BddRuleRecord(
            id="rule-0001",
            task_id="task-0112",
            title="Implementation requires an accepted plan",
            description="Must have accepted plan before implementing",
            feature_id="feature-0001",
            tags=("gate",),
            source="user",
        )
        d = rec.to_dict()
        restored = BddRuleRecord.from_dict(d)
        assert restored == rec

    def test_from_dict_invalid_type(self) -> None:
        with pytest.raises(LaunchError, match="expected mapping"):
            BddRuleRecord.from_dict(42)


class TestBddExampleRecord:
    def test_defaults(self) -> None:
        rec = BddExampleRecord(id="bdd-0001", task_id="task-0001", title="Test")
        assert rec.object_type == "bdd_example"
        assert rec.status == "discovered"
        assert rec.given == ()
        assert rec.when == ()
        assert rec.then == ()
        assert rec.acceptance_criteria == ()
        assert rec.automation.status == "pending"

    def test_round_trip(self) -> None:
        rec = BddExampleRecord(
            id="bdd-0001",
            task_id="task-0112",
            title="Agent tries to implement before approval",
            rule_id="rule-0001",
            status="formulated",
            given=("a task has a proposed plan", "the plan has not been approved"),
            when=("the agent starts implementation",),
            then=("implementation is blocked", "the task remains before implementing"),
            tags=("gate",),
            acceptance_criteria=("ac-0001",),
            automation=BddAutomationRef(status="linked", scenario="Agent tries"),
        )
        d = rec.to_dict()
        restored = BddExampleRecord.from_dict(d)
        assert restored == rec
        assert restored.given == ("a task has a proposed plan", "the plan has not been approved")
        assert restored.when == ("the agent starts implementation",)
        assert restored.then == ("implementation is blocked", "the task remains before implementing")
        assert restored.acceptance_criteria == ("ac-0001",)

    def test_from_dict_invalid_type(self) -> None:
        with pytest.raises(LaunchError, match="expected mapping"):
            BddExampleRecord.from_dict([])

    def test_invalid_status(self) -> None:
        data = {"id": "e-1", "task_id": "t-1", "title": "Test", "status": "invalid"}
        with pytest.raises(LaunchError, match="Unsupported BDD example status"):
            BddExampleRecord.from_dict(data)


class TestBddReportRecord:
    def test_defaults(self) -> None:
        rec = BddReportRecord(
            id="bdd-report-0001",
            task_id="task-0001",
            source_path="reports/cucumber.json",
            format="cucumber-json",
        )
        assert rec.object_type == "bdd_report"
        assert rec.result == "unknown"
        assert rec.example_results == ()

    def test_round_trip(self) -> None:
        rec = BddReportRecord(
            id="bdd-report-0001",
            task_id="task-0112",
            source_path="reports/cucumber.json",
            format="cucumber-json",
            command="pytest -q tests/bdd",
            imported_at="2026-06-07T00:00:00Z",
            result="passed",
            example_results=({"scenario": "Test", "status": "passed"},),
            validation_check_refs=("check-0001",),
        )
        d = rec.to_dict()
        restored = BddReportRecord.from_dict(d)
        assert restored == rec

    def test_from_dict_invalid_type(self) -> None:
        with pytest.raises(LaunchError, match="expected mapping"):
            BddReportRecord.from_dict(True)

    def test_from_dict_bad_example_results(self) -> None:
        data = {
            "id": "r-1",
            "task_id": "t-1",
            "source_path": "p",
            "format": "f",
            "example_results": "not-a-list",
        }
        with pytest.raises(LaunchError, match="example_results must be a list"):
            BddReportRecord.from_dict(data)


class TestStatusNormalizers:
    def test_valid_example_statuses(self) -> None:
        for s in BDD_EXAMPLE_STATUSES:
            assert normalize_bdd_example_status(s) == s

    def test_invalid_example_status(self) -> None:
        with pytest.raises(LaunchError):
            normalize_bdd_example_status("bad")

    def test_valid_automation_statuses(self) -> None:
        for s in BDD_AUTOMATION_STATUSES:
            assert normalize_bdd_automation_status(s) == s

    def test_invalid_automation_status(self) -> None:
        with pytest.raises(LaunchError):
            normalize_bdd_automation_status("bad")
