from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep the repository tree clean when running pytest from the checkout.
sys.dont_write_bytecode = True


# Tests create many short-lived Markdown/YAML records under tmp_path.
# Production durability still fsyncs; pytest opts into faster temporary IO.
os.environ.setdefault("TASKLEDGER_TEST_FAST_IO", "1")

import shutil  # noqa: E402
import weakref  # noqa: E402
from collections.abc import Mapping, Sequence  # noqa: E402
from typing import IO, Any  # noqa: E402

import click  # noqa: E402
import click.testing  # noqa: E402
import pytest  # noqa: E402
from typer import Typer  # noqa: E402
from typer.main import get_command as _typer_get_command  # noqa: E402
from typer.testing import CliRunner as _TyperCliRunner  # noqa: E402

from tests.support.builders import (  # noqa: E402
    create_approved_task,
    create_done_task,
    create_failed_validation_task,
    create_implemented_task,
    init_workspace,
)

# Typer rebuilds the full Click command tree on every CliRunner.invoke call.
# Taskledger's CLI is intentionally broad, so repeated rebuilds dominate the
# CLI-heavy test suite, especially on Windows. Cache the immutable Click command
# tree per Typer app for tests; each invocation still gets a fresh Click context.
_CLICK_COMMAND_CACHE: weakref.WeakKeyDictionary[Typer, Any] = (
    weakref.WeakKeyDictionary()
)


def _cached_click_command(app: Typer) -> Any:
    cached = _CLICK_COMMAND_CACHE.get(app)
    if cached is None:
        cached = _typer_get_command(app)
        _CLICK_COMMAND_CACHE[app] = cached
    return cached


def _invoke_with_cached_click_command(
    self: _TyperCliRunner,
    app: Typer,
    args: str | Sequence[str] | None = None,
    input: bytes | str | IO[Any] | None = None,
    env: Mapping[str, str | None] | None = None,
    catch_exceptions: bool = True,
    color: bool = False,
    **extra: Any,
) -> click.testing.Result:
    if not hasattr(self, "capture"):
        self.capture = "sys"
    return click.testing.CliRunner.invoke(
        self,  # type: ignore[arg-type]
        _cached_click_command(app),
        args=args,
        input=input,
        env=env,
        catch_exceptions=catch_exceptions,
        color=color,
        **extra,
    )


_TyperCliRunner.invoke = _invoke_with_cached_click_command  # type: ignore[assignment]


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
