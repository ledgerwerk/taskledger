"""Tests for BDD report import service."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from taskledger.api.bdd import bdd_init, bdd_rule_add, bdd_example_add
from taskledger.services.bdd_reports import import_bdd_report
from taskledger.errors import LaunchError


class TestCucumberJsonImport:
    def test_import_passing_cucumber_report(self, tmp_path) -> None:
        """Test importing a passing Cucumber JSON report."""
        bdd_init(tmp_path, "task-0001", "Test feature")
        bdd_example_add(
            tmp_path,
            "task-0001",
            title="Test passes",
            given=("something",),
            when=("action",),
            then=("result",),
            acceptance_criteria=("ac-0001",),
        )

        # Create Cucumber JSON report
        report = [
            {
                "name": "Test feature",
                "elements": [
                    {
                        "type": "scenario",
                        "name": "Test passes",
                        "steps": [
                            {"name": "something", "result": {"status": "passed"}},
                            {"name": "action", "result": {"status": "passed"}},
                            {"name": "result", "result": {"status": "passed"}},
                        ],
                    }
                ],
            }
        ]
        report_path = tmp_path / "cucumber.json"
        report_path.write_text(json.dumps(report))

        result = import_bdd_report(
            tmp_path, "task-0001", str(report_path), "cucumber-json", "pytest -q"
        )

        assert result["kind"] == "bdd_report_import"
        assert result["format"] == "cucumber-json"
        assert result["result"] == "passed"
        assert "bdd-0001" in result["matched_examples"]
        assert len(result["unmatched_scenarios"]) == 0
        assert len(result["validation_checks"]) == 1
        assert result["validation_checks"][0]["status"] == "pass"
        assert result["validation_checks"][0]["criterion_id"] == "ac-0001"

    def test_import_failing_cucumber_report(self, tmp_path) -> None:
        """Test importing a failing Cucumber JSON report."""
        bdd_init(tmp_path, "task-0001", "Test feature")
        bdd_example_add(
            tmp_path,
            "task-0001",
            title="Test fails",
            given=("something",),
            when=("action",),
            then=("result",),
            acceptance_criteria=("ac-0001",),
        )

        report = [
            {
                "name": "Test feature",
                "elements": [
                    {
                        "type": "scenario",
                        "name": "Test fails",
                        "steps": [
                            {"name": "something", "result": {"status": "passed"}},
                            {
                                "name": "action",
                                "result": {
                                    "status": "failed",
                                    "error_message": "Expected X but got Y",
                                },
                            },
                        ],
                    }
                ],
            }
        ]
        report_path = tmp_path / "cucumber.json"
        report_path.write_text(json.dumps(report))

        result = import_bdd_report(
            tmp_path, "task-0001", str(report_path), "cucumber-json"
        )

        assert result["result"] == "failed"
        assert result["validation_checks"][0]["status"] == "fail"

    def test_import_unmatched_scenarios(self, tmp_path) -> None:
        """Test importing report with unmatched scenarios."""
        bdd_init(tmp_path, "task-0001", "Test feature")
        bdd_example_add(
            tmp_path,
            "task-0001",
            title="Known scenario",
            given=("x",), when=("y",), then=("z",),
        )

        report = [
            {
                "name": "Test feature",
                "elements": [
                    {
                        "type": "scenario",
                        "name": "Unknown scenario",
                        "steps": [
                            {"name": "step", "result": {"status": "passed"}},
                        ],
                    }
                ],
            }
        ]
        report_path = tmp_path / "cucumber.json"
        report_path.write_text(json.dumps(report))

        result = import_bdd_report(
            tmp_path, "task-0001", str(report_path), "cucumber-json"
        )

        assert len(result["matched_examples"]) == 0
        assert "Unknown scenario" in result["unmatched_scenarios"]
        assert len(result["warnings"]) == 1

    def test_import_missing_file(self, tmp_path) -> None:
        """Test importing a missing report file."""
        with pytest.raises(LaunchError, match="Report file not found"):
            import_bdd_report(
                tmp_path, "task-0001", "nonexistent.json", "cucumber-json"
            )

    def test_import_unsupported_format(self, tmp_path) -> None:
        """Test importing with unsupported format."""
        report_path = tmp_path / "test.json"
        report_path.write_text("[]")
        with pytest.raises(LaunchError, match="Unsupported report format"):
            import_bdd_report(
                tmp_path, "task-0001", str(report_path), "unknown-format"
            )

    def test_import_invalid_json(self, tmp_path) -> None:
        """Test importing invalid JSON."""
        report_path = tmp_path / "bad.json"
        report_path.write_text("not json {{{")
        with pytest.raises(LaunchError, match="Invalid Cucumber JSON"):
            import_bdd_report(
                tmp_path, "task-0001", str(report_path), "cucumber-json"
            )


class TestJunitXmlImport:
    def test_import_passing_junit_report(self, tmp_path) -> None:
        """Test importing a passing JUnit XML report."""
        bdd_init(tmp_path, "task-0001", "Test feature")
        bdd_example_add(
            tmp_path,
            "task-0001",
            title="JUnit test passes",
            given=("something",),
            when=("action",),
            then=("result",),
            acceptance_criteria=("ac-0001",),
        )

        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="BDD Tests" tests="1" failures="0">
    <testcase name="JUnit test passes" classname="test_bdd">
    </testcase>
  </testsuite>
</testsuites>"""
        report_path = tmp_path / "junit.xml"
        report_path.write_text(xml_content)

        result = import_bdd_report(
            tmp_path, "task-0001", str(report_path), "junit-xml", "pytest -q"
        )

        assert result["format"] == "junit-xml"
        assert result["result"] == "passed"
        assert "bdd-0001" in result["matched_examples"]
        assert result["validation_checks"][0]["status"] == "pass"

    def test_import_failing_junit_report(self, tmp_path) -> None:
        """Test importing a failing JUnit XML report."""
        bdd_init(tmp_path, "task-0001", "Test feature")
        bdd_example_add(
            tmp_path,
            "task-0001",
            title="JUnit test fails",
            given=("x",), when=("y",), then=("z",),
            acceptance_criteria=("ac-0001",),
        )

        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="BDD Tests" tests="1" failures="1">
    <testcase name="JUnit test fails" classname="test_bdd">
      <failure message="AssertionError">Expected X but got Y</failure>
    </testcase>
  </testsuite>
