from __future__ import annotations

from pathlib import Path

import tomllib

from taskledger.compat.ledgercore import LEDGERCORE_REQUIREMENT
from taskledger.ids import (
    allocate_ledger_task_id,
    next_project_id,
    normalize_local_resource_id,
    slugify_project_ref,
)


def test_ledgercore_requirement_matches_pyproject() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = pyproject["project"]["dependencies"]
    assert f"ledgercore{LEDGERCORE_REQUIREMENT}" in dependencies


def test_taskledger_uses_ledgercore_id_facade() -> None:
    assert next_project_id("todo", ["todo-0001"]) == "todo-0002"
    assert allocate_ledger_task_id(["task-0124"], 1) == ("task-0125", 126)
    assert allocate_ledger_task_id([], 128) == ("task-0128", 129)
    assert slugify_project_ref("My Project!") == "my-project"
    assert (
        normalize_local_resource_id(
            "tl:task-0001",
            kind="task",
            default_ledger="tl",
            allowed_ledgers={"tl"},
        )
        == "task-0001"
    )
    assert (
        normalize_local_resource_id(
            "TL-TASK-0001",
            kind="task",
            default_ledger="tl",
            allowed_ledgers={"tl"},
        )
        == "task-0001"
    )
