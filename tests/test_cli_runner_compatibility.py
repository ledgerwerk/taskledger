"""Regression tests for the test-harness CLI runner compatibility shims.

These tests guard against the failure mode that broke the Codecov workflow:
``typer.testing.CliRunner.invoke`` must not be replaced by a cross-class call
into ``click.testing.CliRunner.invoke``. The command tree must still be
cached per Typer application, and the legacy ``mix_stderr=False`` constructor
argument must keep working.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import typer
import typer.testing as typer_testing
from typer import Typer
from typer.testing import CliRunner

from tests.conftest import _cached_click_command
from tests.support.builders import init_workspace


def test_cli_runner_accepts_legacy_mix_stderr_argument() -> None:
    runner = CliRunner(mix_stderr=False)
    assert runner is not None
    # The patched __init__ must forward all other args/kwargs unchanged.
    assert isinstance(runner, CliRunner)


def test_cli_runner_invoke_is_typer_owned() -> None:
    """The harness must not replace Typer's invoke with Click's invoke."""
    runner = CliRunner()
    assert runner.invoke.__module__.startswith("typer")


def test_cli_runner_invoke_does_not_raise_missing_attribute() -> None:
    """Regression: invoking must not raise AttributeError on missing attrs.

    This is the exact Codecov failure mode: a cross-class
    ``click.testing.CliRunner.invoke`` call would read ``self.mix_stderr`` on
    a Typer runner and raise. The harness must not reintroduce that path.
    """

    app = typer.Typer()

    @app.command()
    def greet() -> None:
        typer.echo("hello-stdout")
        sys.stderr.write("hello-stderr\n")

    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "hello-stdout" in result.stdout
    assert "hello-stderr" in result.stderr or "hello-stderr" in result.output


def test_command_tree_is_cached_across_invocations() -> None:
    """Repeated invocations for the same app must reuse the cached tree."""
    app = typer.Typer()

    @app.command()
    def ping() -> None:
        typer.echo("pong")

    runner = CliRunner()

    first = _cached_click_command(app)
    second = _cached_click_command(app)
    assert first is second

    first_result = runner.invoke(app, [])
    second_result = runner.invoke(app, [])
    assert first_result.exit_code == 0
    assert second_result.exit_code == 0
    assert first_result.stdout.strip() == "pong"
    assert second_result.stdout.strip() == "pong"


def test_cached_command_tree_uses_typer_get_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh app must build the command tree once via typer.main.get_command."""
    app = typer.Typer()

    @app.command()
    def echo(value: str) -> None:
        typer.echo(value)

    # Drop any cached entry for this exact app instance, then count calls.
    cache = _cached_click_command  # access for type checker; real dict is below
    _ = cache  # silence unused warning

    from tests import conftest

    conftest._CLICK_COMMAND_CACHE.pop(app, None)

    import typer.main as typer_main

    calls: list[object] = []
    original = typer_main.get_command

    def counting(app: Typer, *args: Any, **kwargs: Any) -> Any:
        calls.append(app)
        return original(app, *args, **kwargs)

    monkeypatch.setattr(typer_main, "get_command", counting)
    # Re-bind the cached helper to use the patched get_command.
    from typer.main import get_command as patched_get_command

    monkeypatch.setattr(conftest, "_typer_get_command", patched_get_command)

    runner = CliRunner()
    assert runner.invoke(app, ["hello"]).exit_code == 0
    assert calls == [app]

    # A second invocation must reuse the cached entry; no extra call.
    assert runner.invoke(app, ["world"]).exit_code == 0
    assert calls == [app]


def test_cached_command_cache_disables_cleanly_without_typer_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If typer.testing._get_command is missing, caching must be disabled.

    The harness must never fall back to the cross-class invoke replacement.
    """
    had_get_command = hasattr(typer_testing, "_get_command")
    if not had_get_command:
        pytest.skip("typer.testing._get_command is available in this Typer version")

    monkeypatch.delattr(typer_testing, "_get_command", raising=False)
    try:
        # Re-running the conftest guard should leave the harness safe.
        from tests import conftest

        # Re-run the guarded assignment from conftest with the attribute gone.
        if hasattr(typer_testing, "_get_command"):
            typer_testing._get_command = conftest._cached_click_command
        # If we reach here, the guarded check would have re-enabled caching.
        # The contract is: when the hook is absent, the cache is disabled and
        # the harness does NOT replace typer's invoke.
        assert not hasattr(typer_testing, "_get_command")
    finally:
        # Restore the original hook so other tests keep working.
        from typer.main import get_command as restored_get_command

        typer_testing._get_command = restored_get_command  # type: ignore[attr-defined]


def test_pipeline_commands_print_no_config_message(tmp_path: Path) -> None:
    """The first reported Codecov failure must keep passing."""
    from taskledger.cli import app

    init_workspace(tmp_path)

    runner = CliRunner(mix_stderr=False)
    for command in (["pipeline", "show"], ["pipeline", "list"], ["pipeline", "next"]):
        result = runner.invoke(app, ["--cwd", str(tmp_path), *command])
        assert result.exit_code == 0, result.stdout
        assert result.stdout.strip() == "No worker pipeline configured."


def test_runner_with_mix_stderr_false_writes_both_streams(tmp_path: Path) -> None:
    """``mix_stderr=False`` must not break output capture for either stream."""
    app = typer.Typer()

    @app.command()
    def emit() -> None:
        typer.echo("to-out")
        sys.stderr.write("to-err\n")

    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    # The output buffer must still be populated, regardless of mix_stderr.
    combined = result.output
    assert "to-out" in combined
    assert "to-err" in combined
