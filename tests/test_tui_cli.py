"""CLI tests for the optional ``taskledger tui`` command.

These tests do not import Textual at module load. The help test exercises the
typer help path, and the missing-textual test installs a sys.modules poison
before invoking the command so the import guard fires.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def test_tui_help_is_available_without_importing_textual() -> None:
    # Snapshot module state so we can prove no textual import happens during help.
    before_textual = {
        name for name in sys.modules if name == "textual" or name.startswith("textual.")
    }
    result = runner.invoke(app, ["tui", "--help"])
    after_textual = {
        name for name in sys.modules if name == "textual" or name.startswith("textual.")
    }
    assert result.exit_code == 0, result.stdout
    assert "--refresh-seconds" in result.stdout
    assert "--no-refresh" in result.stdout
    assert "--include-archived" in result.stdout
    assert "--layout" in result.stdout
    assert "TASK_ARG" in result.stdout or "task_arg" in result.stdout
    # --help must not have pulled textual into the process.
    assert after_textual == before_textual, (
        "taskledger tui --help imported textual: "
        f"{sorted(after_textual - before_textual)}"
    )


def test_tui_help_does_not_need_workspace_init(tmp_path: Path) -> None:
    """``--help`` must not require a valid taskledger workspace."""

    result = runner.invoke(app, ["--cwd", str(tmp_path), "tui", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "Auto-refresh the snapshot" in result.stdout


def test_tui_command_is_in_inventory() -> None:
    result = runner.invoke(app, ["commands", "--surface", "human"])
    assert result.exit_code == 0
    assert (
        "tui " in result.stdout or "\ntui " in result.stdout or "tui\t" in result.stdout
    )
    # Strict line check:
    assert any(line.split()[0] == "tui" for line in result.stdout.splitlines())


def test_tui_missing_textual_emits_optional_dependency_error(tmp_path: Path) -> None:
    """When textual is unavailable, tui emits a structured error."""

    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0

    saved_modules = {}
    poisoned: list[str] = []

    class _Poison:
        def __getattr__(self, name: str) -> object:
            raise ImportError(f"textual is blocked: {name}")

    for name in list(sys.modules):
        if name == "textual" or name.startswith("textual."):
            saved_modules[name] = sys.modules.pop(name)
            poisoned.append(name)
    sys.modules["textual"] = _Poison()
    try:
        result = runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "tui"],
        )
    finally:
        sys.modules.pop("textual", None)
        for name in poisoned:
            if name in saved_modules:
                sys.modules[name] = saved_modules[name]
    assert result.exit_code == 2, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "OPTIONAL_DEPENDENCY_MISSING"
    assert payload["error"]["exit_code"] == 2
    remediation = payload["error"]["remediation"]
    assert any("install" in step and "[tui]" in step for step in remediation)


def test_tui_rejects_conflicting_task_ref_and_option(tmp_path: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "tui",
            "task-0001",
            "--task",
            "task-0002",
        ],
    )
    # The conflict check fires before the textual import guard.
    assert result.exit_code == 2, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "USAGE_ERROR"
    assert "TASK_REF" in payload["error"]["message"]
    assert "--task" in payload["error"]["message"]


def test_tui_rejects_invalid_layout(tmp_path: Path) -> None:
    """Invalid --layout values exit USAGE_ERROR before textual is imported."""
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0

    before_textual = {
        name for name in sys.modules if name == "textual" or name.startswith("textual.")
    }
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "tui",
            "--layout",
            "tiny",
        ],
    )
    after_textual = {
        name for name in sys.modules if name == "textual" or name.startswith("textual.")
    }
    assert result.exit_code == 2, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "USAGE_ERROR"
    assert "--layout" in payload["error"]["message"]
    # Validation must fire before the textual import guard.
    assert after_textual == before_textual


def test_tui_app_boots_with_pilot(tmp_path: Path) -> None:
    """Smoke test: the Textual app starts, renders, refreshes, and exercises
    phase-2 navigation without raising.

    Skipped automatically when textual is not installed.
    """
    pytest = __import__("pytest")
    pytest.importorskip("textual")

    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    _create_task_via_runner(tmp_path, "Boot smoke")

    from taskledger.tui.app import TaskledgerTui

    tui_app = TaskledgerTui(workspace_root=tmp_path)
    import asyncio

    async def _drive() -> None:
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            # Switch tabs (phase 1).
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("4")
            await pilot.pause()
            # Stage filter shortcut (phase 2).
            await pilot.press("a")
            await pilot.pause()
            # Toggle archived view (phase 2).
            await pilot.press("t")
            await pilot.pause()
            # Help overlay (phase 1).
            await pilot.press("?")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("q")

    asyncio.run(_drive())


def _create_task_via_runner(tmp_path: Path, title: str) -> None:
    res = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "create", title],
    )
    assert res.exit_code == 0, res.stdout


def _activate_task_via_runner(tmp_path: Path, task_ref: str) -> None:
    """Activate a task so the TUI read model resolves a selected task."""
    res = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "activate", task_ref],
    )
    assert res.exit_code == 0, res.stdout


def test_tui_compact_mode_switches_between_list_and_detail(tmp_path: Path) -> None:
    """Compact layout shows one pane at a time and toggles list<->detail.

    Skipped automatically when textual is not installed.
    """
    pytest = __import__("pytest")
    pytest.importorskip("textual")

    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    _create_task_via_runner(tmp_path, "Compact smoke")
    _activate_task_via_runner(tmp_path, "task-0001")

    import asyncio

    from taskledger.tui.app import TaskledgerTui

    tui_app = TaskledgerTui(workspace_root=tmp_path, layout="compact")

    async def _drive() -> None:
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            classes = set(tui_app.screen.classes)
            # No explicit task_ref -> compact starts in list view.
            assert "-compact" in classes
            assert "-list" in classes

            tui_app.action_show_detail()
            await pilot.pause()
            classes = set(tui_app.screen.classes)
            assert "-detail" in classes
            assert "-list" not in classes

            tui_app.action_show_list()
            await pilot.pause()
            classes = set(tui_app.screen.classes)
            assert "-list" in classes
            assert "-detail" not in classes

    asyncio.run(_drive())


def test_tui_compact_mode_starts_in_detail_with_task_ref(tmp_path: Path) -> None:
    """Launching with an explicit task_ref opens the detail pane in compact mode."""
    pytest = __import__("pytest")
    pytest.importorskip("textual")

    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    _create_task_via_runner(tmp_path, "Compact detail smoke")
    _activate_task_via_runner(tmp_path, "task-0001")

    import asyncio

    from taskledger.tui.app import TaskledgerTui

    tui_app = TaskledgerTui(
        workspace_root=tmp_path,
        layout="compact",
        task_ref="task-0001",
    )

    async def _drive() -> None:
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            classes = set(tui_app.screen.classes)
            assert "-compact" in classes
            assert "-detail" in classes
            assert "-list" not in classes

    asyncio.run(_drive())


def test_tui_wide_mode_never_sets_compact_class(tmp_path: Path) -> None:
    """--layout wide forces the two-pane layout regardless of width."""
    pytest = __import__("pytest")
    pytest.importorskip("textual")

    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0
    _create_task_via_runner(tmp_path, "Wide smoke")

    import asyncio

    from taskledger.tui.app import TaskledgerTui

    tui_app = TaskledgerTui(workspace_root=tmp_path, layout="wide")

    async def _drive() -> None:
        async with tui_app.run_test() as pilot:
            await pilot.pause()
            classes = set(tui_app.screen.classes)
            assert "-wide" in classes
            assert "-compact" not in classes

    asyncio.run(_drive())
