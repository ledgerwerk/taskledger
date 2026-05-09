from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any, cast

import pytest
from click.testing import Result
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.errors import LaunchError
from taskledger.exchange import (
    ARCHIVE_KIND,
    ARCHIVE_VERSION,
    MANIFEST_MEMBER,
    MAX_ARCHIVE_MEMBERS,
    MAX_ARTIFACT_MEMBER_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_PAYLOAD_BYTES,
    PAYLOAD_MEMBER,
    read_project_archive,
)
from taskledger.storage.agent_logs import load_agent_command_logs


def _make_runner() -> CliRunner:
    return CliRunner()


runner = _make_runner()


def _init_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--cwd", str(tmp_path), "init"])
    assert result.exit_code == 0


def _copy_project_uuid(src_root: Path, dst_root: Path) -> None:
    """Make dst_root project use the same project_uuid as src_root."""
    from shutil import copy2

    copy2(src_root / "taskledger.toml", dst_root / "taskledger.toml")


def _set_ledger_next_task_number(root: Path, value: int) -> None:
    config_path = root / "taskledger.toml"
    text = config_path.read_text(encoding="utf-8")
    updated = text.replace(
        "ledger_next_task_number = 1",
        f"ledger_next_task_number = {value}",
    )
    config_path.write_text(updated, encoding="utf-8")


def _json(result: Result) -> dict[str, Any]:
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    payload_dict = cast(dict[str, Any], payload)
    assert payload_dict.get("ok") is True
    return payload_dict


