from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.refs import (
    file_ref_for_local_id,
    global_ref_for_local_id,
    local_id_from_ref,
)
from tests.support.builders import init_workspace


def _init_project(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return tmp_path


def test_default_task_global_ref(tmp_path: Path) -> None:
    workspace = _init_project(tmp_path)
    assert global_ref_for_local_id(workspace, "task-0001") == "tl:task-0001"


def test_file_ref_for_task(tmp_path: Path) -> None:
    workspace = _init_project(tmp_path)
    assert file_ref_for_local_id(workspace, "task-0001") == "tl-task-0001"


def test_parse_canonical_task_ref_to_local(tmp_path: Path) -> None:
    workspace = _init_project(tmp_path)
    assert local_id_from_ref(workspace, "tl:task-0001", kind="task") == "task-0001"


def test_parse_file_safe_alias_to_local(tmp_path: Path) -> None:
    workspace = _init_project(tmp_path)
    assert local_id_from_ref(workspace, "TL-TASK-0001", kind="task") == "task-0001"


def test_custom_ledger_code_derives_refs(tmp_path: Path) -> None:
    workspace = _init_project(tmp_path)
    config_path = workspace / ".ledger" / "taskledger" / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "[ledger]\ncode = 'tl'\nname = 'taskledger'\n",
            "[ledger]\ncode = 'xx'\nname = 'taskledger'\n",
        ),
        encoding="utf-8",
    )
    assert global_ref_for_local_id(workspace, "task-0001") == "xx:task-0001"


def test_wrong_ledger_is_rejected(tmp_path: Path) -> None:
    workspace = _init_project(tmp_path)
    with pytest.raises(LaunchError):
        local_id_from_ref(workspace, "al:adr-0002", kind="task")


def test_wrong_kind_is_rejected(tmp_path: Path) -> None:
    workspace = _init_project(tmp_path)
    with pytest.raises(LaunchError):
        local_id_from_ref(workspace, "tl:todo-0001", kind="task")
