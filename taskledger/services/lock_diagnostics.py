"""Service-level lock diagnostics.

The storage layer (`taskledger/storage/locks.py`) reports lock persistence
state and time-based expiry. This module adds higher-level classification
that compares the lock holder against the current host/actor and produces
prescriptive remediation text. Storage stays free of process/host concerns.

The module is intentionally pure except for the injectable pid checker. Tests
pass a stub pid checker so they never touch real processes.
"""

from __future__ import annotations

import ctypes
import os
import platform
import socket
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from taskledger.domain.actor import ActorRef, HarnessRef
from taskledger.domain.lock import TaskLock
from taskledger.storage.locks import lock_is_expired

PidCheck = Callable[[int], str]

CLASSIFICATION_NONE = "none"
CLASSIFICATION_EXPIRED = "expired"
CLASSIFICATION_ACTIVE_LIVE_LOCAL_PROCESS = "active_live_local_process"
CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS = "active_dead_local_process"
CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS = (
    "active_unverifiable_remote_or_unknown_process"
)
CLASSIFICATION_ACTIVE_NO_PID = "active_no_pid"
CLASSIFICATION_ACTIVE_SAME_ACTOR = "active_same_actor"
CLASSIFICATION_ACTIVE_CURRENT_EXECUTION = "active_current_execution"
CLASSIFICATION_ACTIVE_HARNESS_SESSION = "active_harness_session"
CLASSIFICATION_ACTIVE_OTHER_ACTOR = "active_other_actor"

PID_CHECK_ALIVE = "alive"
PID_CHECK_ALIVE_UNOWNED = "alive_unowned"
PID_CHECK_DEAD = "dead"
PID_CHECK_NA = "n/a"
PID_CHECK_UNKNOWN = "unknown"


def _posix_pid_checker(pid: int) -> str:
    """Probe a local PID using POSIX ``os.kill(pid, 0)`` semantics."""

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return PID_CHECK_DEAD
    except PermissionError:
        return PID_CHECK_ALIVE_UNOWNED
    except OSError:
        return PID_CHECK_DEAD
    return PID_CHECK_ALIVE


def _windows_pid_checker(pid: int) -> str:
    """Probe a local Windows PID without sending console control events."""

    if pid <= 0:
        return PID_CHECK_DEAD

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return PID_CHECK_ALIVE

    error = ctypes.get_last_error()  # type: ignore[attr-defined]
    if error == 5:  # ERROR_ACCESS_DENIED
        return PID_CHECK_ALIVE_UNOWNED
    if error == 87:  # ERROR_INVALID_PARAMETER
        return PID_CHECK_DEAD
    return PID_CHECK_UNKNOWN


def default_pid_checker(pid: int) -> str:
    """Probe a local PID without interrupting the current process on Windows."""

    if platform.system() == "Windows":
        return _windows_pid_checker(pid)
    return _posix_pid_checker(pid)


def current_host_name() -> str:
    """Best-effort local host identification.

    Returns the short hostname (before the first dot). Tests can monkeypatch
    this to simulate different hosts.
    """

    raw = socket.gethostname() or platform.node() or ""
    return raw.split(".", 1)[0]


def _host_matches(holder_host: str | None, current_host: str) -> bool:
    if not holder_host:
        return False
    candidates = {
        socket.gethostname() or "",
        socket.getfqdn() or "",
        platform.node() or "",
        current_host,
        (socket.gethostname() or "").split(".", 1)[0],
        (socket.getfqdn() or "").split(".", 1)[0],
        (platform.node() or "").split(".", 1)[0],
    }
    candidates.discard("")
    holder_short = holder_host.split(".", 1)[0]
    return holder_host in candidates or holder_short in candidates


def _actor_matches(holder: ActorRef, current_actor: ActorRef | None) -> bool:
    if current_actor is None:
        return False
    if holder.actor_id and current_actor.actor_id:
        return holder.actor_id == current_actor.actor_id
    if holder.actor_type != current_actor.actor_type:
        return False
    return holder.actor_name == current_actor.actor_name