def _valid_archive_bytes(*, extra_members: int = 0) -> bytes:
    project_uuid = "11111111-1111-1111-1111-111111111111"
    payload_dict = {
        "version": 3,
        "project_uuid": project_uuid,
        "ledgers": [],
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()
    manifest_dict = {
        "kind": ARCHIVE_KIND,
        "archive_version": ARCHIVE_VERSION,
        "project": {"uuid": project_uuid},
        "payload": {"sha256": payload_sha},
    }
    manifest_bytes = json.dumps(manifest_dict).encode("utf-8")

    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        manifest_info = tarfile.TarInfo(MANIFEST_MEMBER)
        manifest_info.size = len(manifest_bytes)
        tar.addfile(manifest_info, io.BytesIO(manifest_bytes))

        payload_info = tarfile.TarInfo(PAYLOAD_MEMBER)
        payload_info.size = len(payload_bytes)
        tar.addfile(payload_info, io.BytesIO(payload_bytes))

        for index in range(extra_members):
            data = b"x"
            info = tarfile.TarInfo(f"extra/{index}.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    return out.getvalue()


def _archive_with_member_sizes(*, manifest_size: int, payload_size: int) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        manifest_data = b"x" * manifest_size
        manifest_info = tarfile.TarInfo(MANIFEST_MEMBER)
        manifest_info.size = len(manifest_data)
        tar.addfile(manifest_info, io.BytesIO(manifest_data))

        payload_data = b"x" * payload_size
        payload_info = tarfile.TarInfo(PAYLOAD_MEMBER)
        payload_info.size = len(payload_data)
        tar.addfile(payload_info, io.BytesIO(payload_data))

    return out.getvalue()


def _write_archive(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def _read_manifest_payload(path: Path) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    with tarfile.open(path, "r:gz") as tar:
        manifest_bytes = tar.extractfile(MANIFEST_MEMBER).read()  # type: ignore[union-attr]
        payload_bytes = tar.extractfile(PAYLOAD_MEMBER).read()  # type: ignore[union-attr]
    manifest = cast(dict[str, Any], json.loads(manifest_bytes.decode("utf-8")))
    payload = cast(dict[str, Any], json.loads(payload_bytes.decode("utf-8")))
    return manifest, payload, payload_bytes


def _archive_with_extra_member(*, member_name: str, member_size: int) -> bytes:
    project_uuid = "11111111-1111-1111-1111-111111111111"
    payload_dict = {
        "version": 3,
        "project_uuid": project_uuid,
        "v2": {"tasks": []},
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()
    manifest_dict = {
        "kind": ARCHIVE_KIND,
        "archive_version": ARCHIVE_VERSION,
        "project": {"uuid": project_uuid},
        "payload": {"sha256": payload_sha},
    }
    manifest_bytes = json.dumps(manifest_dict).encode("utf-8")
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        manifest_info = tarfile.TarInfo(MANIFEST_MEMBER)
        manifest_info.size = len(manifest_bytes)
        tar.addfile(manifest_info, io.BytesIO(manifest_bytes))

        payload_info = tarfile.TarInfo(PAYLOAD_MEMBER)
        payload_info.size = len(payload_bytes)
        tar.addfile(payload_info, io.BytesIO(payload_bytes))

        extra_data = b"x" * member_size
        extra_info = tarfile.TarInfo(member_name)
        extra_info.size = len(extra_data)
        tar.addfile(extra_info, io.BytesIO(extra_data))
    return out.getvalue()


def _task_lock_paths(project_root: Path, task_id: str) -> list[Path]:
    return sorted(
        (project_root / ".taskledger" / "ledgers").glob(f"*/tasks/{task_id}/lock.yaml")
    )


def _prepare_active_implementation(project_root: Path, *, slug: str) -> None:
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(project_root),
                "task",
                "create",
                slug,
                "--description",
                "Prepare an active implementation for archive transfer tests.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(project_root), "task", "activate", slug]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["--cwd", str(project_root), "plan", "start"]).exit_code == 0
    )
    plan_text = """---
goal: Test cross-machine import behavior.
acceptance_criteria:
  - id: ac-0001
    text: Import state can be resumed.
    mandatory: true
todos:
  - id: todo-0001
    text: Keep implementation running.
    mandatory: true
    validation_hint: taskledger next-action
---

# Plan

Keep implementation open for export/import testing.
"""
    assert (
        runner.invoke(
            app,
            ["--cwd", str(project_root), "plan", "propose", "--text", plan_text],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(project_root),
                "plan",
                "approve",
                "--version",
                "1",
                "--actor",
                "user",
                "--note",
                "Approved for exchange import tests.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["--cwd", str(project_root), "implement", "start"]).exit_code
        == 0
    )


def test_export_and_import_include_v2_state(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)

    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "migrate-v2",
                "--description",
                "Migrate taskledger to v2.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(source_root), "plan", "start", "--task", "migrate-v2"],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "plan",
                "propose",
                "--task",
                "migrate-v2",
                "--text",
                "## Goal\n\nShip export support.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "handoff",
                "create",
                "--task",
                "migrate-v2",
                "--mode",
                "implementation",
                "--summary",
                "Continue elsewhere.",
            ],
        ).exit_code
        == 0
    )

    # Export archive to file
    archive_path = tmp_path / "export.tar.gz"
    export_result = runner.invoke(
        app,
        ["--cwd", str(source_root), "export", str(archive_path)],
    )
    assert export_result.exit_code == 0
    assert archive_path.exists()

    # JSON export returns metadata, not full payload
    json_result = runner.invoke(
        app,
        ["--cwd", str(source_root), "--json", "export", "--overwrite"],
    )
    json_payload = _json(json_result)
    assert "project_uuid" in json_payload["result"]
    assert "v2" not in json_payload["result"]  # metadata only

    # Import into dest
    import_result = runner.invoke(
        app,
        ["--cwd", str(dest_root), "import", str(archive_path)],
    )
    assert import_result.exit_code == 0

    show_result = runner.invoke(
        app,
        ["--cwd", str(dest_root), "--json", "task", "show", "--task", "migrate-v2"],
    )
    task_payload = _json(show_result)
    assert task_payload["result"]["task"]["latest_plan_version"] == 1
    handoffs = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(dest_root),
                "--json",
                "handoff",
                "list",
                "--task",
                "migrate-v2",
            ],
        )
    )
    assert handoffs["result"]["handoffs"][0]["mode"] == "implementation"


