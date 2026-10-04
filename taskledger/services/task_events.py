from __future__ import annotations

import getpass
import os
import socket
from pathlib import Path

from taskledger.domain.models import ActorRef, HarnessRef, TaskEvent, TaskLock
from taskledger.storage.events import append_event, next_event_id
from taskledger.storage.task_store import V2Paths, resolve_v2_paths, task_audit_dir
from taskledger.storage.yaml_store import write_yaml_object
from taskledger.timeutils import utc_now_iso


def default_actor() -> ActorRef:
    return ActorRef(
        actor_type="agent",
        actor_name=getpass.getuser() or "taskledger",
        host=socket.gethostname(),
        pid=os.getpid(),
    )


def default_harness() -> HarnessRef:
    return HarnessRef(
        harness_id="harness-unknown",
        name=os.getenv("TASKLEDGER_HARNESS") or "unknown",
        kind="unknown",
        session_id=os.getenv("TASKLEDGER_SESSION_ID"),
        working_directory=os.getcwd(),
    )


def append_task_event(
    workspace_root: Path,
    task_id: str,
    event_name: str,
    data: dict[str, object],
) -> str | None:
    from taskledger.services.event_logging import event_logging_enabled

    if not event_logging_enabled(workspace_root):
        return None

    paths = resolve_v2_paths(workspace_root)
    event_task_id = task_id
    event_task_uuid: str | None = None
    if task_id != "*":
        from taskledger.errors import LaunchError
        from taskledger.storage.task_identity import task_identity_for_ref

        try:
            identity = task_identity_for_ref(paths, task_id)
        except LaunchError:
            pass
        else:
            event_task_id = identity.task_id
            event_task_uuid = str(identity.task_uuid)
    timestamp = utc_now_iso()
    event_id = next_event_id(paths.events_dir, timestamp)
    append_event(
        paths.events_dir,
        TaskEvent(
            ts=timestamp,
            event=event_name,
            task_id=event_task_id,
            actor=default_actor(),
            harness=default_harness(),
            event_id=event_id,
            data=data,
            task_uuid=event_task_uuid,
        ),
    )
    return event_id


def write_broken_lock_audit(paths: V2Paths, task_id: str, lock: TaskLock) -> Path:
    timestamp = lock.broken_at or utc_now_iso()
    filename = timestamp.replace(":", "").replace("-", "").replace("+00:00", "Z")
    path = task_audit_dir(paths, task_id) / f"broken-lock-{filename}.yaml"
    write_yaml_object(path, lock.to_dict())
    return path
