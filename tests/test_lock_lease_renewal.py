from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.domain.models import ActorRef, HarnessRef
from taskledger.errors import LaunchError
from taskledger.services import tasks as task_services
from taskledger.services.implementation_flow import finish_implementation
from taskledger.services.run_store import show_lock
from taskledger.services.task_collections import (
    add_todo,
    set_todo_done,
    show_todo,
)
from taskledger.services.tasks import (
    activate_task,
    create_task,
    start_implementation,
    start_planning,
    start_validation,
)
from taskledger.storage.locks import read_lock, update_lock
from taskledger.storage.task_store import (
    load_todos,
    resolve_v2_paths,
    task_lock_path,
)
from tests.support.builders import create_approved_task, init_workspace

ACTOR = ActorRef(
    actor_type="agent",
    actor_name="taskledger",
    tool="pi",
    session_id="session-a",
    role="implementer",
)
HARNESS = HarnessRef(
    harness_id="pi",
    name="Pi",
    kind="agent_harness",
    session_id="session-a",
)


def _start_implementation(tmp_path: Path) -> tuple[str, Path]:
    init_workspace(tmp_path)
    task_id = create_approved_task(
        tmp_path,
        title="Lease renewal",
        slug="lease-renewal",
    )
    start_implementation(tmp_path, task_id, actor=ACTOR, harness=HARNESS)
    lock_path = task_lock_path(resolve_v2_paths(tmp_path), task_id)
    return task_id, lock_path


def _read_lock(lock_path: Path):
    lock = read_lock(lock_path)
    assert lock is not None
    return lock


@pytest.mark.parametrize("lease_seconds", [7200, 9000])
def test_todo_done_renews_owned_implementation_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lease_seconds: int,
) -> None:
    task_id, lock_path = _start_implementation(tmp_path)
    lock = _read_lock(lock_path)
    acquired_at = datetime.now(timezone.utc) - timedelta(hours=1)
    completed_at = acquired_at + timedelta(hours=1)
    lock = replace(
        lock,
        created_at=acquired_at.isoformat(),
        expires_at=(acquired_at + timedelta(seconds=lease_seconds)).isoformat(),
        lease_seconds=lease_seconds,
        last_heartbeat_at=acquired_at.isoformat(),
    )
    update_lock(lock_path, lock)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> FrozenDateTime:
            return cls.fromtimestamp(completed_at.timestamp(), tz=tz)

    monkeypatch.setattr(task_services, "datetime", FrozenDateTime)
    set_todo_done(
        tmp_path,
        task_id,
        "todo-0001",
        done=True,
        actor=ACTOR,
        harness=HARNESS,
    )

    renewed = _read_lock(lock_path)
    assert renewed.created_at == lock.created_at
    assert renewed.lock_id == lock.lock_id
    assert renewed.run_id == lock.run_id
    assert renewed.lease_seconds == lease_seconds
    assert renewed.last_heartbeat_at == completed_at.isoformat()
    assert (
        renewed.expires_at
        == (completed_at + timedelta(seconds=lease_seconds)).isoformat()
    )


def test_todo_done_from_another_session_does_not_renew_lock(tmp_path: Path) -> None:
    task_id, lock_path = _start_implementation(tmp_path)
    lock = _read_lock(lock_path)
    other_actor = replace(ACTOR, session_id="session-b")
    other_harness = replace(HARNESS, session_id="session-b")

    set_todo_done(
        tmp_path,
        task_id,
        "todo-0001",
        done=True,
        actor=other_actor,
        harness=other_harness,
    )

    assert _read_lock(lock_path) == lock


def test_read_only_todo_and_lock_show_do_not_renew(tmp_path: Path) -> None:
    task_id, lock_path = _start_implementation(tmp_path)
    lock = _read_lock(lock_path)

    show_todo(tmp_path, task_id, "todo-0001")
    show_lock(
        tmp_path,
        task_id,
        current_actor=ACTOR,
        current_harness=HARNESS,
    )

    assert _read_lock(lock_path) == lock