def test_default_export_filename_includes_project_slug_and_ledger(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "source"
    workspace.mkdir()
    init_result = runner.invoke(
        app,
        ["--cwd", str(workspace), "init", "--project-name", "Taskledger"],
    )
    assert init_result.exit_code == 0, init_result.output

    export_result = _json(
        runner.invoke(app, ["--cwd", str(workspace), "--json", "export", "--overwrite"])
    )
    result = cast(dict[str, Any], export_result["result"])
    filename = Path(cast(str, result["path"])).name
    assert filename.startswith("taskledger-export-taskledger-main-")
    assert filename.endswith(".tar.gz")
    assert result["filename_policy"] == "project-ledger-timestamp-v1"
    assert result["project_slug"] == "taskledger"


def test_default_export_filename_sanitizes_project_name(tmp_path: Path) -> None:
    workspace = tmp_path / "source"
    workspace.mkdir()
    init_result = runner.invoke(
        app,
        ["--cwd", str(workspace), "init", "--project-name", "Odoo 17 Addons!"],
    )
    assert init_result.exit_code == 0, init_result.output

    export_result = _json(
        runner.invoke(app, ["--cwd", str(workspace), "--json", "export", "--overwrite"])
    )
    filename = Path(cast(str, export_result["result"]["path"])).name
    assert filename.startswith("taskledger-export-odoo-17-addons-main-")


def test_explicit_export_path_is_not_rewritten(tmp_path: Path) -> None:
    workspace = tmp_path / "source"
    workspace.mkdir()
    _init_project(workspace)

    archive_path = tmp_path / "custom.tar.gz"
    export_result = _json(
        runner.invoke(
            app,
            ["--cwd", str(workspace), "--json", "export", str(archive_path)],
        )
    )
    assert export_result["result"]["path"] == str(archive_path)


def test_export_positional_task_ref_exports_task_archive(tmp_path: Path) -> None:
    workspace = tmp_path / "source"
    workspace.mkdir()
    _init_project(workspace)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
                "task",
                "create",
                "task-a",
                "--description",
                "First task.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
                "task",
                "create",
                "task-b",
                "--description",
                "Second task.",
            ],
        ).exit_code
        == 0
    )
    export_result = _json(
        runner.invoke(app, ["--cwd", str(workspace), "--json", "export", "task-0001"])
    )
    payload = cast(dict[str, Any], export_result["result"])
    assert payload["archive_scope"] == "tasks"
    assert payload["selected_task_ids"] == ["task-0001"]
    assert payload["counts"]["tasks"] == 1
    archive_path = Path(cast(str, payload["path"]))
    assert archive_path.name.startswith("taskledger-task-")
    manifest, raw_payload, _ = _read_manifest_payload(archive_path)
    assert cast(dict[str, Any], manifest["scope"])["kind"] == "tasks"
    assert cast(dict[str, Any], raw_payload["v2"])["active_task"] is None


def test_export_positional_tar_gz_still_means_output_path(tmp_path: Path) -> None:
    workspace = tmp_path / "source"
    workspace.mkdir()
    _init_project(workspace)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
                "task",
                "create",
                "task-a",
                "--description",
                "First task.",
            ],
        ).exit_code
        == 0
    )
    archive_path = tmp_path / "backup.tar.gz"
    export_result = _json(
        runner.invoke(
            app,
            ["--cwd", str(workspace), "--json", "export", str(archive_path)],
        )
    )
    payload = cast(dict[str, Any], export_result["result"])
    assert payload["path"] == str(archive_path)
    assert payload["archive_scope"] == "ledger"


def test_archive_manifest_includes_project_name_slug_and_uuid(tmp_path: Path) -> None:
    workspace = tmp_path / "source"
    workspace.mkdir()
    init_result = runner.invoke(
        app,
        ["--cwd", str(workspace), "init", "--project-name", "Taskledger"],
    )
    assert init_result.exit_code == 0, init_result.output
    archive_path = tmp_path / "manifest-check.tar.gz"
    export_result = runner.invoke(
        app,
        ["--cwd", str(workspace), "export", str(archive_path)],
    )
    assert export_result.exit_code == 0, export_result.output

    manifest, payload, _ = _read_manifest_payload(archive_path)
    project = cast(dict[str, Any], manifest["project"])
    assert project["uuid"] == payload["project_uuid"]
    assert project["name"] == "Taskledger"
    assert project["slug"] == "taskledger"
    assert project["ledger_ref"] == "main"


def test_archive_import_dry_run_reports_project_name(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    assert (
        runner.invoke(
            app,
            ["--cwd", str(source_root), "init", "--project-name", "Taskledger"],
        ).exit_code
        == 0
    )
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)
    archive_path = tmp_path / "dry-run-name.tar.gz"
    export_result = runner.invoke(
        app,
        ["--cwd", str(source_root), "export", str(archive_path)],
    )
    assert export_result.exit_code == 0, export_result.output

    import_result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(dest_root),
                "--json",
                "import",
                str(archive_path),
                "--dry-run",
            ],
        )
    )
    result = cast(dict[str, Any], import_result["result"])
    assert result["dry_run"] is True
    assert result["project_name"] == "Taskledger"
    assert result["project_slug"] == "taskledger"
    assert result["next_command"] == "taskledger next-action"


