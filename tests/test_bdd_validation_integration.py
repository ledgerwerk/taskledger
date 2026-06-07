"""Tests for BDD validation integration."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from taskledger.cli import app

runner = CliRunner()


class TestBddValidationIntegration:
    def test_import_bdd_report_creates_validation_checks(self, tmp_path, monkeypatch) -> None:
        """Import BDD report should create validation checks for linked criteria."""
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)

        # Create BDD structure
        runner.invoke(app, ["bdd", "init", "--feature", "Test feature"])
        runner.invoke(
            app,
            ["bdd", "example", "add", "--title", "Test passes",
             "--given", "a", "--when", "b", "--then", "c",
             "--acceptance-criterion", "ac-0001"],
        )

        # Create Cucumber JSON report
        import json as json_mod
        report = [
            {
                "name": "Test feature",
                "elements": [
                    {
                        "type": "scenario",
                        "name": "Test passes",
                        "steps": [
                            {"name": "a", "result": {"status": "passed"}},
                            {"name": "b", "result": {"status": "passed"}},
                            {"name": "c", "result": {"status": "passed"}},
                        ],
                    }
                ],
            }
        ]
        report_path = tmp_path / "cucumber.json"
        report_path.write_text(json_mod.dumps(report))

        # Start validation
        runner.invoke(app, ["implement", "start"])
        runner.invoke(app, ["implement", "finish", "--summary", "Done"])
        runner.invoke(app, ["validate", "start"])

        # Import report
        result = runner.invoke(
            app,
            [
                "--json", "validate", "import-bdd-report",
                str(report_path),
                "--format", "cucumber-json",
                "--command", "pytest -q",
            ],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert "bdd-0001" in payload["result"]["matched_examples"]
        assert payload["result"]["result"] == "passed"

    def test_failing_bdd_report_blocks_validation_finish(self, tmp_path, monkeypatch) -> None:
        """Failing BDD report should block validate finish --result passed."""
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)

        # Create BDD structure with mandatory AC
        runner.invoke(app, ["bdd", "init", "--feature", "Test feature"])
        runner.invoke(
            app,
            ["bdd", "example", "add", "--title", "Test fails",
             "--given", "a", "--when", "b", "--then", "c",
             "--acceptance-criterion", "ac-0001"],
        )

        # Create failing Cucumber JSON report
        report = [
            {
                "name": "Test feature",
                "elements": [
                    {
                        "type": "scenario",
                        "name": "Test fails",
                        "steps": [
                            {"name": "a", "result": {"status": "passed"}},
                            {
                                "name": "b",
                                "result": {
                                    "status": "failed",
                                    "error_message": "Expected X",
                                },
                            },
                        ],
                    }
                ],
            }
        ]
        report_path = tmp_path / "cucumber.json"
        report_path.write_text(json.dumps(report))

        # Setup lifecycle
        runner.invoke(app, ["implement", "start"])
        runner.invoke(app, ["implement", "finish", "--summary", "Done"])
        runner.invoke(app, ["validate", "start"])

        # Import failing report
        runner.invoke(
            app,
            [
                "--json", "validate", "import-bdd-report",
                str(report_path),
                "--format", "cucumber-json",
            ],
        )

        # Try to finish validation as passed - should fail because AC check is failing
        result = runner.invoke(
            app,
            ["validate", "finish", "--result", "passed", "--summary", "All good"],
        )
        # This should fail because the criterion check is failing
        assert result.exit_code != 0


def _init_project(tmp_path) -> None:
    """Initialize a minimal taskledger project."""
    runner.invoke(app, ["init"])
    runner.invoke(app, ["task", "create", "Test task"])
    runner.invoke(app, ["task", "activate", "task-0001"])
