"""Tests for BDD storage layer."""

from __future__ import annotations

import pytest

from taskledger.domain.bdd import (
    BddAutomationRef,
    BddExampleRecord,
    BddFeatureRecord,
    BddReportRecord,
    BddRuleRecord,
)
from taskledger.storage.task_store import (
    load_bdd_examples,
    load_bdd_feature,
    load_bdd_reports,
    load_bdd_rules,
    resolve_bdd_example,
    resolve_bdd_rule,
    save_bdd_example,
    save_bdd_feature,
    save_bdd_report,
    save_bdd_rule,
)


class TestBddFeatureStorage:
    def test_save_and_load_feature(self, tmp_path) -> None:
        feature = BddFeatureRecord(
            id="feature-0001",
            task_id="task-0001",
            title="Task lifecycle gates",
            description="Gates for task lifecycle",
            tags=("lifecycle",),
        )
        save_bdd_feature(tmp_path, feature)
        loaded = load_bdd_feature(tmp_path, "task-0001")
        assert loaded is not None
        assert loaded.id == "feature-0001"
        assert loaded.title == "Task lifecycle gates"
        assert loaded.description == "Gates for task lifecycle"
        assert loaded.tags == ("lifecycle",)

    def test_load_missing_feature_returns_none(self, tmp_path) -> None:
        assert load_bdd_feature(tmp_path, "task-9999") is None


class TestBddRuleStorage:
    def test_save_and_load_rules(self, tmp_path) -> None:
        rule1 = BddRuleRecord(
            id="rule-0001",
            task_id="task-0001",
            title="First rule",
            description="Description 1",
        )
        rule2 = BddRuleRecord(
            id="rule-0002",
            task_id="task-0001",
            title="Second rule",
            description="Description 2",
        )
        save_bdd_rule(tmp_path, rule1)
        save_bdd_rule(tmp_path, rule2)
        rules = load_bdd_rules(tmp_path, "task-0001")
        assert len(rules) == 2
        assert rules[0].id == "rule-0001"
        assert rules[1].id == "rule-0002"

    def test_load_empty_rules(self, tmp_path) -> None:
        assert load_bdd_rules(tmp_path, "task-9999") == []

    def test_resolve_rule(self, tmp_path) -> None:
        rule = BddRuleRecord(
            id="rule-0001", task_id="task-0001", title="Test rule"
        )
        save_bdd_rule(tmp_path, rule)
        resolved = resolve_bdd_rule(tmp_path, "task-0001", "rule-0001")
        assert resolved.id == "rule-0001"

    def test_resolve_rule_normalized(self, tmp_path) -> None:
        rule = BddRuleRecord(
            id="rule-0001", task_id="task-0001", title="Test rule"
        )
        save_bdd_rule(tmp_path, rule)
        resolved = resolve_bdd_rule(tmp_path, "task-0001", "rule-1")
        assert resolved.id == "rule-0001"

    def test_resolve_rule_not_found(self, tmp_path) -> None:
        with pytest.raises(Exception, match="BDD rule not found"):
            resolve_bdd_rule(tmp_path, "task-0001", "rule-9999")


class TestBddExampleStorage:
    def test_save_and_load_examples(self, tmp_path) -> None:
        example = BddExampleRecord(
            id="bdd-0001",
            task_id="task-0001",
            title="Agent tries to implement before approval",
            rule_id="rule-0001",
            status="formulated",
            given=("a task has a proposed plan",),
            when=("the agent starts implementation",),
            then=("implementation is blocked",),
            acceptance_criteria=("ac-0001",),
            automation=BddAutomationRef(status="linked", scenario="Test"),
        )
        save_bdd_example(tmp_path, example)
        examples = load_bdd_examples(tmp_path, "task-0001")
        assert len(examples) == 1
        assert examples[0].id == "bdd-0001"
        assert examples[0].title == "Agent tries to implement before approval"
        assert examples[0].given == ("a task has a proposed plan",)
        assert examples[0].when == ("the agent starts implementation",)
        assert examples[0].then == ("implementation is blocked",)
        assert examples[0].acceptance_criteria == ("ac-0001",)
        assert examples[0].automation.status == "linked"

    def test_load_empty_examples(self, tmp_path) -> None:
        assert load_bdd_examples(tmp_path, "task-9999") == []

    def test_resolve_example(self, tmp_path) -> None:
        example = BddExampleRecord(
            id="bdd-0001", task_id="task-0001", title="Test"
        )
        save_bdd_example(tmp_path, example)
        resolved = resolve_bdd_example(tmp_path, "task-0001", "bdd-0001")
        assert resolved.id == "bdd-0001"

    def test_resolve_example_normalized(self, tmp_path) -> None:
        example = BddExampleRecord(
            id="bdd-0001", task_id="task-0001", title="Test"
        )
        save_bdd_example(tmp_path, example)
        resolved = resolve_bdd_example(tmp_path, "task-0001", "bdd-1")
        assert resolved.id == "bdd-0001"

    def test_resolve_example_not_found(self, tmp_path) -> None:
        with pytest.raises(Exception, match="BDD example not found"):
            resolve_bdd_example(tmp_path, "task-0001", "bdd-9999")


class TestBddReportStorage:
    def test_save_and_load_reports(self, tmp_path) -> None:
        report = BddReportRecord(
            id="bdd-report-0001",
            task_id="task-0001",
            source_path="reports/cucumber.json",
            format="cucumber-json",
            command="pytest -q tests/bdd",
            result="passed",
            example_results=({"scenario": "Test", "status": "passed"},),
        )
        save_bdd_report(tmp_path, report)
        reports = load_bdd_reports(tmp_path, "task-0001")
        assert len(reports) == 1
        assert reports[0].id == "bdd-report-0001"
        assert reports[0].format == "cucumber-json"
        assert reports[0].result == "passed"

    def test_load_empty_reports(self, tmp_path) -> None:
        assert load_bdd_reports(tmp_path, "task-9999") == []