def test_export_import_preserves_agent_command_logs(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)

    source_config = source_root / "taskledger.toml"
    source_config.write_text(
        source_config.read_text(encoding="utf-8")
        + "\n[agent_logging]\nenabled = true\n",
        encoding="utf-8",
    )

    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "log-export-task",
                "--description",
                "Create transcript log entry before export.",
            ],
        ).exit_code
        == 0
    )
    source_logs = load_agent_command_logs(source_root)
    assert source_logs

    archive_path = tmp_path / "agent-logs-export.tar.gz"
    export_result = runner.invoke(
        app,
        ["--cwd", str(source_root), "export", str(archive_path)],
    )
    assert export_result.exit_code == 0, export_result.stdout

    import_result = runner.invoke(
        app,
        ["--cwd", str(dest_root), "import", str(archive_path)],
    )
    assert import_result.exit_code == 0, import_result.stdout

    dest_logs = load_agent_command_logs(dest_root)
    assert dest_logs
    assert any(item.command_kind == "taskledger_cli" for item in dest_logs)


def test_export_and_import_include_release_records(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)

    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "release-boundary",
                "--description",
                "Create a release boundary task.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(source_root), "task", "activate", "release-boundary"]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["--cwd", str(source_root), "plan", "start"]).exit_code == 0
    )
    plan_text = """---
goal: Finish a release boundary task.
acceptance_criteria:
  - id: ac-0001
    text: Release boundary task is done.
todos:
  - id: todo-0001
    text: Finish the boundary task.
    validation_hint: python -c "print('ok')"
---

# Plan

Finish the boundary task.
"""
    assert (
        runner.invoke(
            app,
            ["--cwd", str(source_root), "plan", "propose", "--text", plan_text],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "plan",
                "approve",
                "--version",
                "1",
                "--actor",
                "user",
                "--note",
                "Approved.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(source_root), "implement", "start"],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "implement",
                "change",
                "--path",
                "taskledger/exchange.py",
                "--kind",
                "edit",
                "--summary",
                "Prepared exchange release coverage.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "todo",
                "done",
                "todo-0001",
                "--evidence",
                "python -c print('ok')",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "implement",
                "finish",
                "--summary",
                "Implemented release boundary.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(source_root), "validate", "start"],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "validate",
                "check",
                "--criterion",
                "ac-0001",
                "--status",
                "pass",
                "--evidence",
                "python -c print('ok')",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "validate",
                "finish",
                "--result",
                "passed",
                "--summary",
                "Validated release boundary.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "release",
                "tag",
                "0.4.1",
                "--at-task",
                "release-boundary",
                "--note",
                "0.4.1 released",
            ],
        ).exit_code
        == 0
    )

    # Export archive
    archive_path = tmp_path / "release-export.tar.gz"
    export_result = runner.invoke(
        app,
        ["--cwd", str(source_root), "export", str(archive_path)],
    )
    assert export_result.exit_code == 0

    # Import into dest
    import_result = runner.invoke(
        app,
        ["--cwd", str(dest_root), "import", str(archive_path)],
    )
    assert import_result.exit_code == 0

    show_result = runner.invoke(
        app,
        ["--cwd", str(dest_root), "--json", "release", "show", "0.4.1"],
    )
    payload = _json(show_result)
    assert payload["result"]["release"]["boundary_task_id"] == "task-0001"


def test_import_replace_quarantines_lock_and_allows_resume(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)
    _prepare_active_implementation(source_root, slug="portable-import")

    archive_path = tmp_path / "portable-import.tar.gz"
    export_result = runner.invoke(
        app,
        ["--cwd", str(source_root), "export", str(archive_path)],
    )
    assert export_result.exit_code == 0, export_result.stdout

    import_result = runner.invoke(
        app,
        ["--cwd", str(dest_root), "import", str(archive_path), "--replace"],
    )
    assert import_result.exit_code == 0, import_result.stdout

    assert not _task_lock_paths(dest_root, "task-0001")
    imported_lock_audits = sorted(
        (dest_root / ".taskledger" / "ledgers").glob(
            "*/tasks/task-0001/audit/imported-lock-*.yaml"
        )
    )
    assert imported_lock_audits

    next_action_payload = _json(
        runner.invoke(app, ["--cwd", str(dest_root), "--json", "next-action"])
    )
    assert next_action_payload["result"]["action"] == "implement-resume"


def test_import_replace_lock_policy_keep_restores_lock(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)
    _prepare_active_implementation(source_root, slug="keep-lock-import")

    archive_path = tmp_path / "keep-lock-import.tar.gz"
    export_result = runner.invoke(
        app,
        ["--cwd", str(source_root), "export", str(archive_path)],
    )
    assert export_result.exit_code == 0, export_result.stdout

    import_result = runner.invoke(
        app,
        [
            "--cwd",
            str(dest_root),
            "import",
            str(archive_path),
            "--replace",
            "--lock-policy",
            "keep",
        ],
    )
    assert import_result.exit_code == 0, import_result.stdout
    assert _task_lock_paths(dest_root, "task-0001")


