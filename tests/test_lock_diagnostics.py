from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from taskledger.domain.actor import ActorRef
from taskledger.domain.lock import TaskLock
from taskledger.services.lock_diagnostics import (
    CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS,
    CLASSIFICATION_ACTIVE_NO_PID,
    CLASSIFICATION_ACTIVE_OTHER_ACTOR,
    CLASSIFICATION_ACTIVE_SAME_ACTOR,
    CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS,
    CLASSIFICATION_EXPIRED,
    CLASSIFICATION_NONE,
    PID_CHECK_ALIVE,
    PID_CHECK_DEAD,
    PID_CHECK_UNKNOWN,
    _posix_pid_checker,
    diagnose_lock,
    diagnostics_from_payload,
)

NOW = datetime(2026, 6, 4, 20, 49, 47, tzinfo=timezone.utc)
HOST_LOCAL = "wsl"
HOST_REMOTE = "build-server-01"


def _holder(**overrides: object) -> ActorRef:
    base: dict[str, object] = {
        "actor_type": "user",
        "actor_name": "nahrstaedt",
        "host": HOST_LOCAL,
        "pid": 512425,
    }
    base.update(overrides)
    return ActorRef.from_dict(base)


def _lock(
    *,
    holder: ActorRef | None = None,
    stage: str = "implementing",
    expires_at: str | None = "2026-06-04T22:35:58.611426+00:00",
) -> TaskLock:
    return TaskLock(
        lock_id="lock-20260604T203558Z-0001",
        task_id="task-0001",
        stage=stage,  # type: ignore[arg-type]
        run_id="run-0002",
        created_at="2026-06-04T20:35:58.611426+00:00",
        expires_at=expires_at,
        reason="Continuing todo-0004",
        holder=holder or _holder(),
    )


# specmason: req=REQ-0030 ac=AC-0346
def test_diagnose_lock_none_returns_none_classification() -> None:
    diag = diagnose_lock(None, current_host=HOST_LOCAL)

    assert diag.classification == CLASSIFICATION_NONE
    assert diag.active is False
    assert diag.expired is False
    assert diag.holder is None
    assert diag.remediation == ()


# specmason: req=REQ-0030 ac=AC-0339
def test_diagnose_expired_impl_recommends_repair_flag() -> None:
    expired_at = NOW - timedelta(minutes=5)
    lock = _lock(
        expires_at=expired_at.isoformat(),
    )

    diag = diagnose_lock(lock, now=NOW, current_host=HOST_LOCAL)

    assert diag.classification == CLASSIFICATION_EXPIRED
    assert diag.expired is True
    assert diag.active is True
    assert diag.seconds_until_expiry is not None
    assert diag.seconds_until_expiry < 0
    assert len(diag.remediation) == 1
    assert "implement resume" in diag.remediation[0]
    assert "--repair-expired-lock" in diag.remediation[0]
    assert "--task task-0001" in diag.remediation[0]


# specmason: req=REQ-0030 ac=AC-0340
def test_diagnose_lock_expired_planning_recommends_repair_lock() -> None:
    expired_at = NOW - timedelta(minutes=5)
    lock = _lock(
        holder=_holder(actor_type="agent", actor_name="planner"),
        stage="planning",
        expires_at=expired_at.isoformat(),
    )

    diag = diagnose_lock(lock, now=NOW, current_host=HOST_LOCAL)

    assert diag.classification == CLASSIFICATION_EXPIRED
    assert diag.remediation[0].startswith("taskledger repair lock")


# specmason: req=REQ-0030 ac=AC-0341
def test_diagnose_lock_local_dead_pid_classifies_dead_local_process() -> None:
    lock = _lock()

    diag = diagnose_lock(
        lock,
        now=NOW,
        current_host=HOST_LOCAL,
        pid_checker=lambda pid: PID_CHECK_DEAD,
    )

    assert diag.classification == CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS
    assert diag.holder_pid_check == PID_CHECK_DEAD
    assert diag.expired is False
    assert diag.holder_pid == 512425
    assert diag.holder_host == HOST_LOCAL
    assert "is no longer running" in diag.summary
    assert any(
        "taskledger repair lock --task task-0001" in cmd for cmd in diag.remediation
    )
    assert any(
        "taskledger implement resume --task task-0001" in cmd
        for cmd in diag.remediation
    )
    assert any("Holder PID 512425" in cmd for cmd in diag.remediation)


