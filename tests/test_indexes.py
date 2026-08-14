from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.domain.sidecars import DependencyRequirement, RequirementCollection
from taskledger.domain.task import IntroductionRecord
from taskledger.storage.indexes import (
    rebuild_v2_indexes,
    remove_introduction_index_entry,
    update_dependency_index_entry,
    update_introduction_index_entry,
)
from taskledger.storage.task_store import (
    resolve_v2_paths,
    save_introduction,
    save_requirements,
)
from tests.support.builders import init_workspace


def _read(path: Path) -> list[dict[str, object]]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_incremental_index_updates_match_rebuild(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    paths = resolve_v2_paths(tmp_path)
    runner = CliRunner()
    for slug in ("required", "dependent"):
        result = runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                slug,
                "--description",
                "Index parity task.",
            ],
        )
        assert result.exit_code == 0, result.output
    rebuild_v2_indexes(paths)
    intro = IntroductionRecord(
        id="intro-0001",
        slug="release",
        title="Release",
        body="Release context",
    )

    save_introduction(tmp_path, intro)
    update_introduction_index_entry(paths, intro)
    update_dependency_index_entry(paths, "task-0001", ["task-0002"])
    save_requirements(
        tmp_path,
        RequirementCollection(
            task_id="task-0001",
            requirements=(DependencyRequirement(task_id="task-0002"),),
        ),
    )

    incremental = {
        "introductions": _read(paths.introductions_index_path),
        "dependencies": _read(paths.dependencies_index_path),
    }
    rebuild_v2_indexes(paths)
    rebuilt = {
        "introductions": _read(paths.introductions_index_path),
        "dependencies": _read(paths.dependencies_index_path),
    }
    assert incremental == rebuilt

    remove_introduction_index_entry(paths, intro.id)
    assert _read(paths.introductions_index_path) == []
