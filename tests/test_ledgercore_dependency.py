from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

from taskledger.compat.ledgercore import LEDGERCORE_REQUIREMENT
from taskledger.ids import next_project_id, slugify_project_ref


def test_ledgercore_requirement_matches_pyproject() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = pyproject["project"]["dependencies"]
    assert f"ledgercore{LEDGERCORE_REQUIREMENT}" in dependencies


def test_taskledger_uses_ledgercore_id_facade() -> None:
    assert next_project_id("todo", ["todo-0001"]) == "todo-0002"
    assert slugify_project_ref("My Project!") == "my-project"
