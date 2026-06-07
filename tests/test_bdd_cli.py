"""Tests for BDD CLI commands."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from taskledger.cli import app

runner = CliRunner()


class TestBddInit:
    def test_bdd_init_json(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)

        result = runner.invoke(
            app, ["--json", "bdd", "init", "--feature", "Task lifecycle gates"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["command"] == "bdd.init"
        assert payload["result"]["feature"]["title"] == "Task lifecycle gates"

    def test_bdd_init_human(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)

        result = runner.invoke(
            app, ["bdd", "init", "--feature", "Test feature"]
        )
        assert result.exit_code == 0
        assert "BDD initialized" in result.stdout

    def test_bdd_init_twice_fails(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)

        runner.invoke(app, ["bdd", "init", "--feature", "First"])
        result = runner.invoke(app, ["bdd", "init", "--feature", "Second"])
        assert result.exit_code != 0


class TestBddStatus:
    def test_bdd_status_json(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)
        runner.invoke(app, ["bdd", "init", "--feature", "Test"])

        result = runner.invoke(app, ["--json", "bdd", "status"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["result"]["feature_title"] == "Test"
        assert payload["result"]["rule_count"] == 0


class TestBddRuleCommands:
    def test_rule_add_json(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)
        runner.invoke(app, ["bdd", "init", "--feature", "Test"])

        result = runner.invoke(
            app, ["--json", "bdd", "rule", "add", "Implementation requires plan"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["result"]["rule"]["title"] == "Implementation requires plan"
        assert payload["result"]["rule"]["id"] == "rule-0001"

    def test_rule_list_json(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)
        runner.invoke(app, ["bdd", "init", "--feature", "Test"])
        runner.invoke(app, ["bdd", "rule", "add", "Rule 1"])
        runner.invoke(app, ["bdd", "rule", "add", "Rule 2"])

        result = runner.invoke(app, ["--json", "bdd", "rule", "list"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert len(payload["result"]["rules"]) == 2

    def test_rule_show_json(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)
        runner.invoke(app, ["bdd", "init", "--feature", "Test"])
        runner.invoke(app, ["bdd", "rule", "add", "My rule"])

        result = runner.invoke(app, ["--json", "bdd", "rule", "show", "rule-0001"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["result"]["rule"]["id"] == "rule-0001"


class TestBddExampleCommands:
    def test_example_add_json(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)
        runner.invoke(app, ["bdd", "init", "--feature", "Test"])

        result = runner.invoke(
            app,
            [
                "--json", "bdd", "example", "add",
                "--title", "Test scenario",
                "--given", "something",
                "--when", "action",
                "--then", "result",
                "--acceptance-criterion", "ac-0001",
            ],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        ex = payload["result"]["example"]
        assert ex["title"] == "Test scenario"
        assert ex["status"] == "linked"
        assert ex["acceptance_criteria"] == ["ac-0001"]

    def test_example_list_json(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)
        runner.invoke(app, ["bdd", "init", "--feature", "Test"])
        runner.invoke(
            app,
            ["bdd", "example", "add", "--title", "Ex1",
             "--given", "a", "--when", "b", "--then", "c"],
        )

        result = runner.invoke(app, ["--json", "bdd", "example", "list"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert len(payload["result"]["examples"]) == 1

    def test_example_show_json(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)
        runner.invoke(app, ["bdd", "init", "--feature", "Test"])
        runner.invoke(
            app,
            ["bdd", "example", "add", "--title", "Ex1",
             "--given", "a", "--when", "b", "--then", "c"],
        )

        result = runner.invoke(app, ["--json", "bdd", "example", "show", "bdd-0001"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["result"]["example"]["id"] == "bdd-0001"

    def test_example_link_ac(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)
        runner.invoke(app, ["bdd", "init", "--feature", "Test"])
        runner.invoke(
            app,
            ["bdd", "example", "add", "--title", "Ex1",
             "--given", "a", "--when", "b", "--then", "c"],
        )

        result = runner.invoke(
            app, ["--json", "bdd", "example", "link-ac", "bdd-0001", "ac-0001"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert "ac-0001" in payload["result"]["example"]["acceptance_criteria"]
        assert payload["result"]["example"]["status"] == "linked"


class TestBddGherkinExport:
    def test_gherkin_export_json(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)
        runner.invoke(app, ["bdd", "init", "--feature", "Test feature"])
        runner.invoke(
            app,
            ["bdd", "example", "add", "--title", "Test scenario",
             "--given", "a", "--when", "b", "--then", "c"],
        )

        out = str(tmp_path / "test.feature")
        result = runner.invoke(
            app, ["--json", "bdd", "gherkin-export", "--out", out]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert "bdd-0001" in payload["result"]["exported_examples"]


class TestBddArchledgerBridge:
    def test_archledger_candidate(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)
        runner.invoke(app, ["bdd", "init", "--feature", "Test feature"])
        runner.invoke(
            app,
            ["bdd", "example", "add", "--title", "Lifecycle gate test",
             "--given", "a task", "--when", "action", "--then", "result",
             "--acceptance-criterion", "ac-0001"],
        )

        out = str(tmp_path / "candidate.md")
        result = runner.invoke(
            app, ["--json", "bdd", "archledger-candidate", "bdd-0001", "--out", out]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["result"]["candidate"]["suggested_type"] == "runtime_scenario"

    def test_example_link_archledger(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _init_project(tmp_path)
        runner.invoke(app, ["bdd", "init", "--feature", "Test feature"])
        runner.invoke(
            app,
            ["bdd", "example", "add", "--title", "Test",
             "--given", "a", "--when", "b", "--then", "c"],
        )

        result = runner.invoke(
            app,
            ["--json", "bdd", "example", "link-archledger",
             "bdd-0001", "al_runtime_0123"],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert "al_runtime_0123" in payload["result"]["example"]["archledger_refs"]


def _init_project(tmp_path) -> None:
    """Initialize a minimal taskledger project."""
    runner.invoke(app, ["init"])
    # Activate a task for testing
    runner.invoke(app, ["task", "create", "Test task"])
    runner.invoke(app, ["task", "activate", "task-0001"])
