from __future__ import annotations

import errno
import json
import threading
import time
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from taskledger.domain.models import (
    AcceptanceCriterion,
    ActiveTaskState,
    ActorRef,
    CodeChangeRecord,
    PlanRecord,
    QuestionRecord,
    TaskEvent,
    TaskLock,
    TaskRecord,
    TaskRunRecord,
    TaskTodo,
    TodoCollection,
    ValidationCheck,
)
from taskledger.errors import LaunchError
from taskledger.services.web_dashboard import (
    DashboardServerConfig,
    DashboardServerHandle,
    _DashboardRequestHandler,
    launch_dashboard_server,
    render_index_html,
)
from taskledger.storage.events import append_event
from taskledger.storage.task_store import (
    ensure_v2_layout,
    resolve_v2_paths,
    save_active_task_state,
    save_change,
    save_lock,
    save_plan,
    save_question,
    save_run,
    save_task,
    save_todos,
)


def _skip_if_socket_forbidden(exc: OSError) -> None:
    if exc.errno in {errno.EPERM, errno.EACCES}:
        pytest.skip("Socket bind not permitted in this test environment.")
    raise exc


def _build_workspace(tmp_path: Path) -> None:
    ensure_v2_layout(tmp_path)
    task = TaskRecord(
        id="task-0001",
        slug="serve-task",
        title="Serve dashboard",
        body="Read-only dashboard task.",
        status_stage="validating",
        description_summary="Exercise the serve dashboard payload.",
        latest_plan_version=2,
        accepted_plan_version=2,
        latest_implementation_run="run-0001",
        latest_validation_run="run-0002",
    )
    save_task(tmp_path, task)
    save_active_task_state(tmp_path, ActiveTaskState(task_id=task.id))

    save_plan(
        tmp_path,
        PlanRecord(
            task_id=task.id,
            plan_version=1,
            status="superseded",
            goal="Initial serve spike.",
            body="Initial plan body.",
            criteria=(AcceptanceCriterion(id="ac-0001", text="Serve exists."),),
            todos=(TaskTodo(id="todo-0001", text="Draft the server."),),
        ),
    )
    save_plan(
        tmp_path,
        PlanRecord(
            task_id=task.id,
            plan_version=2,
            status="accepted",
            goal="Ship the read-only dashboard.",
            body="Accepted plan body.",
            criteria=(
                AcceptanceCriterion(id="ac-0001", text="Serve exists."),
                AcceptanceCriterion(id="ac-0002", text="Dashboard is read-only."),
            ),
            todos=(
                TaskTodo(id="todo-0001", text="Add the server.", mandatory=True),
                TaskTodo(id="todo-0002", text="Add docs.", mandatory=False),
            ),
            test_commands=("python -m pytest tests/test_serve_dashboard.py -q",),
            expected_outputs=("Serve dashboard tests pass.",),
        ),
    )

    save_question(
        tmp_path,
        QuestionRecord(
            id="q-0001",
            task_id=task.id,
            question="Should localhost-only binding be enforced?",
            status="answered",
            answer="Yes.",
            required_for_plan=True,
        ),
    )
    save_question(
        tmp_path,
        QuestionRecord(
            id="q-0002",
            task_id=task.id,
            question="Should actions be enabled?",
            status="open",
            required_for_plan=False,
        ),
    )

    save_todos(
        tmp_path,
        TodoCollection(
            task_id=task.id,
            todos=(
                TaskTodo(
                    id="todo-0001",
                    text="Add the server.",
                    done=True,
                    mandatory=True,
                    status="done",
                ),
                TaskTodo(
                    id="todo-0002",
                    text="Add docs.",
                    done=False,
                    mandatory=False,
                    status="open",
                ),
            ),
        ),
    )

    save_run(
        tmp_path,
        TaskRunRecord(
            run_id="run-0001",
            task_id=task.id,
            run_type="implementation",
            status="finished",
            summary="Implemented the read-only dashboard.",
            based_on_plan_version=2,
        ),
    )
    save_run(
        tmp_path,
        TaskRunRecord(
            run_id="run-0002",
            task_id=task.id,
            run_type="validation",
            status="running",
            summary="Checking the dashboard endpoints.",
            based_on_plan_version=2,
            based_on_implementation_run="run-0001",
            checks=(
                ValidationCheck(
                    id="check-0001",
                    criterion_id="ac-0001",
                    name="Serve command works.",
                    status="pass",
                    evidence=("python -m pytest tests/test_serve_dashboard.py -q",),
                ),
            ),
        ),
    )

    save_change(
        tmp_path,
        CodeChangeRecord(
            change_id="change-0001",
            task_id=task.id,
            implementation_run="run-0001",
            timestamp="2026-04-28T08:00:00Z",
            kind="edit",
            path="taskledger/services/web_dashboard.py",
            summary="Added read-only HTTP dashboard server.",
        ),
    )

    save_lock(
        tmp_path,
        task.id,
        TaskLock(
            lock_id="lock-0001",
            task_id=task.id,
            stage="validating",
            run_id="run-0002",
            created_at="2026-04-28T08:30:00Z",
            expires_at=None,
            reason="Validation in progress.",
            holder=ActorRef(actor_name="copilot", role="validator"),
        ),
    )

    paths = resolve_v2_paths(tmp_path)
    append_event(
        paths.events_dir,
        TaskEvent(
            event_id="evt-20260428T080000Z-000001",
            ts="2026-04-28T08:00:00Z",
            event="task.created",
            task_id=task.id,
            actor=ActorRef(actor_name="copilot"),
        ),
    )
    append_event(
        paths.events_dir,
        TaskEvent(
            event_id="evt-20260428T081000Z-000002",
            ts="2026-04-28T08:10:00Z",
            event="plan.approved",
            task_id=task.id,
            actor=ActorRef(actor_name="user", actor_type="user"),
        ),
    )
    append_event(
        paths.events_dir,
        TaskEvent(
            event_id="evt-20260428T082000Z-000003",
            ts="2026-04-28T08:20:00Z",
            event="validate.started",
            task_id=task.id,
            actor=ActorRef(actor_name="copilot", role="validator"),
        ),
    )