def _actor_identity_matches(holder: ActorRef, current_actor: ActorRef) -> bool:
    if holder.actor_id or current_actor.actor_id:
        return bool(holder.actor_id and holder.actor_id == current_actor.actor_id)
    return (
        holder.actor_type == current_actor.actor_type
        and holder.actor_name == current_actor.actor_name
    )


def lock_owned_by_current_execution(
    lock: TaskLock,
    *,
    current_actor: ActorRef,
    current_harness: HarnessRef | None = None,
    current_host: str | None = None,
) -> bool:
    """Return whether strong identity evidence ties the lock to this execution."""
    holder = lock.holder
    holder_harness_name = (
        lock.harness.name
        if lock.harness is not None
        else (
            holder.tool
            or (holder.actor_name if holder.actor_name in KNOWN_HARNESS_TOOLS else None)
        )
    )
    current_harness_name = (
        current_harness.name if current_harness is not None else current_actor.tool
    )
    holder_session_id = (
        lock.harness.session_id if lock.harness is not None else None
    ) or holder.session_id
    current_session_id = (
        current_harness.session_id if current_harness is not None else None
    ) or current_actor.session_id

    if (
        holder_harness_name
        and current_harness_name
        and holder_harness_name.casefold() == current_harness_name.casefold()
        and holder_session_id
        and current_session_id
        and holder_session_id == current_session_id
    ):
        return True

    if (
        holder.session_id
        and current_actor.session_id
        and holder.session_id == current_actor.session_id
        and _actor_identity_matches(holder, current_actor)
    ):
        return True

    host = current_host or current_host_name()
    return (
        holder.pid_scope == "owner"
        and current_actor.pid_scope == "owner"
        and holder.pid is not None
        and holder.pid == current_actor.pid
        and _host_matches(holder.host, host)
        and _host_matches(current_actor.host, host)
        and _actor_identity_matches(holder, current_actor)
    )


def _seconds_until_expiry(lock: TaskLock, now: datetime) -> int | None:
    if not lock.expires_at:
        return None
    try:
        expires_at = datetime.fromisoformat(lock.expires_at)
    except ValueError:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    delta = (expires_at - now).total_seconds()
    return int(delta)


def _format_expiry_delta(seconds: int | None) -> str:
    if seconds is None:
        return "no expiry"
    if seconds <= 0:
        return "expired"
    total = seconds
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or not hours:
        parts.append(f"{minutes}m")
    return f"valid for {' '.join(parts)}"


@dataclass(frozen=True)
class LockDiagnostics:
    """Prescriptive classification of a TaskLock.

    Storage-layer ``lock_status()`` answers "is the lock file present and
    unexpired?". This answers "given the current host/actor, what should the
    agent do next?".
    """

    active: bool
    expired: bool
    classification: str
    holder: dict[str, object] | None
    holder_pid: int | None
    holder_host: str | None
    current_host: str
    holder_pid_check: str
    seconds_until_expiry: int | None
    expiry_label: str
    summary: str
    remediation: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _empty_diagnostics(current_host: str) -> LockDiagnostics:
    return LockDiagnostics(
        active=False,
        expired=False,
        classification=CLASSIFICATION_NONE,
        holder=None,
        holder_pid=None,
        holder_host=None,
        current_host=current_host,
        holder_pid_check=PID_CHECK_NA,
        seconds_until_expiry=None,
        expiry_label="n/a",
        summary="No active lock.",
        remediation=(),
    )


def _remediation_for_expired(lock: TaskLock, task_id: str | None) -> tuple[str, ...]:
    target = task_id or lock.task_id
    if lock.stage == "implementing":
        return (
            (
                f"taskledger implement resume --task {target} "
                f'--repair-expired-lock --reason "Reacquire expired '
                f'implementation lock."'
            ),
        )
    return (
        (
            f"taskledger repair lock --task {target} "
            f'--reason "Recover expired {lock.stage} lock."'
        ),
    )