def test_todo_completion_without_a_lock_still_succeeds(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    task_id = create_approved_task(
        tmp_path,
        title="No active lock",
        slug="no-active-lock",
    )
    user = ActorRef(actor_type="user", actor_name="tester")

    set_todo_done(tmp_path, task_id, "todo-0001", done=True, actor=user)

    assert load_todos(tmp_path, task_id).todos[0].done


def test_planning_lock_is_not_renewed_by_todo_completion(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    task = create_task(
        tmp_path,
        title="Planning lock",
        slug="planning-lock",
        description="Verify non-implementation lock behavior.",
    )
    activate_task(tmp_path, task.id, reason="test setup")
    add_todo(tmp_path, task.id, text="Planning todo")
    start_planning(tmp_path, task.id)
    lock_path = task_lock_path(resolve_v2_paths(tmp_path), task.id)
    lock = _read_lock(lock_path)

    set_todo_done(
        tmp_path,
        task.id,
        "todo-0001",
        done=True,
        actor=ActorRef(actor_type="user", actor_name="tester"),
    )

    assert _read_lock(lock_path) == lock


def test_expired_implementation_lock_is_not_resurrected(tmp_path: Path) -> None:
    task_id, lock_path = _start_implementation(tmp_path)
    lock = _read_lock(lock_path)
    expired_lock = replace(
        lock,
        expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    )
    update_lock(lock_path, expired_lock)

    with pytest.raises(LaunchError):
        set_todo_done(
            tmp_path,
            task_id,
            "todo-0001",
            done=True,
            actor=ACTOR,
            harness=HARNESS,
        )

    assert _read_lock(lock_path) == expired_lock
    assert not load_todos(tmp_path, task_id).todos[0].done


def test_replaced_lock_is_not_overwritten_when_renewal_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id, lock_path = _start_implementation(tmp_path)
    lock = _read_lock(lock_path)
    replaced_lock = replace(lock, lock_id="replacement-lock")
    renew_lock_lease = task_services.renew_lock_lease

    def replace_then_renew(*args, **kwargs):
        update_lock(lock_path, replaced_lock)
        return renew_lock_lease(*args, **kwargs)

    monkeypatch.setattr(task_services, "renew_lock_lease", replace_then_renew)
    with pytest.raises(LaunchError, match="changed before lease renewal"):
        set_todo_done(
            tmp_path,
            task_id,
            "todo-0001",
            done=True,
            actor=ACTOR,
            harness=HARNESS,
        )

    assert _read_lock(lock_path) == replaced_lock
    assert load_todos(tmp_path, task_id).todos[0].done


def test_todo_cli_passes_resolved_actor_and_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taskledger import cli_misc

    _start_implementation(tmp_path)
    resolved: dict[str, object] = {}
    original_set_todo_done = cli_misc.set_todo_done

    def capture_identity(*args, **kwargs):
        resolved.update(kwargs)
        return original_set_todo_done(*args, **kwargs)

    monkeypatch.setattr(
        cli_misc,
        "resolve_effective_identity",
        lambda _root, *, cwd: (ACTOR, HARNESS),
    )
    monkeypatch.setattr(cli_misc, "set_todo_done", capture_identity)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "todo", "done", "todo-0001"],
    )

    assert result.exit_code == 0, result.stdout
    assert resolved["actor"] == ACTOR
    assert resolved["harness"] == HARNESS


def test_validation_lock_is_not_renewed_by_todo_completion(tmp_path: Path) -> None:
    task_id, lock_path = _start_implementation(tmp_path)
    set_todo_done(
        tmp_path,
        task_id,
        "todo-0001",
        done=True,
        actor=ACTOR,
        harness=HARNESS,
    )
    finish_implementation(tmp_path, task_id, summary="Implementation complete.")
    start_validation(tmp_path, task_id, actor=ACTOR, harness=HARNESS)
    lock = _read_lock(lock_path)

    with pytest.raises(LaunchError):
        set_todo_done(
            tmp_path,
            task_id,
            "todo-0001",
            done=True,
            actor=ACTOR,
            harness=HARNESS,
        )

    assert _read_lock(lock_path) == lock
