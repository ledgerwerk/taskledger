"""Tests for Gherkin export service."""

from __future__ import annotations

import pytest

from taskledger.api.bdd import bdd_init, bdd_rule_add, bdd_example_add
from taskledger.services.bdd_gherkin import export_gherkin
from taskledger.storage.task_store import save_bdd_example
from taskledger.domain.bdd import BddExampleRecord
from taskledger.errors import LaunchError


class TestGherkinExport:
    def test_export_basic_feature(self, tmp_path) -> None:
        """Test basic Gherkin export with rules and examples."""
        bdd_init(tmp_path, "task-0001", "Task lifecycle gates")
        bdd_rule_add(tmp_path, "task-0001", "Implementation requires an accepted plan")
        bdd_example_add(
            tmp_path,
            "task-0001",
            title="Agent tries to implement before approval",
            rule_id="rule-0001",
            given=("a task has a proposed plan", "the plan has not been approved"),
            when=("the agent starts implementation",),
            then=("implementation is blocked",),
            acceptance_criteria=("ac-0001",),
        )

        out = tmp_path / "features" / "lifecycle.feature"
        result = export_gherkin(tmp_path, "task-0001", str(out))

        assert result["kind"] == "bdd_gherkin_export"
        assert result["task_id"] == "task-0001"
        assert "bdd-0001" in result["exported_examples"]
        assert out.exists()

        content = out.read_text()
        assert "Feature: Task lifecycle gates" in content
        assert "Rule: Implementation requires an accepted plan" in content
        assert "Scenario: Agent tries to implement before approval" in content
        assert "Given a task has a proposed plan" in content
        assert "And the plan has not been approved" in content
        assert "When the agent starts implementation" in content
        assert "Then implementation is blocked" in content

    def test_export_ownership_header(self, tmp_path) -> None:
        """Test that exported .feature files have ownership headers."""
        bdd_init(tmp_path, "task-0001", "Test feature")
        bdd_example_add(
            tmp_path,
            "task-0001",
            title="Test scenario",
            given=("something",),
            when=("action",),
            then=("result",),
        )

        out = tmp_path / "test.feature"
        export_gherkin(tmp_path, "task-0001", str(out))

        content = out.read_text()
        assert "# Generated from Taskledger task task-0001." in content
        assert "# Edit Taskledger BDD records as canonical source" in content

    def test_export_refuses_no_formulated_examples(self, tmp_path) -> None:
        """Export should refuse if no formulated examples exist."""
        bdd_init(tmp_path, "task-0001", "Test feature")
        # Add a discovered-only example (no given/when/then)
        example = BddExampleRecord(
            id="bdd-0001", task_id="task-0001", title="Just discovered"
        )
        save_bdd_example(tmp_path, example)

        with pytest.raises(LaunchError, match="No formulated BDD examples"):
            export_gherkin(tmp_path, "task-0001", str(tmp_path / "out.feature"))

    def test_export_warns_missing_ac_links(self, tmp_path) -> None:
        """Export should warn when examples lack AC links."""
        bdd_init(tmp_path, "task-0001", "Test feature")
        bdd_example_add(
            tmp_path,
            "task-0001",
            title="No AC link",
            given=("something",),
            when=("action",),
            then=("result",),
        )

        out = tmp_path / "test.feature"
        result = export_gherkin(tmp_path, "task-0001", str(out))

        assert len(result["warnings"]) == 1
        assert "no acceptance-criterion link" in result["warnings"][0]

    def test_export_refuses_outside_workspace(self, tmp_path) -> None:
        """Export should refuse paths outside workspace."""
        bdd_init(tmp_path, "task-0001", "Test feature")
        bdd_example_add(
            tmp_path,
            "task-0001",
            title="Test",
            given=("something",),
            when=("action",),
            then=("result",),
        )

        with pytest.raises(LaunchError, match="within workspace"):
            export_gherkin(tmp_path, "task-0001", "/tmp/outside.feature")

    def test_export_deterministic_ordering(self, tmp_path) -> None:
        """Export should produce deterministic ordering."""
        bdd_init(tmp_path, "task-0001", "Test feature")
        bdd_rule_add(tmp_path, "task-0001", "Rule B")
        bdd_rule_add(tmp_path, "task-0001", "Rule A")
        bdd_example_add(
            tmp_path,
            "task-0001",
            title="Example under rule 2",
            rule_id="rule-0002",
            given=("x",), when=("y",), then=("z",),
        )
        bdd_example_add(
            tmp_path,
            "task-0001",
            title="Example under rule 1",
            rule_id="rule-0001",
            given=("a",), when=("b",), then=("c",),
        )

        out1 = tmp_path / "out1.feature"
        out2 = tmp_path / "out2.feature"
        export_gherkin(tmp_path, "task-0001", str(out1))
        export_gherkin(tmp_path, "task-0001", str(out2))

        assert out1.read_text() == out2.read_text()

    def test_export_with_tags(self, tmp_path) -> None:
        """Export should include tags."""
        bdd_init(tmp_path, "task-0001", "Test feature")
        from taskledger.storage.task_store import load_bdd_feature, save_bdd_feature

        feature = load_bdd_feature(tmp_path, "task-0001")
        assert feature is not None
        # Update feature with tags
        from taskledger.domain.bdd import BddFeatureRecord

        tagged = BddFeatureRecord(
            id=feature.id,
            task_id=feature.task_id,
            title=feature.title,
            description=feature.description,
            tags=("lifecycle", "gates"),
        )
        save_bdd_feature(tmp_path, tagged)

        bdd_example_add(
            tmp_path,
            "task-0001",
            title="Tagged example",
            given=("x",), when=("y",), then=("z",),
        )

        out = tmp_path / "test.feature"
        export_gherkin(tmp_path, "task-0001", str(out))

        content = out.read_text()
        assert "@lifecycle" in content
        assert "@gates" in content

    def test_export_no_bdd_initialized(self, tmp_path) -> None:
        """Export should fail if BDD not initialized."""
        with pytest.raises(LaunchError, match="BDD not initialized"):
            export_gherkin(tmp_path, "task-0001", str(tmp_path / "out.feature"))