def _remediation_for_dead_local(
    lock: TaskLock, task_id: str | None, pid: int
) -> tuple[str, ...]:
    target = task_id or lock.task_id
    if lock.stage == "implementing":
        return (
            (
                f"taskledger repair lock --task {target} "
                f'--reason "Holder PID {pid} is no longer running."'
            ),
            (
                f"taskledger implement resume --task {target} "
                f'--reason "Reacquire implementation lock after stale '
                f'holder repair."'
            ),
        )
    return (
        (
            f"taskledger repair lock --task {target} "
            f'--reason "Holder PID {pid} is no longer running."'
        ),
    )


def _remediation_for_unverifiable(
    lock: TaskLock, task_id: str | None
) -> tuple[str, ...]:
    target = task_id or lock.task_id
    pid_text = f" PID {lock.holder.pid}" if lock.holder.pid else ""
    return (
        (
            f"# Holder{pid_text} is on host {lock.holder.host!r}; "
            f"verify liveness manually before repairing."
        ),
        f"taskledger lock show --task {target}",
    )


KNOWN_HARNESS_TOOLS = {"pi", "codex", "opencode"}


def _pid_is_checkable_owner(holder: ActorRef, lock: TaskLock) -> bool:
    """Return True if the holder PID is safe to probe for lock-owner liveness."""
    scope = getattr(holder, "pid_scope", None)
    if scope == "owner":
        return holder.pid is not None
    if scope in {"command", "unverifiable_harness"}:
        return False

    # Legacy inference for old lock records with no pid_scope.
    if holder.session_id or holder.harness_id or lock.harness is not None:
        tool = (holder.tool or "").lower()
        harness_name = (lock.harness.name if lock.harness else "").lower()
        if tool in KNOWN_HARNESS_TOOLS or harness_name in KNOWN_HARNESS_TOOLS:
            return False

    return holder.pid is not None


