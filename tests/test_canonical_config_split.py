from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.init import init_canonical_project_state
from taskledger.storage.project_config import load_canonical_project_config


def test_canonical_config_is_version_three_without_topology_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    init_canonical_project_state(project, create_sibling_store=True)
    config = project / ".ledger" / "taskledger" / "config.toml"
    text = config.read_text(encoding="utf-8")
    assert "config_version = 3" in text
    assert "taskledger_dir" not in text
    assert "ledger_ref" not in text
    assert load_canonical_project_config(config)


def test_canonical_parser_rejects_legacy_state_fields(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'config_version = 3\nledger_ref = "main"\n'
        '[ledger]\ncode = "tl"\nname = "taskledger"\n',
        encoding="utf-8",
    )
    with pytest.raises(LaunchError, match="forbidden|legacy fields|Unsupported"):
        load_canonical_project_config(config)