# specmason: req=REQ-0030 ac=AC-0342
def test_diagnose_lock_local_dead_pid_for_planning_only_recommends_repair() -> None:
    lock = _lock(stage="planning")

    diag = diagnose_lock(
        lock,
        now=NOW,
        current_host=HOST_LOCAL,
        pid_checker=lambda pid: PID_CHECK_DEAD,
    )

    assert diag.classification == CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS
    assert all("implement resume" not in cmd for cmd in diag.remediation), (
        diag.remediation
    )


# specmason: req=REQ-0030 ac=AC-0343
def test_diagnose_lock_local_live_pid_other_actor_classifies_other_actor() -> None:
    lock = _lock()
    current = ActorRef(actor_type="agent", actor_name="pi")

    diag = diagnose_lock(
        lock,
        now=NOW,
        current_actor=current,
        current_host=HOST_LOCAL,
        pid_checker=lambda pid: PID_CHECK_ALIVE,
    )

    assert diag.classification == CLASSIFICATION_ACTIVE_OTHER_ACTOR
    assert diag.holder_pid_check == PID_CHECK_ALIVE
    # Live other-actor locks must not advertise `repair lock`.
    assert all("taskledger repair lock" not in cmd for cmd in diag.remediation), (
        diag.remediation
    )


# specmason: req=REQ-0030 ac=AC-0344
def test_diagnose_lock_local_live_pid_same_actor_classifies_same_actor() -> None:
    lock = _lock()
    current = ActorRef(actor_type="user", actor_name="nahrstaedt", host=HOST_LOCAL)

    diag = diagnose_lock(
        lock,
        now=NOW,
        current_actor=current,
        current_host=HOST_LOCAL,
        pid_checker=lambda pid: PID_CHECK_ALIVE,
    )

    assert diag.classification == CLASSIFICATION_ACTIVE_SAME_ACTOR
    assert diag.holder_pid_check == PID_CHECK_ALIVE
    assert diag.remediation == ()


# specmason: req=REQ-0030 ac=AC-0347
def test_diagnose_lock_remote_host_is_unverifiable() -> None:
    lock = _lock(holder=_holder(host=HOST_REMOTE, pid=99999))

    diag = diagnose_lock(
        lock,
        now=NOW,
        current_host=HOST_LOCAL,
        # Even if the local pid_checker would say "dead", the diagnostics
        # must NOT classify a remote/unknown host as a dead local process.
        pid_checker=lambda pid: PID_CHECK_DEAD,
    )

    assert (
        diag.classification
        == CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS
    )
    assert diag.holder_pid_check in {"unknown", "n/a"}
    assert all(
        "taskledger repair lock --reason" not in cmd for cmd in diag.remediation
    ), diag.remediation
    # The diagnostics should explicitly warn the caller to verify manually.
    assert any("verify" in cmd.lower() for cmd in diag.remediation)


# specmason: req=REQ-0030 ac=AC-0345
def test_diagnose_lock_no_pid_local_host_classifies_no_pid() -> None:
    lock = _lock(holder=_holder(pid=None))

    diag = diagnose_lock(
        lock,
        now=NOW,
        current_host=HOST_LOCAL,
    )

    assert diag.classification == CLASSIFICATION_ACTIVE_NO_PID
    assert diag.holder_pid_check == "n/a"
    # No repair recommendation without evidence the holder is dead.
    assert all(
        "taskledger repair lock --reason" not in cmd for cmd in diag.remediation
    ), diag.remediation


# specmason: req=REQ-0030 ac=AC-0348
def test_diagnose_lock_same_actor_without_pid_still_classifies_same_actor() -> None:
    lock = _lock(holder=_holder(pid=None))
    current = ActorRef(actor_type="user", actor_name="nahrstaedt")

    diag = diagnose_lock(
        lock,
        now=NOW,
        current_actor=current,
        current_host=HOST_LOCAL,
    )

    assert diag.classification == CLASSIFICATION_ACTIVE_SAME_ACTOR
    assert diag.remediation == ()


