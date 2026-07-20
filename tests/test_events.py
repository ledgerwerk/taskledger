from __future__ import annotations

import json
from pathlib import Path

import pytest

from taskledger.domain.models import ActorRef, TaskEvent
from taskledger.errors import LaunchError
from taskledger.storage.events import append_event, load_events, load_recent_events


# specmason: req=REQ-0020 ac=AC-0283
def test_load_events_sorts_by_timestamp_and_event_id(tmp_path: Path) -> None:
    events_dir = tmp_path / "events"
    actor = ActorRef(actor_type="agent", actor_name="taskledger")
    append_event(
        events_dir,
        TaskEvent(
            ts="2026-04-24T08:45:00+00:00",
            event="plan.proposed",
            task_id="task-1",
            actor=actor,
            event_id="evt-20260424T084500Z-000002",
        ),
    )
    append_event(
        events_dir,
        TaskEvent(
            ts="2026-04-24T08:44:00+00:00",
            event="plan.started",
            task_id="task-1",
            actor=actor,
            event_id="evt-20260424T084400Z-000001",
        ),
    )
    append_event(
        events_dir,
        TaskEvent(
            ts="2026-04-24T08:45:00+00:00",
            event="plan.approved",
            task_id="task-1",
            actor=actor,
            event_id="evt-20260424T084500Z-000001",
        ),
    )

    events = load_events(events_dir)

    assert [event.event_id for event in events] == [
        "evt-20260424T084400Z-000001",
        "evt-20260424T084500Z-000001",
        "evt-20260424T084500Z-000002",
    ]


# specmason: req=REQ-0020 ac=AC-0282
def test_load_events_rejects_duplicate_event_ids(tmp_path: Path) -> None:
    events_dir = tmp_path / "events"
    events_dir.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "object_type": "event",
        "file_version": "v2",
        "event_id": "evt-20260424T084500Z-000001",
        "ts": "2026-04-24T08:45:00+00:00",
        "event": "plan.proposed",
        "task_id": "task-1",
        "actor": {"actor_type": "agent", "actor_name": "taskledger"},
        "data": {},
    }
    log_path = events_dir / "2026-04-24.ndjson"
    log_path.write_text(
        json.dumps(payload) + "\n" + json.dumps(payload) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(LaunchError, match="Duplicate event id"):
        load_events(events_dir)


# specmason: req=REQ-0020 ac=AC-0284
def test_load_recent_events_returns_chronological_task_tail(tmp_path: Path) -> None:
    events_dir = tmp_path / "events"
    actor = ActorRef(actor_type="agent", actor_name="taskledger")
    append_event(
        events_dir,
        TaskEvent(
            ts="2026-04-24T08:44:00+00:00",
            event="plan.started",
            task_id="task-1",
            actor=actor,
            event_id="evt-20260424T084400Z-000001",
        ),
    )
    append_event(
        events_dir,
        TaskEvent(
            ts="2026-04-24T08:45:00+00:00",
            event="plan.approved",
            task_id="task-2",
            actor=actor,
            event_id="evt-20260424T084500Z-000002",
        ),
    )
    append_event(
        events_dir,
        TaskEvent(
            ts="2026-04-24T08:46:00+00:00",
            event="implement.started",
            task_id="task-1",
            actor=actor,
            event_id="evt-20260424T084600Z-000003",
        ),
    )
    append_event(
        events_dir,
        TaskEvent(
            ts="2026-04-24T08:47:00+00:00",
            event="implement.finished",
            task_id="task-1",
            actor=actor,
            event_id="evt-20260424T084700Z-000004",
        ),
    )

    events = load_recent_events(events_dir, task_id="task-1", limit=2)

    assert [event.event_id for event in events] == [
        "evt-20260424T084600Z-000003",
        "evt-20260424T084700Z-000004",
    ]
