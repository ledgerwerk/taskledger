from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.domain.sidecars import FileLink
from taskledger.services.tasks import create_task
from taskledger.storage.task_store import load_links
from tests.support.builders import init_workspace


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def test_existing_links_load_without_baseline_fields() -> None:
    link = FileLink.from_dict(
        {
            "schema_version": 1,
            "object_type": "link",
            "file_version": "v2",
            "path": "src/foo.py",
            "kind": "code",
            "task_id": "task-0001",
        }
    )
    assert link.baseline_hash is None
    assert link.baseline_size is None
    assert link.baseline_mtime is None
    assert link.baseline_exists is None


def test_new_links_record_baseline_fields(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(ws, title="Link task", slug="link-task", description="x")
    source = ws / "src" / "foo.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("print('hi')\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["--cwd", str(ws), "file", "link", task.id, "src/foo.py", "--kind", "code"],
    )
    assert result.exit_code == 0, result.stdout

    link = load_links(ws, task.id).links[0]
    assert link.baseline_exists is True
    assert isinstance(link.baseline_hash, str) and link.baseline_hash.startswith(
        "sha256:"
    )
    assert link.baseline_size == len(b"print('hi')\n")
    assert link.target_type == "file"


def test_binary_files_hash_without_decoding_errors(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(ws, title="Binary task", slug="binary-task", description="x")
    blob = ws / "src" / "blob.bin"
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(b"\xff\xfe\x00\x01")

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(ws),
            "file",
            "link",
            task.id,
            "src/blob.bin",
            "--kind",
            "artifact",
        ],
    )
    assert result.exit_code == 0, result.stdout
    link = load_links(ws, task.id).links[0]
    assert isinstance(link.baseline_hash, str) and link.baseline_hash.startswith(
        "sha256:"
    )


def test_modified_file_status(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(ws, title="Modified task", slug="modified-task", description="x")
    path = ws / "src" / "foo.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("one\n", encoding="utf-8")
    runner.invoke(
        app, ["--cwd", str(ws), "file", "link", task.id, "src/foo.py", "--kind", "code"]
    )
    path.write_text("two\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["--cwd", str(ws), "--json", "file", "status", task.id],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["links"][0]["status"] == "modified"


def test_deleted_file_status(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(ws, title="Deleted task", slug="deleted-task", description="x")
    path = ws / "docs" / "old.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("old\n", encoding="utf-8")
    runner.invoke(
        app, ["--cwd", str(ws), "file", "link", task.id, "docs/old.md", "--kind", "doc"]
    )
    path.unlink()

    result = runner.invoke(app, ["--cwd", str(ws), "--json", "file", "status", task.id])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["links"][0]["status"] == "deleted"


def test_new_file_status_from_missing_baseline(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(ws, title="New file task", slug="new-file-task", description="x")
    runner.invoke(
        app, ["--cwd", str(ws), "file", "link", task.id, "src/new.py", "--kind", "code"]
    )
    new_file = ws / "src" / "new.py"
    new_file.parent.mkdir(parents=True, exist_ok=True)
    new_file.write_text("created\n", encoding="utf-8")

    result = runner.invoke(app, ["--cwd", str(ws), "--json", "file", "status", task.id])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["links"][0]["status"] == "new"


def test_directory_status_is_unchanged_without_recursive_hashing(
    tmp_path: Path,
) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(
        ws, title="Directory task", slug="directory-task", description="x"
    )
    target = ws / "src" / "pkg"
    target.mkdir(parents=True, exist_ok=True)
    (target / "__init__.py").write_text("", encoding="utf-8")
    runner.invoke(
        app, ["--cwd", str(ws), "file", "link", task.id, "src/pkg", "--kind", "dir"]
    )

    result = runner.invoke(app, ["--cwd", str(ws), "--json", "file", "status", task.id])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    link = payload["result"]["links"][0]
    assert link["current"]["target_type"] == "dir"
    assert link["current"]["hash"] is None
    assert link["status"] == "unchanged"


def test_refresh_rebaselines_modified_file(tmp_path: Path) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(ws, title="Refresh task", slug="refresh-task", description="x")
    path = ws / "src" / "foo.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("one\n", encoding="utf-8")
    runner.invoke(
        app, ["--cwd", str(ws), "file", "link", task.id, "src/foo.py", "--kind", "code"]
    )
    path.write_text("two\n", encoding="utf-8")

    before = runner.invoke(app, ["--cwd", str(ws), "--json", "file", "status", task.id])
    assert json.loads(before.stdout)["result"]["links"][0]["status"] == "modified"

    refreshed = runner.invoke(
        app,
        [
            "--cwd",
            str(ws),
            "file",
            "refresh",
            task.id,
            "src/foo.py",
            "--reason",
            "Rebaseline after change",
        ],
    )
    assert refreshed.exit_code == 0, refreshed.stdout

    after = runner.invoke(app, ["--cwd", str(ws), "--json", "file", "status", task.id])
    assert json.loads(after.stdout)["result"]["links"][0]["status"] == "unchanged"


def test_existing_link_baseline_is_preserved_without_explicit_snapshot(
    tmp_path: Path,
) -> None:
    ws = init_workspace(tmp_path)
    task = create_task(ws, title="Preserve task", slug="preserve-task", description="x")
    path = ws / "src" / "foo.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("one\n", encoding="utf-8")
    runner.invoke(
        app, ["--cwd", str(ws), "file", "link", task.id, "src/foo.py", "--kind", "code"]
    )
    path.write_text("two\n", encoding="utf-8")

    preserve = runner.invoke(
        app,
        ["--cwd", str(ws), "file", "link", task.id, "src/foo.py", "--kind", "test"],
    )
    assert preserve.exit_code == 0, preserve.stdout
    preserved_status = runner.invoke(
        app, ["--cwd", str(ws), "--json", "file", "status", task.id]
    )
    assert (
        json.loads(preserved_status.stdout)["result"]["links"][0]["status"]
        == "modified"
    )

    refresh = runner.invoke(
        app,
        [
            "--cwd",
            str(ws),
            "file",
            "link",
            task.id,
            "src/foo.py",
            "--kind",
            "test",
            "--snapshot",
        ],
    )
    assert refresh.exit_code == 0, refresh.stdout
    refreshed_status = runner.invoke(
        app, ["--cwd", str(ws), "--json", "file", "status", task.id]
    )
    assert (
        json.loads(refreshed_status.stdout)["result"]["links"][0]["status"]
        == "unchanged"
    )