@contextmanager
def _running_server(
    workspace_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    task_ref: str | None = None,
) -> DashboardServerHandle:
    try:
        handle = launch_dashboard_server(
            DashboardServerConfig(
                workspace_root=workspace_root,
                host=host,
                port=port,
                task_ref=task_ref,
            )
        )
    except OSError as exc:
        _skip_if_socket_forbidden(exc)
        raise
    thread = threading.Thread(target=handle.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        yield handle
    finally:
        handle.close()
        thread.join(timeout=1)


def _request(
    handle: DashboardServerHandle,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
):
    return Request(
        f"{handle.url.rstrip('/')}{path}",
        method=method,
        headers=headers or {},
    )


def _load_json(handle: DashboardServerHandle, path: str) -> dict[str, object]:
    with urlopen(_request(handle, path), timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _load_error(
    handle: DashboardServerHandle,
    path: str,
    *,
    method: str = "GET",
) -> tuple[int, dict[str, object]]:
    try:
        with urlopen(_request(handle, path, method=method), timeout=5):
            raise AssertionError("Expected HTTP error response.")
    except HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        return exc.code, payload


def test_render_index_html_escapes_task_ref_and_refresh_interval() -> None:
    html = render_index_html(
        refresh_ms=750,
        task_ref='task-0001</script><img src=x onerror="boom">',
    )
    assert "const refreshMs = 750;" in html
    assert "\\u003c/script\\u003e\\u003cimg" in html
    assert '</script><img src=x onerror="boom">' not in html


def test_dashboard_refresh_loop_does_not_use_set_interval() -> None:
    html = render_index_html(refresh_ms=1000, task_ref=None)

    assert "setInterval" not in html
    assert "setTimeout" in html
    assert "refreshInFlight" in html
    assert "Promise.allSettled" in html
    assert "Math.max(refreshMs * 5, 5000)" in html
    assert "Math.max(refreshMs * 15, 15000)" in html
    assert "endpointOrFallback" in html


def test_dashboard_html_has_human_layout_sections() -> None:
    html = render_index_html(refresh_ms=1000, task_ref=None)

    assert "active-task-hero" in html
    assert "next-action-card" in html
    assert "Do next" in html
    assert "metric-grid" in html
    assert "task-search" in html
    assert "raw-payload" in html
    assert "command-row" in html


def test_dashboard_preserves_details_state_helpers() -> None:
    html = render_index_html(refresh_ms=1000, task_ref=None)

    assert "openDetailsKeys" in html
    assert "rememberDetailsState" in html
    assert "bindDetailsState" in html
    assert "data-detail-key" in html


def test_dashboard_refresh_tracks_changed_endpoints() -> None:
    html = render_index_html(refresh_ms=1000, task_ref=None)

    assert "const changed = new Set();" in html
    assert "return { payload: state.payload, changed: false }" in html
    assert "return result.changed;" in html
    assert 'if (changed.has("tasks")) renderTasks();' in html
    assert (
        'if (changed.has("project") || changed.has("dashboard")'
        ' || changed.has("events"))' in html
    )
    assert "renderSections();" in html


def test_dashboard_has_pause_and_manual_refresh_controls() -> None:
    html = render_index_html(refresh_ms=1000, task_ref=None)

    assert "pollingPaused" in html
    assert "Pause updates" in html
    assert "Refresh now" in html
    assert "Review status" in html


def test_dashboard_prioritizes_human_review_surface() -> None:
    html = render_index_html(refresh_ms=1000, task_ref=None)

    assert "Current summary" in html
    assert "Recent events" in html
    assert "Debug / raw payload" in html
    assert "Recent activity stays visible" in html


def test_dashboard_html_uses_compact_do_next_copy() -> None:
    html = render_index_html(refresh_ms=1000, task_ref=None)

    assert "When done" in html
    assert "Todo progress" in html
    assert "Raw next action payload" not in html


def test_dashboard_html_does_not_emit_broken_todo_renderer_tokens() -> None:
    html = render_index_html(refresh_ms=1000, task_ref=None)

    assert "const todoCards = items.map((todo) => {" in html
    assert "}))]));" not in html


def test_dashboard_html_has_accessible_landmarks() -> None:
    html = render_index_html(refresh_ms=1000, task_ref=None)

    assert "<header" in html
    assert 'aria-label="Tasks"' in html
    assert "aria-current" in html
    assert "progressbar" in html


def test_dashboard_assets_load_from_package_resources() -> None:
    css = (
        files("taskledger.web_assets")
        .joinpath("dashboard.css")
        .read_text(encoding="utf-8")
    )
    script = (
        files("taskledger.web_assets")
        .joinpath("dashboard.js")
        .read_text(encoding="utf-8")
    )

    assert ".dashboard-layout" in css
    assert "const refreshMs = __REFRESH_MS__;" in script
    assert "function renderSections()" in script


def test_launch_dashboard_server_defaults_to_loopback_and_reports_bound_port(
    tmp_path: Path,
) -> None:
    _build_workspace(tmp_path)
    try:
        handle = launch_dashboard_server(
            DashboardServerConfig(workspace_root=tmp_path, port=0)
        )
    except OSError as exc:
        _skip_if_socket_forbidden(exc)
        raise
    try:
        assert handle.host == "127.0.0.1"
        assert handle.port > 0
        assert handle.url.startswith("http://127.0.0.1:")
    finally:
        handle.close()


def test_launch_dashboard_server_rejects_non_loopback_hosts(tmp_path: Path) -> None:
    _build_workspace(tmp_path)
    with pytest.raises(LaunchError, match="localhost"):
        launch_dashboard_server(
            DashboardServerConfig(workspace_root=tmp_path, host="0.0.0.0")
        )


def test_dashboard_api_routes_return_expected_payloads(tmp_path: Path) -> None:
    _build_workspace(tmp_path)
    with _running_server(tmp_path) as handle:
        root = urlopen(_request(handle, "/"), timeout=5).read().decode("utf-8")
        project_payload = _load_json(handle, "/api/project")
        tasks_payload = _load_json(handle, "/api/tasks")
        dash_payload = _load_json(handle, "/api/dashboard?task=active")
        events_payload = _load_json(handle, "/api/events?task=active&limit=2")

    assert "Taskledger dashboard" in root
    assert project_payload["kind"] == "serve_project"
    assert project_payload["health"] == "not_checked"
    assert tasks_payload["kind"] == "tasks"
    assert tasks_payload["tasks"][0]["id"] == "task-0001"
    assert (
        tasks_payload["tasks"][0]["description_summary"]
        == "Exercise the serve dashboard payload."
    )
    assert tasks_payload["tasks"][0]["labels"] == []
    assert dash_payload["kind"] == "dashboard"
    assert dash_payload["task"]["id"] == "task-0001"
    assert dash_payload["task"]["active_stage"] == "validation"
    assert len(dash_payload["plans"]) == 2
    assert dash_payload["questions"]["items"][0]["id"] == "q-0001"
    assert dash_payload["validation"]["kind"] == "validation_status"
    assert dash_payload["lock"]["stage"] == "validating"
    assert dash_payload["revision"]
    assert "events" not in dash_payload
    assert len(events_payload["items"]) == 2
    assert events_payload["items"][-1]["event"] == "validate.started"


def test_dashboard_api_returns_404_for_unknown_task(tmp_path: Path) -> None:
    _build_workspace(tmp_path)
    with _running_server(tmp_path) as handle:
        status, payload = _load_error(handle, "/api/dashboard?task=missing-task")

    assert status == 404
    assert payload["ok"] is False
    assert payload["error"]["type"] == "NotFound"


def test_dashboard_rejects_non_get_requests(tmp_path: Path) -> None:
    _build_workspace(tmp_path)
    with _running_server(tmp_path) as handle:
        status, payload = _load_error(handle, "/api/dashboard", method="POST")

    assert status == 405
    assert payload["ok"] is False
    assert payload["error"]["type"] == "MethodNotAllowed"


def test_serve_tasks_route_does_not_call_full_project_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_workspace(tmp_path)

    def fail(*args, **kwargs):
        raise AssertionError("full project_status must not be used by /api/tasks")

    monkeypatch.setattr("taskledger.api.project.project_status", fail)

    with _running_server(tmp_path) as handle:
        payload = _load_json(handle, "/api/tasks")

    assert payload["kind"] == "tasks"


def test_serve_project_route_does_not_call_full_project_status_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_workspace(tmp_path)

    def fail(*args, **kwargs):
        raise AssertionError(
            "full project_status_summary must not be used by /api/project"
        )

    monkeypatch.setattr("taskledger.api.project.project_status_summary", fail)

    with _running_server(tmp_path) as handle:
        payload = _load_json(handle, "/api/project")

    assert payload["kind"] == "serve_project"


def test_default_serve_polling_routes_do_not_call_inspect_v2_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_workspace(tmp_path)

    def fail(*args, **kwargs):
        raise AssertionError("default serve polling routes must not run doctor")

    monkeypatch.setattr("taskledger.services.doctor.inspect_v2_project", fail)

    with _running_server(tmp_path) as handle:
        _load_json(handle, "/api/project")
        _load_json(handle, "/api/tasks")
        _load_json(handle, "/api/dashboard?task=active")
        _load_json(handle, "/api/events?task=active&limit=2")


def test_events_route_uses_recent_event_tail_not_full_event_load(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_workspace(tmp_path)

    def fail(*args, **kwargs):
        raise AssertionError("serve /api/events must not call full load_events")

    monkeypatch.setattr("taskledger.storage.events.load_events", fail)

    with _running_server(tmp_path) as handle:
        payload = _load_json(handle, "/api/events?task=active&limit=2")

    assert payload["kind"] == "events"
    assert len(payload["items"]) == 2


def test_dashboard_api_does_not_duplicate_events(tmp_path: Path) -> None:
    _build_workspace(tmp_path)

    with _running_server(tmp_path) as handle:
        payload = _load_json(handle, "/api/dashboard?task=active")

    assert "events" not in payload


def test_dashboard_endpoint_supports_etag_not_modified(tmp_path: Path) -> None:
    _build_workspace(tmp_path)

    with _running_server(tmp_path) as handle:
        with urlopen(
            _request(handle, "/api/dashboard?task=active"),
            timeout=5,
        ) as first:
            etag = first.headers["ETag"]
            first.read()
        with pytest.raises(HTTPError) as exc_info:
            urlopen(
                _request(
                    handle,
                    "/api/dashboard?task=active",
                    headers={"If-None-Match": etag},
                ),
                timeout=5,
            )

    assert exc_info.value.code == 304


@pytest.mark.parametrize("fail_on", ["headers", "write"])
def test_send_text_ignores_client_disconnects(fail_on: str) -> None:
    class _Writer:
        def write(self, data: bytes) -> None:
            if fail_on == "write":
                raise BrokenPipeError()

    def _end_headers() -> None:
        if fail_on == "headers":
            raise BrokenPipeError()

    handler = _DashboardRequestHandler.__new__(_DashboardRequestHandler)
    handler.wfile = _Writer()
    handler.send_response = lambda *args, **kwargs: None
    handler.send_header = lambda *args, **kwargs: None
    handler.end_headers = _end_headers

    handler._send_text(200, "ok", content_type="text/plain")
