from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.task_store import (
    resolve_run,
    resolve_v2_paths,
    task_lock_path,
)
from tests.support.builders import create_implemented_task, init_workspace


def test_finish_without_validation_lock_does_not_mutate_run_or_task(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    task_id = create_implemented_task(tmp_path, slug="validation-finish-lock")
    started = runner.invoke(
        app, ["--json", "--root", str(tmp_path), "validate", "start"]
    )
    assert started.exit_code == 0, started.stdout
    run_id = _json(started)["result"]["run_id"]
    path = task_lock_path(resolve_v2_paths(tmp_path), task_id)
    path.unlink()
    run_before = resolve_run(tmp_path, task_id, str(run_id))

    finished = runner.invoke(
        app,
        [
            "--json",
            "--root",
            str(tmp_path),
            "validate",
            "finish",
            "--result",
            "blocked",
            "--summary",
            "Lock is missing.",
        ],
    )
    assert finished.exit_code != 0
    run_after = resolve_run(tmp_path, task_id, str(run_id))
    assert run_after.status == "running"
    assert run_after.finished_at == run_before.finished_at
    assert run_after.result == run_before.result
    from taskledger.storage.task_store import resolve_task

    assert resolve_task(tmp_path, task_id).status_stage == "implemented"


runner = CliRunner()


def _start_validation(root: Path) -> tuple[str, str]:
    task_id = create_implemented_task(root, slug="validation-recovery")
    started = runner.invoke(app, ["--json", "--root", str(root), "validate", "start"])
    assert started.exit_code == 0, started.stdout
    run_id = _json(started)["result"]["run_id"]
    return task_id, str(run_id)


def test_expired_validation_lock_guides_resume_and_blocks_new_start(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    task_id, run_id = _start_validation(tmp_path)
    _expire_lock(tmp_path, task_id)

    next_action = runner.invoke(app, ["--json", "--root", str(tmp_path), "next-action"])
    assert next_action.exit_code == 0, next_action.stdout
    next_result = _json(next_action)["result"]
    assert next_result["action"] == "expired-validation-lock-resume"
    assert "validate resume" in next_result["next_command"], next_result
    assert "--repair-expired-lock" in next_result["next_command"]
    assert run_id in next_result["next_command"], next_result.get("next_item")
    assert "repair lock" not in next_result["next_command"]

    lock_show = runner.invoke(
        app, ["--json", "--root", str(tmp_path), "lock", "show", "--task", task_id]
    )
    assert lock_show.exit_code == 0, lock_show.stdout
    assert "validate resume" in lock_show.stdout
    assert "--repair-expired-lock" in lock_show.stdout

    capability = runner.invoke(
        app, ["--json", "--root", str(tmp_path), "can", "validate", "--task", task_id]
    )
    assert capability.exit_code == 0, capability.stdout
    capability_result = _json(capability)["result"]
    assert capability_result["ok"] is False
    assert "validate resume" in str(capability_result["blocking"])


def test_removed_validation_lock_is_resumable_and_doctor_guides_recovery(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    task_id, run_id = _start_validation(tmp_path)
    task_lock_path(resolve_v2_paths(tmp_path), task_id).unlink()

    next_action = runner.invoke(app, ["--json", "--root", str(tmp_path), "next-action"])
    assert next_action.exit_code == 0, next_action.stdout
    next_result = _json(next_action)["result"]
    assert next_result["action"] == "validate-resume"
    assert "validate resume" in next_result["next_command"]
    assert run_id in next_result["next_command"]

    doctor = runner.invoke(app, ["--json", "--root", str(tmp_path), "doctor"])
    assert doctor.exit_code == 0, doctor.stdout
    assert "validate resume" in doctor.stdout

    capability = runner.invoke(
        app, ["--json", "--root", str(tmp_path), "can", "validate", "--task", task_id]
    )
    assert capability.exit_code == 0, capability.stdout
    capability_result = _json(capability)["result"]
    assert capability_result["ok"] is False
    assert "validate resume" in str(capability_result["blocking"])

    resumed = runner.invoke(
        app,
        [
            "--json",
            "--root",
            str(tmp_path),
            "validate",
            "resume",
            "--reason",
            "Reacquire after diagnosed lock removal.",
        ],
    )
    assert resumed.exit_code == 0, resumed.stdout
    assert _json(resumed)["result"]["run_id"] == run_id


def _json(result: object) -> dict[str, object]:
    return json.loads(result.stdout)


def _expire_lock(root: Path, task_id: str) -> None:
    path = task_lock_path(resolve_v2_paths(root), task_id)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["expires_at"] = "2000-01-01T00:00:00+00:00"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_resume_expired_validation_lock_preserves_run_evidence(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    task_id = create_implemented_task(tmp_path, slug="validation-resume")
    started = runner.invoke(
        app, ["--json", "--root", str(tmp_path), "validate", "start"]
    )
    assert started.exit_code == 0, started.stdout
    run_id = _json(started)["result"]["run_id"]

    command = runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "validate",
            "command",
            "--",
            sys.executable,
            "-c",
            "print('evidence')",
        ],
    )
    assert command.exit_code == 0, command.stdout
    previous = resolve_run(tmp_path, task_id, str(run_id))
    _expire_lock(tmp_path, task_id)

    resumed = runner.invoke(
        app,
        [
            "--json",
            "--root",
            str(tmp_path),
            "validate",
            "resume",
            "--reason",
            "Continue after validation timeout.",
            "--repair-expired-lock",
        ],
    )
    assert resumed.exit_code == 0, resumed.stdout
    payload = _json(resumed)["result"]
    assert payload["run_id"] == run_id
    assert payload["repaired_expired_lock"] is True
    current = resolve_run(tmp_path, task_id, str(run_id))
    assert current.status == "running"
    assert current.started_at == previous.started_at
    assert current.checks == previous.checks
    assert current.worklog == previous.worklog
    assert current.artifact_refs == previous.artifact_refs

    lock_path = task_lock_path(resolve_v2_paths(tmp_path), task_id)
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    assert lock["stage"] == "validating"
    assert lock["run_id"] == run_id
    assert lock["expires_at"] != "2000-01-01T00:00:00+00:00"


@pytest.mark.parametrize("mismatch", ["run_id", "stage"])
def test_resume_refuses_mismatched_expired_lock(tmp_path: Path, mismatch: str) -> None:
    init_workspace(tmp_path)
    task_id, run_id = _start_validation(tmp_path)
    path = task_lock_path(resolve_v2_paths(tmp_path), task_id)
    lock = yaml.safe_load(path.read_text(encoding="utf-8"))
    lock["expires_at"] = "2000-01-01T00:00:00+00:00"
    lock[mismatch] = "run-unrelated" if mismatch == "run_id" else "implementing"
    path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")
    before = path.read_bytes()

    resumed = runner.invoke(
        app,
        [
            "--json",
            "--root",
            str(tmp_path),
            "validate",
            "resume",
            "--reason",
            "Do not take an unrelated lock.",
            "--repair-expired-lock",
        ],
    )
    assert resumed.exit_code != 0
    assert path.read_bytes() == before
    assert resolve_run(tmp_path, task_id, run_id).status == "running"


def test_same_execution_validation_resume_is_idempotent(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    task_id = create_implemented_task(tmp_path, slug="validation-idempotent")
    identity = [
        "--actor",
        "agent",
        "--actor-name",
        "validator",
        "--actor-role",
        "validator",
        "--harness",
        "pi",
        "--session-id",
        "session-1",
    ]
    started = runner.invoke(
        app, ["--json", "--root", str(tmp_path), "validate", "start", *identity]
    )
    assert started.exit_code == 0, started.stdout
    run_id = _json(started)["result"]["run_id"]
    before_lock = yaml.safe_load(
        task_lock_path(resolve_v2_paths(tmp_path), task_id).read_text(encoding="utf-8")
    )

    resumed = runner.invoke(
        app,
        [
            "--json",
            "--root",
            str(tmp_path),
            "validate",
            "resume",
            "--reason",
            "Retry same execution.",
            *identity,
        ],
    )
    assert resumed.exit_code == 0, resumed.stdout
    result = _json(resumed)["result"]
    assert result["already_active"] is True
    assert result["run_id"] == run_id
    assert result["lock"]["lock_id"] == before_lock["lock_id"]


def test_validation_resume_cannot_take_other_execution_live_lock(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)
    task_id = create_implemented_task(tmp_path, slug="validation-other-owner")
    owner = [
        "--actor",
        "agent",
        "--actor-name",
        "owner",
        "--actor-role",
        "validator",
        "--harness",
        "pi",
        "--session-id",
        "session-owner",
    ]
    started = runner.invoke(
        app, ["--json", "--root", str(tmp_path), "validate", "start", *owner]
    )
    assert started.exit_code == 0, started.stdout
    path = task_lock_path(resolve_v2_paths(tmp_path), task_id)
    before = path.read_bytes()
    other = [
        "--actor",
        "agent",
        "--actor-name",
        "other",
        "--actor-role",
        "validator",
        "--harness",
        "pi",
        "--session-id",
        "session-other",
    ]

    resumed = runner.invoke(
        app,
        [
            "--json",
            "--root",
            str(tmp_path),
            "validate",
            "resume",
            "--reason",
            "Must not take another live lock.",
            *other,
        ],
    )
    assert resumed.exit_code != 0
    assert path.read_bytes() == before


def test_repair_lock_returns_validation_resume_follow_up(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    task_id, run_id = _start_validation(tmp_path)
    _expire_lock(tmp_path, task_id)

    repaired = runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "repair",
            "lock",
            "--task",
            task_id,
            "--reason",
            "Remove diagnosed expired validation lock.",
        ],
    )
    assert repaired.exit_code == 0, repaired.stdout
    assert "matching validation run" in repaired.stdout
    assert run_id in repaired.stdout
    assert "taskledger validate resume" in repaired.stdout
    assert "--repair-expired-lock" not in repaired.stdout
