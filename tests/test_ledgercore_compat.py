"""Tests for the Ledgercore compatibility boundary."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from taskledger.compat.ledgercore import (
    TaskledgerCLIState,
    _parse_version,
    get_cli_apis,
    get_migration_apis,
    make_cli_error_envelope,
    make_cli_state,
    make_cli_success_envelope,
    require_ledgercore_060,
    translate_ledgercore_error,
)


class TestVersionCheck:
    """Test minimum version validation."""

    def test_parse_version_valid(self) -> None:
        assert _parse_version("0.6.0") == (0, 6, 0)
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_parse_version_invalid(self) -> None:
        with pytest.raises(ValueError, match="Invalid version"):
            _parse_version("invalid")
        with pytest.raises(ValueError, match="Invalid version"):
            _parse_version("0.6")

    def test_require_ledgercore_060_succeeds(self) -> None:
        """Should not raise with installed ledgercore 0.6.0."""
        require_ledgercore_060()

    def test_require_ledgercore_old_version_fails(self) -> None:
        """Should raise with ledgercore < 0.6.0."""
        with patch("ledgercore.__version__", "0.5.0"):
            with pytest.raises(RuntimeError, match=">=0.6.0,<0.7.0"):
                require_ledgercore_060()

    def test_require_ledgercore_new_version_fails(self) -> None:
        """Should raise with ledgercore >= 0.7.0."""
        with patch("ledgercore.__version__", "0.7.0"):
            with pytest.raises(RuntimeError, match=">=0.6.0,<0.7.0"):
                require_ledgercore_060()


class TestCLIImports:
    """Test that CLI API imports work correctly."""

    def test_get_cli_apis_returns_dict(self) -> None:
        apis = get_cli_apis()
        assert isinstance(apis, dict)
        assert "SuccessEnvelope" in apis
        assert "ErrorEnvelope" in apis
        assert "CommonCLIState" in apis
        assert "CommandMetadata" in apis
        assert "ExitCode" in apis

    def test_get_migration_apis_returns_dict(self) -> None:
        apis = get_migration_apis()
        assert isinstance(apis, dict)
        assert "StorageMigrationItem" in apis
        assert "StorageMigrationPlan" in apis
        assert "execute_storage_migration" in apis
        assert "recover_storage_migration" in apis


class TestCLIState:
    """Test TaskledgerCLIState wrapper."""

    def test_cli_state_properties(self, tmp_path: Path) -> None:
        state = make_cli_state(
            root=tmp_path,
            json_output=True,
            quiet=False,
            verbose=False,
        )
        assert isinstance(state, TaskledgerCLIState)
        assert state.cwd == tmp_path
        assert state.json_output is True
        assert state.requested_root == tmp_path
        assert state.resolved_root is None

    def test_cli_state_resolved_root(self, tmp_path: Path) -> None:
        state = make_cli_state(root=tmp_path)
        resolved = tmp_path / "resolved"
        # TaskledgerCLIState is frozen, so we need to create a new one
        from taskledger.compat.ledgercore import TaskledgerCLIState

        new_state = TaskledgerCLIState(
            common=state.common,
            requested_root=tmp_path,
            resolved_root=resolved,
            no_log=False,
        )
        assert new_state.cwd == resolved


class TestEnvelopes:
    """Test envelope creation."""

    def test_success_envelope_shape(self) -> None:
        envelope = make_cli_success_envelope(
            command="task show",
            result={"task_id": "task-0001"},
            events=(),
            warnings=(),
        )
        d = envelope.as_mapping()
        assert d["schema"] == "ledgerwerk.cli.v1"
        assert d["ok"] is True
        assert d["tool"] == "taskledger"
        assert d["command"] == "task show"
        assert d["result"]["task_id"] == "task-0001"
        assert isinstance(d["events"], (tuple, list))
        assert isinstance(d["warnings"], (tuple, list))

    def test_error_envelope_shape(self) -> None:
        envelope = make_cli_error_envelope(
            command="task show",
            error={"code": "not_found", "message": "Task not found"},
            events=(),
            warnings=(),
        )
        d = envelope.as_mapping()
        assert d["schema"] == "ledgerwerk.cli.v1"
        assert d["ok"] is False
        assert d["tool"] == "taskledger"
        assert d["command"] == "task show"
        assert d["error"]["code"] == "not_found"

    def test_envelope_coerces_string_warnings(self) -> None:
        envelope = make_cli_success_envelope(
            command="sync.git.status",
            result={},
            warnings=("A compatibility warning.",),
        )

        assert envelope.as_mapping()["warnings"] == [
            {
                "code": "taskledger_warning",
                "message": "A compatibility warning.",
                "replacement": None,
            }
        ]


class TestErrorTranslation:
    """Test error translation preserves codes."""

    def test_translate_generic_error(self) -> None:
        exc = ValueError("test error")
        result = translate_ledgercore_error(exc, command="test cmd")
        assert "taskledger_valueerror" in result["code"]
        assert result["message"] == "test error"
        assert "domain_code" in result["details"]
        assert "ledgercore_code" in result["details"]

    def test_translate_error_with_code(self) -> None:
        class CustomError(Exception):
            code = "CUSTOM_CODE"

        exc = CustomError("custom message")
        result = translate_ledgercore_error(exc)
        assert "taskledger_custom_code" in result["code"]
        assert result["details"]["ledgercore_code"] == "CUSTOM_CODE"