def test_import_archive_rejects_different_project_uuid_without_mutation(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)

    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "source-task",
                "--description",
                "Source state.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(dest_root),
                "task",
                "create",
                "dest-task",
                "--description",
                "Destination state.",
            ],
        ).exit_code
        == 0
    )

    archive_path = tmp_path / "mismatch.tar.gz"
    export_result = runner.invoke(
        app,
        ["--cwd", str(source_root), "export", str(archive_path)],
    )
    assert export_result.exit_code == 0, export_result.stdout

    import_result = runner.invoke(
        app,
        ["--cwd", str(dest_root), "import", str(archive_path), "--replace"],
    )
    assert import_result.exit_code != 0
    assert "Project UUID mismatch" in import_result.output

    dest_task_result = runner.invoke(
        app,
        ["--cwd", str(dest_root), "task", "show", "--task", "dest-task"],
    )
    assert dest_task_result.exit_code == 0, dest_task_result.stdout


def test_import_single_task_preserves_id_when_free(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "source-task",
                "--description",
                "Source state.",
            ],
        ).exit_code
        == 0
    )
    export_payload = _json(
        runner.invoke(
            app,
            ["--cwd", str(source_root), "--json", "export", "task-0001", "--overwrite"],
        )
    )
    archive_path = Path(cast(str, export_payload["result"]["path"]))
    import_payload = _json(
        runner.invoke(
            app, ["--cwd", str(dest_root), "--json", "import", str(archive_path)]
        )
    )
    result = cast(dict[str, Any], import_payload["result"])
    assert result["archive_scope"] == "tasks"
    assert result["task_id_map"] == {"task-0001": "task-0001"}
    assert result["imported_task_ids"] == ["task-0001"]
    show = runner.invoke(
        app,
        ["--cwd", str(dest_root), "--json", "task", "show", "--task", "task-0001"],
    )
    assert show.exit_code == 0, show.stdout


def test_import_single_task_renumbers_on_conflict_without_overwrite(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "source-task",
                "--description",
                "Source state.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(dest_root),
                "task",
                "create",
                "dest-task",
                "--description",
                "Destination state.",
            ],
        ).exit_code
        == 0
    )
    export_payload = _json(
        runner.invoke(
            app,
            ["--cwd", str(source_root), "--json", "export", "task-0001", "--overwrite"],
        )
    )
    archive_path = Path(cast(str, export_payload["result"]["path"]))
    import_payload = _json(
        runner.invoke(
            app, ["--cwd", str(dest_root), "--json", "import", str(archive_path)]
        )
    )
    result = cast(dict[str, Any], import_payload["result"])
    assert result["task_id_map"] == {"task-0001": "task-0002"}
    assert result["renumbered"] == ["task-0001"]
    dest_show = _json(
        runner.invoke(
            app,
            ["--cwd", str(dest_root), "--json", "task", "show", "--task", "task-0001"],
        )
    )
    imported_show = _json(
        runner.invoke(
            app,
            ["--cwd", str(dest_root), "--json", "task", "show", "--task", "task-0002"],
        )
    )
    assert dest_show["result"]["task"]["slug"] == "dest-task"
    assert imported_show["result"]["task"]["slug"] == "source-task"


def test_import_single_task_dry_run_reports_id_map_without_mutation(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "source-task",
                "--description",
                "Source state.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(dest_root),
                "task",
                "create",
                "dest-task",
                "--description",
                "Destination state.",
            ],
        ).exit_code
        == 0
    )
    export_payload = _json(
        runner.invoke(
            app,
            ["--cwd", str(source_root), "--json", "export", "task-0001", "--overwrite"],
        )
    )
    archive_path = Path(cast(str, export_payload["result"]["path"]))
    dry_run_payload = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(dest_root),
                "--json",
                "import",
                str(archive_path),
                "--dry-run",
            ],
        )
    )
    result = cast(dict[str, Any], dry_run_payload["result"])
    assert result["dry_run"] is True
    assert result["task_id_map"] == {"task-0001": "task-0002"}
    tasks = _json(
        runner.invoke(app, ["--cwd", str(dest_root), "--json", "task", "list"])
    )
    assert len(cast(list[dict[str, Any]], tasks["result"]["tasks"])) == 1