# specmason: req=REQ-0030 ac=AC-0356
def test_posix_pid_checker_permission_error_is_treated_as_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PID owned by another user must not be reported as dead."""

    import os

    def fake_kill(pid: int, sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "kill", fake_kill)

    assert _posix_pid_checker(512425) == "alive_unowned"


# specmason: req=REQ-0030 ac=AC-0349
def test_diagnose_lock_unknown_pid_check_stays_unverifiable() -> None:
    lock = _lock()

    diag = diagnose_lock(
        lock,
        now=NOW,
        current_host=HOST_LOCAL,
        pid_checker=lambda pid: PID_CHECK_UNKNOWN,
    )

    assert (
        diag.classification
        == CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS
    )
    assert diag.holder_pid_check == PID_CHECK_UNKNOWN
    assert all("taskledger repair lock" not in cmd for cmd in diag.remediation), (
        diag.remediation
    )


# specmason: req=REQ-0030 ac=AC-0351
def test_diagnostics_to_dict_round_trips_through_payload_reconstruction() -> None:
    lock = _lock()
    diag = diagnose_lock(
        lock,
        now=NOW,
        current_host=HOST_LOCAL,
        pid_checker=lambda pid: PID_CHECK_DEAD,
    )

    rebuilt = diagnostics_from_payload({"diagnostics": diag.to_dict()})

    assert rebuilt is not None
    assert rebuilt.classification == CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS
    assert rebuilt.remediation == diag.remediation
    assert rebuilt.summary == diag.summary


# specmason: req=REQ-0030 ac=AC-0350
def test_diagnose_lock_uses_task_id_in_remediation_when_provided() -> None:
    lock = _lock()

    diag = diagnose_lock(
        lock,
        task_id="task-0099",
        now=NOW,
        current_host=HOST_LOCAL,
        pid_checker=lambda pid: PID_CHECK_DEAD,
    )

    assert all("--task task-0099" in cmd for cmd in diag.remediation)


class TestHarnessSessionDiagnostics:
    """Tests for harness session PID scope and legacy inference."""

    # specmason: req=REQ-0030 ac=AC-0357
    def test_pi_harness_without_owner_pid_is_not_dead_local_process(self) -> None:
        from taskledger.services.lock_diagnostics import (
            CLASSIFICATION_ACTIVE_HARNESS_SESSION,
        )

        lock = _lock(
            holder=_holder(
                actor_type="agent",
                actor_name="pi",
                tool="pi",
                session_id="pi-session-1",
                pid=None,
                command_pid=999999,
                pid_scope="unverifiable_harness",
            )
        )

        diag = diagnose_lock(
            lock,
            now=NOW,
            current_host=HOST_LOCAL,
            pid_checker=lambda pid: PID_CHECK_DEAD,
        )

        assert diag.classification == CLASSIFICATION_ACTIVE_HARNESS_SESSION
        assert diag.holder_pid_check in {"n/a", "unknown"}
        assert all("repair lock" not in cmd for cmd in diag.remediation)

    # specmason: req=REQ-0030 ac=AC-0353
    def test_harness_owner_pid_dead_still_repairs(self) -> None:
        lock = _lock(
            holder=_holder(
                actor_type="agent",
                actor_name="pi",
                tool="pi",
                session_id="pi-session-1",
                pid=999999,
                command_pid=111,
                pid_scope="owner",
            )
        )

        diag = diagnose_lock(
            lock,
            now=NOW,
            current_host=HOST_LOCAL,
            pid_checker=lambda pid: PID_CHECK_DEAD,
        )

        assert diag.classification == CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS
        assert any("repair lock" in cmd for cmd in diag.remediation)

    # specmason: req=REQ-0030 ac=AC-0356
    def test_legacy_pi_lock_with_session_inferred_as_unverifiable(self) -> None:
        from taskledger.services.lock_diagnostics import (
            CLASSIFICATION_ACTIVE_HARNESS_SESSION,
        )

        # Old record: tool=pi, session_id present, pid=some_value, no pid_scope.
        lock = _lock(
            holder=_holder(
                actor_type="agent",
                actor_name="pi",
                tool="pi",
                session_id="pi-session-1",
                pid=999999,
                # pid_scope intentionally not set (legacy).
            )
        )

        diag = diagnose_lock(
            lock,
            now=NOW,
            current_host=HOST_LOCAL,
            pid_checker=lambda pid: PID_CHECK_DEAD,
        )

        # Should be classified as harness session, not dead local process.
        assert diag.classification == CLASSIFICATION_ACTIVE_HARNESS_SESSION
        assert all("repair lock" not in cmd for cmd in diag.remediation)

    # specmason: req=REQ-0030 ac=AC-0355
    def test_legacy_pi_lock_with_harness_ref_inferred_as_unverifiable(self) -> None:
        from taskledger.domain.actor import HarnessRef
        from taskledger.services.lock_diagnostics import (
            CLASSIFICATION_ACTIVE_HARNESS_SESSION,
        )

        lock = TaskLock(
            lock_id="lock-test",
            task_id="task-0001",
            stage="implementing",
            run_id="run-0001",
            created_at=NOW.isoformat(),
            expires_at=(NOW + timedelta(hours=2)).isoformat(),
            reason="test",
            holder=_holder(
                actor_type="agent",
                actor_name="pi",
                pid=999999,
            ),
            harness=HarnessRef(
                harness_id="h-001",
                name="pi",
                kind="agent_harness",
                session_id="pi-session-1",
            ),
        )

        diag = diagnose_lock(
            lock,
            now=NOW,
            current_host=HOST_LOCAL,
            pid_checker=lambda pid: PID_CHECK_DEAD,
        )

        assert diag.classification == CLASSIFICATION_ACTIVE_HARNESS_SESSION
        assert all("repair lock" not in cmd for cmd in diag.remediation)

    # specmason: req=REQ-0030 ac=AC-0338
    def test_command_pid_scope_not_checkable(self) -> None:
        from taskledger.services.lock_diagnostics import (
            CLASSIFICATION_ACTIVE_HARNESS_SESSION,
        )

        lock = _lock(
            holder=_holder(
                actor_type="agent",
                actor_name="some-agent",
                session_id="s1",
                pid=999999,
                pid_scope="command",
            )
        )

        diag = diagnose_lock(
            lock,
            now=NOW,
            current_host=HOST_LOCAL,
            pid_checker=lambda pid: PID_CHECK_DEAD,
        )

        assert diag.classification == CLASSIFICATION_ACTIVE_HARNESS_SESSION
        assert all("repair lock" not in cmd for cmd in diag.remediation)

    # specmason: req=REQ-0030 ac=AC-0352
    def test_direct_user_dead_pid_still_repairs(self) -> None:
        # Direct user: no harness session, no pid_scope, dead pid -> still dead local.
        lock = _lock(
            holder=_holder(
                actor_type="user",
                actor_name="nahrstaedt",
                pid=999999,
            )
        )

        diag = diagnose_lock(
            lock,
            now=NOW,
            current_host=HOST_LOCAL,
            pid_checker=lambda pid: PID_CHECK_DEAD,
        )

        assert diag.classification == CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS
        assert any("repair lock" in cmd for cmd in diag.remediation)

    # specmason: req=REQ-0030 ac=AC-0354
    def test_harness_session_same_actor_classification(self) -> None:
        from taskledger.services.lock_diagnostics import (
            CLASSIFICATION_ACTIVE_SAME_ACTOR,
        )

        lock = _lock(
            holder=_holder(
                actor_type="agent",
                actor_name="pi",
                tool="pi",
                session_id="pi-session-1",
                pid=999999,
                pid_scope="unverifiable_harness",
            )
        )
        current = ActorRef(
            actor_type="agent",
            actor_name="pi",
            tool="pi",
            session_id="pi-session-1",
        )

        diag = diagnose_lock(
            lock,
            current_actor=current,
            now=NOW,
            current_host=HOST_LOCAL,
            pid_checker=lambda pid: PID_CHECK_DEAD,
        )

        assert diag.classification == CLASSIFICATION_ACTIVE_SAME_ACTOR
        assert diag.remediation == ()