def diagnose_lock(
    lock: TaskLock | None,
    *,
    task_id: str | None = None,
    current_actor: ActorRef | None = None,
    current_harness: HarnessRef | None = None,
    now: datetime | None = None,
    pid_checker: PidCheck | None = None,
    current_host: str | None = None,
) -> LockDiagnostics:
    """Classify ``lock`` and produce remediation guidance.

    Parameters
    ----------
    lock:
        The active lock to inspect, or ``None``.
    task_id:
        Task id to embed in remediation commands. Defaults to ``lock.task_id``.
    current_actor:
        The actor the caller is currently representing. Matching logical actor
        identity alone does not prove current-execution ownership. ``None`` means
        unknown.
    current_harness:
        The harness the caller is currently representing. Matching provider and
        non-empty session IDs establish current-execution ownership.
    now:
        Reference time for expiry checks. Defaults to ``datetime.now(utc)``.
    pid_checker:
        Callable used to verify a local holder PID. Defaults to
        :func:`default_pid_checker`. Tests inject a stub.
    current_host:
        Override for the local hostname. Defaults to
        :func:`current_host_name`. Tests inject to simulate remote holders.
    """

    host = current_host or current_host_name()
    if lock is None:
        return _empty_diagnostics(host)

    reference = now or datetime.now(timezone.utc)
    expired = lock_is_expired(lock, now=reference)
    seconds = _seconds_until_expiry(lock, reference)
    expiry_label = _format_expiry_delta(seconds)
    holder = lock.holder
    holder_dict = holder.to_dict()
    pid = holder.pid
    holder_host = holder.host

    if expired:
        remediation = _remediation_for_expired(lock, task_id)
        summary = (
            f"Expired {lock.stage} lock from run {lock.run_id}; "
            "follow the recommended recovery command."
        )
        return LockDiagnostics(
            active=True,
            expired=True,
            classification=CLASSIFICATION_EXPIRED,
            holder=holder_dict,
            holder_pid=pid,
            holder_host=holder_host,
            current_host=host,
            holder_pid_check=PID_CHECK_NA,
            seconds_until_expiry=seconds,
            expiry_label=expiry_label,
            summary=summary,
            remediation=remediation,
        )

    current_execution = current_actor is not None and lock_owned_by_current_execution(
        lock,
        current_actor=current_actor,
        current_harness=current_harness,
        current_host=host,
    )
    if current_execution:
        return LockDiagnostics(
            active=True,
            expired=False,
            classification=CLASSIFICATION_ACTIVE_CURRENT_EXECUTION,
            holder=holder_dict,
            holder_pid=pid,
            holder_host=holder_host,
            current_host=host,
            holder_pid_check=PID_CHECK_NA,
            seconds_until_expiry=seconds,
            expiry_label=expiry_label,
            summary=(
                f"Active {lock.stage} lock is owned by the current execution; "
                "continue with the existing lock."
            ),
            remediation=(),
        )

    same_actor = _actor_matches(holder, current_actor)
    if pid is None:
        pid_scope = getattr(holder, "pid_scope", None)
        has_harness_session = bool(
            holder.session_id
            or holder.harness_id
            or (lock.harness is not None)
            or pid_scope == "unverifiable_harness"
        )
        if same_actor:
            classification = CLASSIFICATION_ACTIVE_SAME_ACTOR
            summary = (
                f"Active {lock.stage} lock has the same logical actor identity "
                f"({holder.actor_type}:{holder.actor_name}), but this execution "
                "is unverified; no holder PID was recorded."
            )
            remediation = ()
        elif has_harness_session:
            classification = CLASSIFICATION_ACTIVE_HARNESS_SESSION
            session_info = holder.session_id or "unknown"
            summary = (
                f"Active {lock.stage} lock is held by harness session "
                f"{holder.actor_name}/{session_info}; no owner PID is available "
                "for liveness probing. Do not repair solely from command PID state."
            )
            remediation = (f"taskledger lock show --task {task_id or lock.task_id}",)
        elif _host_matches(holder_host, host):
            classification = CLASSIFICATION_ACTIVE_NO_PID
            summary = (
                f"Active {lock.stage} lock is held by "
                f"{holder.actor_type}:{holder.actor_name} on this host, "
                "but no holder PID was recorded."
            )
            remediation = (f"taskledger lock show --task {task_id or lock.task_id}",)
        else:
            classification = (
                CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS
            )
            summary = (
                f"Active {lock.stage} lock is held by "
                f"{holder.actor_type}:{holder.actor_name} on host "
                f"{holder_host!r}; liveness cannot be verified "
                "without a PID."
            )
            remediation = _remediation_for_unverifiable(lock, task_id)
        return LockDiagnostics(
            active=True,
            expired=False,
            classification=classification,
            holder=holder_dict,
            holder_pid=None,
            holder_host=holder_host,
            current_host=host,
            holder_pid_check=PID_CHECK_NA,
            seconds_until_expiry=seconds,
            expiry_label=expiry_label,
            summary=summary,
            remediation=remediation,
        )

    checkable = _pid_is_checkable_owner(holder, lock)

    if not checkable:
        # PID exists but is not a reliable owner indicator (harness/command subprocess).
        if same_actor:
            classification = CLASSIFICATION_ACTIVE_SAME_ACTOR
            summary = (
                f"Active {lock.stage} lock has the same logical actor identity "
                f"({holder.actor_type}:{holder.actor_name}), but this execution "
                "is unverified; its PID is a command subprocess."
            )
            remediation = ()
        else:
            classification = CLASSIFICATION_ACTIVE_HARNESS_SESSION
            session_info = holder.session_id or "unknown"
            summary = (
                f"Active {lock.stage} lock is held by harness session "
                f"{holder.actor_name}/{session_info}; no owner PID is available "
                "for liveness probing. Do not repair solely from command PID state."
            )
            remediation = (f"taskledger lock show --task {task_id or lock.task_id}",)
        pid_status_out = PID_CHECK_NA
    else:
        pid_check = pid_checker or default_pid_checker
        host_match = _host_matches(holder_host, host)
        if host_match:
            pid_status = pid_check(pid)
        else:
            pid_status = PID_CHECK_UNKNOWN

        pid_alive = pid_status in {PID_CHECK_ALIVE, PID_CHECK_ALIVE_UNOWNED}

        if not host_match or pid_status == PID_CHECK_UNKNOWN:
            classification = (
                CLASSIFICATION_ACTIVE_UNVERIFIABLE_REMOTE_OR_UNKNOWN_PROCESS
            )
            summary = (
                f"Active {lock.stage} lock is held by {holder.actor_type}:"
                f"{holder.actor_name} on host {holder_host!r}; cannot verify "
                "the holder process from this host."
            )
            remediation = _remediation_for_unverifiable(lock, task_id)
            pid_status_out = PID_CHECK_UNKNOWN
        elif not pid_alive:
            classification = CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS
            summary = (
                f"Active non-expired {lock.stage} lock is held by a local PID "
                f"({pid}) that is no longer running."
            )
            remediation = _remediation_for_dead_local(lock, task_id, pid)
            pid_status_out = pid_status
        elif same_actor:
            classification = CLASSIFICATION_ACTIVE_SAME_ACTOR
            summary = (
                f"Active {lock.stage} lock has the same logical actor identity "
                f"({holder.actor_type}:{holder.actor_name}), but this execution "
                f"is unverified; holder PID {pid} is alive on this host."
            )
            remediation = ()
            pid_status_out = pid_status
        else:
            classification = CLASSIFICATION_ACTIVE_OTHER_ACTOR
            summary = (
                f"Active {lock.stage} lock is held by a different actor "
                f"({holder.actor_type}:{holder.actor_name}); holder PID {pid} "
                "is alive on this host."
            )
            remediation = (
                (
                    "# Do not take over a live lock from another actor; "
                    "use a handoff or wait for the holder to release."
                ),
                f"taskledger lock show --task {task_id or lock.task_id}",
            )
            pid_status_out = pid_status

    return LockDiagnostics(
        active=True,
        expired=False,
        classification=classification,
        holder=holder_dict,
        holder_pid=pid,
        holder_host=holder_host,
        current_host=host,
        holder_pid_check=pid_status_out,
        seconds_until_expiry=seconds,
        expiry_label=expiry_label,
        summary=summary,
        remediation=remediation,
    )