def test_import_single_task_id_policy_fail_on_conflict(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "source-task",
                "--description",
                "Source state.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(dest_root),
                "task",
                "create",
                "dest-task",
                "--description",
                "Destination state.",
            ],
        ).exit_code
        == 0
    )
    export_payload = _json(
        runner.invoke(
            app,
            ["--cwd", str(source_root), "--json", "export", "task-0001", "--overwrite"],
        )
    )
    archive_path = Path(cast(str, export_payload["result"]["path"]))
    import_result = runner.invoke(
        app,
        [
            "--cwd",
            str(dest_root),
            "import",
            str(archive_path),
            "--id-policy",
            "fail-on-conflict",
        ],
    )
    assert import_result.exit_code != 0
    tasks = _json(
        runner.invoke(app, ["--cwd", str(dest_root), "--json", "task", "list"])
    )
    assert len(cast(list[dict[str, Any]], tasks["result"]["tasks"])) == 1


def test_import_single_task_updates_ledger_next_task_number(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)
    _set_ledger_next_task_number(source_root, 87)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "source-high-id",
                "--description",
                "Source state.",
            ],
        ).exit_code
        == 0
    )
    export_payload = _json(
        runner.invoke(
            app,
            ["--cwd", str(source_root), "--json", "export", "task-0087", "--overwrite"],
        )
    )
    archive_path = Path(cast(str, export_payload["result"]["path"]))
    import_payload = _json(
        runner.invoke(
            app,
            ["--cwd", str(dest_root), "--json", "import", str(archive_path)],
        )
    )
    assert import_payload["result"]["ledger_next_task_number"] >= 88
    _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(dest_root),
                "--json",
                "task",
                "create",
                "after-import",
                "--description",
                "Counter repair check.",
            ],
        )
    )
    show = _json(
        runner.invoke(
            app,
            ["--cwd", str(dest_root), "--json", "task", "show", "after-import"],
        )
    )
    assert show["result"]["task"]["id"] == "task-0088"


def test_import_single_task_artifacts_follow_renumbered_task_id(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "source-task",
                "--description",
                "Source state.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(dest_root),
                "task",
                "create",
                "dest-task",
                "--description",
                "Destination state.",
            ],
        ).exit_code
        == 0
    )
    source_artifact = (
        source_root
        / ".taskledger"
        / "ledgers"
        / "main"
        / "tasks"
        / "task-0001"
        / "artifacts"
        / "run-0001"
        / "out.txt"
    )
    source_artifact.parent.mkdir(parents=True, exist_ok=True)
    source_artifact.write_text("artifact-output\n", encoding="utf-8")
    export_payload = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "--json",
                "export",
                "task-0001",
                "--include-run-artifacts",
                "--overwrite",
            ],
        )
    )
    archive_path = Path(cast(str, export_payload["result"]["path"]))
    _json(
        runner.invoke(
            app, ["--cwd", str(dest_root), "--json", "import", str(archive_path)]
        )
    )
    imported_artifact = (
        dest_root
        / ".taskledger"
        / "ledgers"
        / "main"
        / "tasks"
        / "task-0002"
        / "artifacts"
        / "run-0001"
        / "out.txt"
    )
    assert imported_artifact.read_text(encoding="utf-8") == "artifact-output\n"


def test_import_single_task_does_not_replace_active_task(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "source-task",
                "--description",
                "Source state.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(dest_root),
                "task",
                "create",
                "dest-task",
                "--description",
                "Destination state.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(dest_root), "task", "activate", "dest-task"]
        ).exit_code
        == 0
    )
    export_payload = _json(
        runner.invoke(
            app,
            ["--cwd", str(source_root), "--json", "export", "task-0001", "--overwrite"],
        )
    )
    archive_path = Path(cast(str, export_payload["result"]["path"]))
    _json(
        runner.invoke(
            app,
            ["--cwd", str(dest_root), "--json", "import", str(archive_path)],
        )
    )
    show = _json(
        runner.invoke(app, ["--cwd", str(dest_root), "--json", "task", "show"])
    )
    assert show["result"]["task"]["slug"] == "dest-task"


def test_read_project_archive_rejects_too_many_members(tmp_path: Path) -> None:
    archive_path = tmp_path / "too-many-members.tar.gz"
    data = _valid_archive_bytes(extra_members=MAX_ARCHIVE_MEMBERS - 1)
    _write_archive(archive_path, data)

    with pytest.raises(LaunchError, match="too many members"):
        read_project_archive(archive_path)


