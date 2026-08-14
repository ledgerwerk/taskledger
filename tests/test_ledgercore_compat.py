"""Tests for the Ledgercore compatibility boundary."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from unittest.mock import patch

import pytest

from taskledger.compat.ledgercore import (
    LEDGERCORE_REQUIREMENT,
    TaskledgerCLIState,
    _parse_version,
    get_cli_apis,
    get_migration_apis,
    inspect_ledgercore_version,
    ledgercore_is_compatible,
    make_cli_error_envelope,
    make_cli_state,
    make_cli_success_envelope,
    require_ledgercore_060,
    require_supported_ledgercore,
    translate_ledgercore_error,
)


class TestVersionCheck:
    """Test minimum version validation."""

    def test_parse_version_valid(self) -> None:
        assert str(_parse_version("0.6.0")) == "0.6.0"
        assert str(_parse_version("1.2.3")) == "1.2.3"
        assert str(_parse_version("0.6.1+local")) == "0.6.1+local"

    def test_parse_version_invalid(self) -> None:
        with pytest.raises(ValueError, match="Invalid version"):
            _parse_version("invalid")

    def test_require_ledgercore_060_succeeds(self) -> None:
        """The compatibility alias accepts the supported boundary."""
        with (
            patch("ledgercore.__version__", "0.6.1"),
            patch(
                "taskledger.compat.ledgercore.importlib_metadata.version",
                return_value="0.6.1",
            ),
        ):
            require_supported_ledgercore()
            require_ledgercore_060()

    def test_require_ledgercore_old_version_fails(self) -> None:
        """Should raise with ledgercore < 0.6.1."""
        with (
            patch("ledgercore.__version__", "0.5.0"),
            patch(
                "taskledger.compat.ledgercore.importlib_metadata.version",
                return_value="0.5.0",
            ),
        ):
            with pytest.raises(RuntimeError, match=LEDGERCORE_REQUIREMENT):
                require_ledgercore_060()

    def test_require_ledgercore_new_version_fails(self) -> None:
        """Should raise with ledgercore >= 0.7.0."""
        with (
            patch("ledgercore.__version__", "0.7.0"),
            patch(
                "taskledger.compat.ledgercore.importlib_metadata.version",
                return_value="0.7.0",
            ),
        ):
            with pytest.raises(RuntimeError, match=LEDGERCORE_REQUIREMENT):
                require_ledgercore_060()

    def test_version_probe_reports_module_distribution_and_path(self) -> None:
        with (
            patch("ledgercore.__version__", "0.6.1"),
            patch(
                "taskledger.compat.ledgercore.importlib_metadata.version",
                return_value="0.6.1",
            ),
        ):
            info = inspect_ledgercore_version()

        assert info.module_version == "0.6.1"
        assert info.distribution_version == "0.6.1"
        assert info.package_file
        assert info.version_mismatch is False
        assert ledgercore_is_compatible(info) is True

    def test_module_distribution_mismatch_fails_strict_compatibility(self) -> None:
        with (
            patch("ledgercore.__version__", "0.5.1"),
            patch(
                "taskledger.compat.ledgercore.importlib_metadata.version",
                return_value="0.6.1",
            ),
        ):
            info = inspect_ledgercore_version()
            assert info.version_mismatch is True
            assert ledgercore_is_compatible(info) is False
            with pytest.raises(
                RuntimeError,
                match="module reports 0.5.1.*distribution reports 0.6.1",
            ):
                require_supported_ledgercore()

    @pytest.mark.parametrize(
        ("version", "compatible"),
        [
            ("0.6.0", False),
            ("0.6.1.dev1", False),
            ("0.6.1rc1", False),
            ("0.6.1", True),
            ("0.6.1.post1", True),
            ("0.6.1+local", True),
            ("0.6.9", True),
            ("0.7.0.dev1", False),
            ("0.7.0", False),
        ],
    )
    def test_supported_version_boundaries(
        self,
        version: str,
        compatible: bool,
    ) -> None:
        with (
            patch("ledgercore.__version__", version),
            patch(
                "taskledger.compat.ledgercore.importlib_metadata.version",
                return_value=version,
            ),
        ):
            info = inspect_ledgercore_version()
            assert ledgercore_is_compatible(info) is compatible
            if compatible:
                require_supported_ledgercore()
            else:
                with pytest.raises(RuntimeError, match=LEDGERCORE_REQUIREMENT):
                    require_supported_ledgercore()

    def test_missing_distribution_metadata_is_not_compatible(self) -> None:
        with (
            patch("ledgercore.__version__", "0.6.1"),
            patch(
                "taskledger.compat.ledgercore.importlib_metadata.version",
                side_effect=importlib.metadata.PackageNotFoundError("ledgercore"),
            ),
        ):
            info = inspect_ledgercore_version()
            assert info.distribution_version is None
            assert ledgercore_is_compatible(info) is False
            with pytest.raises(RuntimeError, match="distribution metadata"):
                require_supported_ledgercore()


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