</testsuites>"""
        report_path = tmp_path / "junit.xml"
        report_path.write_text(xml_content)

        result = import_bdd_report(
            tmp_path, "task-0001", str(report_path), "junit-xml"
        )

        assert result["result"] == "failed"
        assert result["validation_checks"][0]["status"] == "fail"

    def test_import_junit_with_testsuite_root(self, tmp_path) -> None:
        """Test importing JUnit XML with testsuite as root element."""
        bdd_init(tmp_path, "task-0001", "Test feature")
        bdd_example_add(
            tmp_path,
            "task-0001",
            title="Direct suite test",
            given=("x",), when=("y",), then=("z",),
        )

        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="BDD Tests" tests="1" failures="0">
  <testcase name="Direct suite test" classname="test_bdd">
  </testcase>
</testsuite>"""
        report_path = tmp_path / "junit.xml"
        report_path.write_text(xml_content)

        result = import_bdd_report(
            tmp_path, "task-0001", str(report_path), "junit-xml"
        )

        assert result["result"] == "passed"

    def test_import_invalid_xml(self, tmp_path) -> None:
        """Test importing invalid XML."""
        report_path = tmp_path / "bad.xml"
        report_path.write_text("not xml <><><>")
        with pytest.raises(LaunchError, match="Invalid JUnit XML"):
            import_bdd_report(
                tmp_path, "task-0001", str(report_path), "junit-xml"
            )