def test_read_project_archive_rejects_oversized_manifest(tmp_path: Path) -> None:
    archive_path = tmp_path / "oversized-manifest.tar.gz"
    data = _archive_with_member_sizes(
        manifest_size=MAX_MANIFEST_BYTES + 1,
        payload_size=128,
    )
    _write_archive(archive_path, data)

    with pytest.raises(LaunchError, match="manifest is too large"):
        read_project_archive(archive_path)


def test_read_project_archive_rejects_oversized_payload(tmp_path: Path) -> None:
    archive_path = tmp_path / "oversized-payload.tar.gz"
    data = _archive_with_member_sizes(
        manifest_size=128,
        payload_size=MAX_PAYLOAD_BYTES + 1,
    )
    _write_archive(archive_path, data)

    with pytest.raises(LaunchError, match="payload is too large"):
        read_project_archive(archive_path)


def test_export_import_preserves_archived_task_metadata_and_slug_reuse(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source-archive"
    dest_root = tmp_path / "dest-archive"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)

    record = runner.invoke(
        app,
        [
            "--cwd",
            str(source_root),
            "task",
            "record",
            "Legacy archive",
            "--slug",
            "legacy-archive",
            "--description",
            "Historical archived task",
            "--summary",
            "Completed",
            "--allow-empty-record",
            "--reason",
            "test",
        ],
    )
    assert record.exit_code == 0, record.output
    archive = runner.invoke(
        app,
        [
            "--cwd",
            str(source_root),
            "task",
            "archive",
            "legacy-archive",
            "--reason",
            "Hide old task",
        ],
    )
    assert archive.exit_code == 0, archive.output

    archive_path = tmp_path / "archive-metadata.tar.gz"
    export_result = runner.invoke(
        app,
        ["--cwd", str(source_root), "export", str(archive_path)],
    )
    assert export_result.exit_code == 0, export_result.output

    import_result = runner.invoke(
        app,
        ["--cwd", str(dest_root), "import", str(archive_path)],
    )
    assert import_result.exit_code == 0, import_result.output

    visible = runner.invoke(app, ["--cwd", str(dest_root), "task", "list"])
    assert visible.exit_code == 0, visible.output
    assert "legacy-archive" not in visible.output

    archived = runner.invoke(
        app,
        ["--cwd", str(dest_root), "task", "list", "--archived"],
    )
    assert archived.exit_code == 0, archived.output
    assert "legacy-archive" in archived.output

    create = runner.invoke(
        app,
        [
            "--cwd",
            str(dest_root),
            "--json",
            "task",
            "create",
            "New legacy archive",
            "--slug",
            "legacy-archive",
        ],
    )
    payload = _json(create)
    assert payload["result"]["slug"] == "legacy-archive"


def test_old_archive_without_project_name_still_imports(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)

    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "legacy-import-task",
                "--description",
                "legacy archive payload",
            ],
        ).exit_code
        == 0
    )
    archive_path = tmp_path / "legacy-no-project-name.tar.gz"
    export_result = runner.invoke(
        app,
        ["--cwd", str(source_root), "export", str(archive_path)],
    )
    assert export_result.exit_code == 0, export_result.output

    manifest, payload, _ = _read_manifest_payload(archive_path)
    project = cast(dict[str, Any], manifest["project"])
    project.pop("name", None)
    project.pop("slug", None)
    payload.pop("project_name", None)
    payload.pop("project_slug", None)
    rewritten_payload = (
        json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    cast(dict[str, Any], manifest["payload"])["sha256"] = hashlib.sha256(
        rewritten_payload
    ).hexdigest()
    rewritten_manifest = (
        json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )

    with tarfile.open(archive_path, "w:gz") as tar:
        manifest_info = tarfile.TarInfo(MANIFEST_MEMBER)
        manifest_info.size = len(rewritten_manifest)
        tar.addfile(manifest_info, io.BytesIO(rewritten_manifest))

        payload_info = tarfile.TarInfo(PAYLOAD_MEMBER)
        payload_info.size = len(rewritten_payload)
        tar.addfile(payload_info, io.BytesIO(rewritten_payload))

    import_result = runner.invoke(
        app,
        ["--cwd", str(dest_root), "import", str(archive_path)],
    )
    assert import_result.exit_code == 0, import_result.output


def test_json_import_dry_run_does_not_mutate_state(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "json-dry-run-source",
                "--description",
                "source state for dry run import",
            ],
        ).exit_code
        == 0
    )

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    snapshot_result = _json(
        runner.invoke(
            app,
            ["--cwd", str(source_root), "--json", "snapshot", str(snapshot_dir)],
        )
    )
    export_path = Path(cast(str, snapshot_result["result"]["export_path"]))

    dry_run_result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(dest_root),
                "--json",
                "import",
                str(export_path),
                "--dry-run",
            ],
        )
    )
    assert dry_run_result["result"]["dry_run"] is True
    assert dry_run_result["result"]["counts"]["tasks"] == 1

    list_result = _json(
        runner.invoke(app, ["--cwd", str(dest_root), "--json", "task", "list"])
    )
    assert list_result["result"]["tasks"] == []


