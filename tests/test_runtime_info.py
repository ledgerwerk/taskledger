"""Tests for the taskledger runtime command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from taskledger.compat.ledgercore import LedgercoreVersionInfo


class TestRuntimeInfo:
    """Tests for runtime provenance reporting."""

    def test_runtime_command_reports_versions(self) -> None:
        from taskledger.services.runtime_info import collect_runtime_info

        info = collect_runtime_info()
        assert info.taskledger_version
        assert info.taskledger_package_file
        assert info.taskledger_cli_file
        assert info.taskledger_migrate_file
        assert info.python_executable
        assert info.migration_contract_version == 3

    def test_runtime_command_reports_migrate_commands(self) -> None:
        from taskledger.services.runtime_info import collect_runtime_info

        info = collect_runtime_info()
        commands = list(info.available_migrate_commands)
        assert "inspect" in commands
        assert "status" in commands
        assert "plan" in commands
        assert "apply" in commands

    def test_runtime_command_reports_ledgercore(self) -> None:
        from taskledger.services.runtime_info import collect_runtime_info

        info = collect_runtime_info()
        # Ledgercore should be importable in the test environment
        assert info.ledgercore_version is not None
        assert info.ledgercore_package_file is not None
        assert info.ledgercore_module_version == info.ledgercore_version
        assert info.ledgercore_distribution_version is not None
        assert info.ledgercore_required == ">=0.6.1,<0.7.0"
        assert info.ledgercore_version_mismatch is False

    def test_runtime_to_dict_has_expected_keys(self) -> None:
        from taskledger.services.runtime_info import collect_runtime_info

        info = collect_runtime_info()
        d = info.to_dict()
        assert d["kind"] == "taskledger_runtime"
        assert "taskledger_version" in d
        assert "taskledger_package_file" in d
        assert "available_migrate_commands" in d
        assert "ledgercore_module_version" in d
        assert "ledgercore_distribution_version" in d
        assert "ledgercore_version_mismatch" in d
        assert "ledgercore_required" in d
        assert "ledgercore_compatible" in d

    def test_runtime_human_summary_is_nonempty(self) -> None:
        from taskledger.services.runtime_info import collect_runtime_info

        info = collect_runtime_info()
        summary = info.human_summary()
        assert "TASKLEDGER RUNTIME" in summary
        assert "Migration" in summary

    def test_runtime_cli_command(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from taskledger.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["--root", str(tmp_path), "runtime"])
        assert result.exit_code == 0
        assert "TASKLEDGER RUNTIME" in result.output

    def test_runtime_cli_json(self, tmp_path: Path) -> None:
        import json

        from typer.testing import CliRunner

        from taskledger.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["--root", str(tmp_path), "--json", "runtime"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["result"]["kind"] == "taskledger_runtime"

    def test_runtime_reports_module_distribution_mismatch(self) -> None:
        from taskledger.services.runtime_info import collect_runtime_info

        probe = LedgercoreVersionInfo(
            module_version="0.5.1",
            distribution_version="0.6.1",
            package_file="/tmp/ledgercore/__init__.py",
            version_mismatch=True,
        )
        with patch(
            "taskledger.services.runtime_info.inspect_ledgercore_version",
            return_value=probe,
        ):
            info = collect_runtime_info()

        assert info.ledgercore_module_version == "0.5.1"
        assert info.ledgercore_distribution_version == "0.6.1"
        assert info.ledgercore_version_mismatch is True
        assert info.ledgercore_compatible is False
