from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Redirect bytecode to .pytest_cache/pycache to keep the source tree clean
# while allowing persistent bytecode reuse across repeated pytest runs.
PYTEST_PYCACHE = ROOT / ".pytest_cache" / "pycache"
if sys.pycache_prefix is None:
    sys.pycache_prefix = str(PYTEST_PYCACHE)
sys.dont_write_bytecode = False


import shutil
import weakref
from typing import Any

import pytest
import typer.testing as typer_testing
from typer import Typer
from typer.main import get_command as _typer_get_command
from typer.testing import CliRunner as _TyperCliRunner

# Some test modules still instantiate ``CliRunner(mix_stderr=False)`` for
# historical reasons. Newer Typer/Click releases reject that argument, so the
# constructor wrapper below discards it. This shim exists only for test
# source compatibility and is unrelated to command caching.
_original_cli_runner_init = _TyperCliRunner.__init__


def _patched_cli_runner_init(
    self: _TyperCliRunner,
    *args: Any,
    **kwargs: Any,
) -> None:
    kwargs.pop("mix_stderr", None)
    _original_cli_runner_init(self, *args, **kwargs)


_TyperCliRunner.__init__ = _patched_cli_runner_init  # type: ignore[assignment]

from tests.support.builders import (
    create_approved_task,
    create_done_task,
    create_failed_validation_task,
    create_implemented_task,
    init_workspace,
)


@pytest.fixture(autouse=True)
def _taskledger_test_io_mode(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enable fast I/O for ordinary tests; real fsync for durable_io tests.

    Tests marked with ``durable_io`` verify real flush/fsync/replace
    durability behavior and must run with the production default.
    All other tests skip fsync via ``TASKLEDGER_TEST_FAST_IO=1".
    """
    if request.node.get_closest_marker("durable_io") is not None:
        monkeypatch.delenv("TASKLEDGER_TEST_FAST_IO", raising=False)
        return
    monkeypatch.setenv("TASKLEDGER_TEST_FAST_IO", "1")


# Typer rebuilds the full Click command tree on every CliRunner.invoke call.
# Taskledger's CLI is intentionally broad, so repeated rebuilds dominate the
# CLI-heavy test suite, especially on Windows. Cache the immutable Click
# command tree per Typer app for tests; each invocation still gets a fresh
# Click context.
#
# The cache is implemented by swapping the private command-lookup helper used
# by ``typer.testing``. Typer's own ``CliRunner.invoke`` then calls our cached
# function instead of rebuilding the command tree. We do NOT replace
# ``CliRunner.invoke`` with ``click.testing.CliRunner.invoke`` because the two
# runner implementations do not share instance state; on Click 8.1.x the
# cross-class call reads ``self.mix_stderr`` and raises AttributeError.
_CLICK_COMMAND_CACHE: weakref.WeakKeyDictionary[Typer, Any] = (
    weakref.WeakKeyDictionary()
)


def _cached_click_command(app: Typer) -> Any:
    cached = _CLICK_COMMAND_CACHE.get(app)
    if cached is None:
        cached = _typer_get_command(app)
        _CLICK_COMMAND_CACHE[app] = cached
    return cached


if hasattr(typer_testing, "_get_command"):
    typer_testing._get_command = _cached_click_command  # type: ignore[attr-defined]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Remove local pytest/Python cache artifacts when explicitly requested."""
    if hasattr(session.config, "workerinput"):
        return
    if exitstatus == pytest.ExitCode.INTERRUPTED:
        return
    if os.environ.get("TASKLEDGER_TEST_CLEAN_PYCACHE", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        return
    shutil.rmtree(ROOT / ".pytest_cache", ignore_errors=True)
    cache_roots = [
        ROOT / "taskledger",
        ROOT / "tests",
        ROOT / "docs",
        ROOT / "__pycache__",
    ]
    for cache_root in cache_roots:
        if cache_root.name == "__pycache__":
            shutil.rmtree(cache_root, ignore_errors=True)
            continue
        if not cache_root.exists():
            continue
        for cache_dir in cache_root.rglob("__pycache__"):
            shutil.rmtree(cache_dir, ignore_errors=True)


def _copy_template(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst, dirs_exist_ok=True)
    return dst


@pytest.fixture(scope="session")
def empty_workspace_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("taskledger-empty-template")
    init_workspace(root)
    return root


@pytest.fixture
def empty_workspace(tmp_path: Path, empty_workspace_template: Path) -> Path:
    return _copy_template(empty_workspace_template, tmp_path / "workspace")


@pytest.fixture(scope="session")
def approved_workspace_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("taskledger-approved-template")
    init_workspace(root)
    create_approved_task(root, title="Approved task", slug="approved-task")
    return root


@pytest.fixture
def approved_workspace(tmp_path: Path, approved_workspace_template: Path) -> Path:
    return _copy_template(approved_workspace_template, tmp_path / "workspace")


@pytest.fixture(scope="session")
def implemented_workspace_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("taskledger-implemented-template")
    init_workspace(root)
    create_implemented_task(root, title="Implemented task", slug="implemented-task")
    return root


@pytest.fixture
def implemented_workspace(tmp_path: Path, implemented_workspace_template: Path) -> Path:
    return _copy_template(implemented_workspace_template, tmp_path / "workspace")


@pytest.fixture(scope="session")
def done_workspace_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("taskledger-done-template")
    init_workspace(root)
    create_done_task(root, title="Done task", slug="done-task")
    return root


@pytest.fixture
def done_workspace(tmp_path: Path, done_workspace_template: Path) -> Path:
    return _copy_template(done_workspace_template, tmp_path / "workspace")


@pytest.fixture(scope="session")
def failed_validation_workspace_template(
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    root = tmp_path_factory.mktemp("taskledger-failed-validation-template")
    init_workspace(root)
    create_failed_validation_task(
        root, title="Failed validation task", slug="failed-validation-task"
    )
    return root


@pytest.fixture
def failed_validation_workspace(
    tmp_path: Path, failed_validation_workspace_template: Path
) -> Path:
    return _copy_template(failed_validation_workspace_template, tmp_path / "workspace")
