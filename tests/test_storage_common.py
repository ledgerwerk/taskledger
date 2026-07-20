"""Tests for taskledger.storage.common."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.common import (
    content_hash,
    load_json_array,
    load_json_object,
    merge_text,
    read_text,
    relative_to_project,
    relative_to_workspace,
    summarize_text,
    write_json,
    write_text,
)
from taskledger.storage.paths import ProjectPaths


def _paths(tmp_path: Path) -> ProjectPaths:
    project_dir = tmp_path / ".taskledger"
    return ProjectPaths(
        workspace_root=tmp_path,
        project_dir=project_dir,
        taskledger_dir=project_dir,
        config_path=project_dir / "project.toml",
        releases_dir=project_dir / "releases",
        repos_dir=project_dir / "repos",
        repo_index_path=project_dir / "repos" / "index.json",
    )


# -- load_json_array --


def test_load_json_array_missing_file(tmp_path: Path) -> None:
    result = load_json_array(tmp_path / "missing.json", "test")
    assert result == []


def test_load_json_array_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.json"
    p.write_text("")
    result = load_json_array(p, "test")
    assert result == []


def test_load_json_array_valid(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text('[{"a": 1}, {"b": 2}]')
    result = load_json_array(p, "test")
    assert result == [{"a": 1}, {"b": 2}]


def test_load_json_array_filters_non_dicts(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text('[{"a": 1}, 42, "x", null, {"b": 2}]')
    result = load_json_array(p, "test")
    assert result == [{"a": 1}, {"b": 2}]


def test_load_json_array_rejects_non_array(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text('{"a": 1}')
    with pytest.raises(LaunchError, match="expected a JSON array"):
        load_json_array(p, "test")


def test_load_json_array_rejects_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text("not json")
    with pytest.raises(LaunchError, match="Invalid"):
        load_json_array(p, "test")


# -- load_json_object --


def test_load_json_object_valid(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text('{"key": "value"}')
    result = load_json_object(p, "test")
    assert result == {"key": "value"}


def test_load_json_object_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text("")
    result = load_json_object(p, "test")
    assert result == {}


def test_load_json_object_rejects_array(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text("[1, 2]")
    with pytest.raises(LaunchError, match="expected a JSON object"):
        load_json_object(p, "test")


def test_load_json_object_rejects_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text("{bad json")
    with pytest.raises(LaunchError, match="Invalid"):
        load_json_object(p, "test")


# -- write_json / write_text / read_text --


def test_write_json_creates_file(tmp_path: Path) -> None:
    p = tmp_path / "sub" / "out.json"
    write_json(p, {"x": 1})
    data = json.loads(p.read_text())
    assert data == {"x": 1}


# specmason: req=REQ-0052 ac=AC-0556
def test_write_text_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "a" / "b" / "c" / "file.txt"
    write_text(p, "hello")
    assert p.read_text() == "hello"


# specmason: req=REQ-0052 ac=AC-0556
def test_read_text_reads_utf8(tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("café", encoding="utf-8")
    assert read_text(p) == "café"


# specmason: req=REQ-0052 ac=AC-0555
def test_read_text_raises_on_missing(tmp_path: Path) -> None:
    with pytest.raises(LaunchError, match="Failed to read"):
        read_text(tmp_path / "nope.txt")


# specmason: req=REQ-0052 ac=AC-0555
def test_write_text_raises_on_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "readonly" / "f.txt"

    def _raise_oserror(*_args: object, **_kwargs: object) -> int:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(Path, "write_bytes", _raise_oserror)

    with pytest.raises(LaunchError, match="Failed to write"):
        write_text(p, "new")


# -- relative_to_project / relative_to_workspace --


def test_relative_to_project(tmp_path: Path) -> None:
    ps = _paths(tmp_path)
    target = ps.project_dir / "tasks" / "task-0001.md"
    assert relative_to_project(ps, target) == "tasks/task-0001.md"


def test_relative_to_workspace(tmp_path: Path) -> None:
    ps = _paths(tmp_path)
    target = tmp_path / "src" / "main.py"
    assert relative_to_workspace(ps, target) == "src/main.py"


def test_relative_to_workspace_outside_root(tmp_path: Path) -> None:
    ps = _paths(tmp_path)
    outside = Path("/some/other/path")
    assert relative_to_workspace(ps, outside) == outside.as_posix()


# -- summarize_text --


# specmason: req=REQ-0052 ac=AC-0557
def test_summarize_text_short() -> None:
    assert summarize_text("hello") == "hello"


# specmason: req=REQ-0052 ac=AC-0557
def test_summarize_text_collapse_whitespace() -> None:
    assert summarize_text("  hello   world  ") == "hello world"


# specmason: req=REQ-0052 ac=AC-0557
def test_summarize_text_empty() -> None:
    assert summarize_text("") is None
    assert summarize_text("   ") is None


# specmason: req=REQ-0052 ac=AC-0557
def test_summarize_text_long() -> None:
    text = "x" * 90
    result = summarize_text(text)
    assert result is not None
    assert result.endswith("...")
    assert len(result) == 80


# specmason: req=REQ-0052 ac=AC-0557
def test_summarize_text_exactly_80() -> None:
    text = "x" * 80
    assert summarize_text(text) == text


# -- content_hash --


# specmason: req=REQ-0052 ac=AC-0554
def test_content_hash_returns_sha256() -> None:
    h = content_hash("test")
    assert h is not None
    assert len(h) == 64


# specmason: req=REQ-0052 ac=AC-0554
def test_content_hash_empty_returns_none() -> None:
    assert content_hash("") is None


# -- merge_text --


# specmason: req=REQ-0052 ac=AC-0555
def test_merge_text_append() -> None:
    result = merge_text("current", "incoming", prepend=False)
    assert result == "current\n\nincoming"


# specmason: req=REQ-0052 ac=AC-0556
def test_merge_text_prepend() -> None:
    result = merge_text("current", "incoming", prepend=True)
    assert result == "incoming\n\ncurrent"


# specmason: req=REQ-0052 ac=AC-0556
def test_merge_text_empty_current() -> None:
    assert merge_text("", "incoming", prepend=False) == "incoming"


# specmason: req=REQ-0052 ac=AC-0556
def test_merge_text_empty_incoming() -> None:
    assert merge_text("current", "", prepend=False) == "current"