def test_export_without_bodies_omits_plan_and_task_body(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _init_project(source_root)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "body-export",
                "--description",
                "Task body should be omitted when include-bodies is false.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(source_root), "task", "activate", "body-export"],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["--cwd", str(source_root), "plan", "start"]).exit_code == 0
    )
    plan_text = """---
goal: Verify body stripping.
acceptance_criteria:
  - id: ac-0001
    text: Bodies can be omitted.
todos:
  - id: todo-0001
    text: Export.
    validation_hint: taskledger export
---

# Plan body

This markdown body should be removed when include-bodies=false.
"""
    assert (
        runner.invoke(
            app,
            ["--cwd", str(source_root), "plan", "propose", "--text", plan_text],
        ).exit_code
        == 0
    )
    archive_path = tmp_path / "without-bodies.tar.gz"
    export_result = runner.invoke(
        app,
        [
            "--cwd",
            str(source_root),
            "export",
            str(archive_path),
            "--no-include-bodies",
        ],
    )
    assert export_result.exit_code == 0, export_result.output
    archive = read_project_archive(archive_path)
    payload = cast(dict[str, Any], archive["payload"])
    tasks = cast(list[dict[str, Any]], payload["v2"]["tasks"])
    plans = cast(list[dict[str, Any]], payload["v2"]["plans"])
    assert "body" not in tasks[0]
    assert "body" not in plans[0]


def test_export_with_run_artifacts_includes_artifact_members(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    dest_root = tmp_path / "dest"
    source_root.mkdir()
    dest_root.mkdir()
    _init_project(source_root)
    _init_project(dest_root)
    _copy_project_uuid(source_root, dest_root)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(source_root),
                "task",
                "create",
                "artifact-export",
                "--description",
                "Artifact export coverage.",
            ],
        ).exit_code
        == 0
    )
    artifact_path = (
        source_root
        / ".taskledger"
        / "ledgers"
        / "main"
        / "tasks"
        / "task-0001"
        / "artifacts"
        / "run.log"
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("artifact-output\n", encoding="utf-8")

    archive_path = tmp_path / "with-artifacts.tar.gz"
    export_result = runner.invoke(
        app,
        [
            "--cwd",
            str(source_root),
            "export",
            str(archive_path),
            "--include-run-artifacts",
        ],
    )
    assert export_result.exit_code == 0, export_result.output
    with tarfile.open(archive_path, "r:gz") as tar:
        names = {member.name for member in tar.getmembers()}
    assert "artifacts/tasks/task-0001/artifacts/run.log" in names

    import_result = runner.invoke(
        app,
        ["--cwd", str(dest_root), "import", str(archive_path), "--replace"],
    )
    assert import_result.exit_code == 0, import_result.output
    imported_artifact = (
        dest_root
        / ".taskledger"
        / "ledgers"
        / "main"
        / "tasks"
        / "task-0001"
        / "artifacts"
        / "run.log"
    )
    assert imported_artifact.read_text(encoding="utf-8") == "artifact-output\n"


def test_import_archive_rejects_unsafe_artifact_member_paths(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe-artifact.tar.gz"
    data = _archive_with_extra_member(
        member_name="artifacts/../../etc/passwd",
        member_size=8,
    )
    _write_archive(archive_path, data)

    with pytest.raises(LaunchError, match="Unsafe archive member path"):
        read_project_archive(archive_path)


def test_import_archive_rejects_oversized_artifact_payload(tmp_path: Path) -> None:
    archive_path = tmp_path / "oversized-artifact.tar.gz"
    data = _archive_with_extra_member(
        member_name="artifacts/tasks/task-0001/artifacts/huge.bin",
        member_size=MAX_ARTIFACT_MEMBER_BYTES + 1,
    )
    _write_archive(archive_path, data)

    with pytest.raises(LaunchError, match="artifact member is too large"):
        read_project_archive(archive_path)