def diagnostics_from_payload(payload: dict[str, Any]) -> LockDiagnostics | None:
    """Reconstruct diagnostics from a JSON payload (best effort)."""

    raw = payload.get("diagnostics")
    if not isinstance(raw, dict):
        return None
    remediation = raw.get("remediation") or ()
    if isinstance(remediation, list | tuple):
        remediation_tuple = tuple(str(item) for item in remediation)
    else:
        remediation_tuple = ()
    return LockDiagnostics(
        active=bool(raw.get("active", False)),
        expired=bool(raw.get("expired", False)),
        classification=str(raw.get("classification", "")),
        holder=raw.get("holder") if isinstance(raw.get("holder"), dict) else None,
        holder_pid=(
            raw.get("holder_pid") if isinstance(raw.get("holder_pid"), int) else None
        ),
        holder_host=(
            raw.get("holder_host") if isinstance(raw.get("holder_host"), str) else None
        ),
        current_host=str(raw.get("current_host", "")),
        holder_pid_check=str(raw.get("holder_pid_check", "")),
        seconds_until_expiry=(
            raw.get("seconds_until_expiry")
            if isinstance(raw.get("seconds_until_expiry"), int)
            else None
        ),
        expiry_label=str(raw.get("expiry_label", "")),
        summary=str(raw.get("summary", "")),
        remediation=remediation_tuple,
    )
