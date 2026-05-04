from __future__ import annotations

# ruff: noqa: E501
import hashlib
import json
import socket
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from textwrap import dedent
from urllib.parse import parse_qs, urlparse

from taskledger.errors import LaunchError
from taskledger.services.serve_read_model import (
    serve_dashboard_snapshot,
    serve_project_summary,
    serve_task_events,
    serve_task_summaries,
)
from taskledger.storage.task_store import (
    resolve_task_or_active,
    resolve_v2_paths,
    task_dir,
)


@dataclass(slots=True, frozen=True)
class DashboardServerConfig:
    workspace_root: Path
    host: str = "127.0.0.1"
    port: int = 8765
    task_ref: str | None = None
    refresh_ms: int = 1000
    open_browser: bool = False


@dataclass(slots=True)
class CachedResponse:
    revision: str
    body: bytes
    content_type: str


class _DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    workspace_root: Path
    default_task_ref: str | None
    refresh_ms: int
    cache: dict[str, CachedResponse]


@dataclass(slots=True)
class DashboardServerHandle:
    server: _DashboardHTTPServer
    host: str
    port: int
    url: str
    _serving: bool = False

    def serve_forever(self) -> None:
        self._serving = True
        try:
            self.server.serve_forever()
        finally:
            self._serving = False

    def close(self) -> None:
        if self._serving:
            self.server.shutdown()
        self.server.server_close()


def render_index_html(*, refresh_ms: int, task_ref: str | None) -> str:
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            "  <title>Taskledger dashboard</title>",
            _render_dashboard_css(),
            "</head>",
            _render_dashboard_body(),
            _render_dashboard_script(refresh_ms, task_ref),
            "</html>",
        ]
    )


def _load_dashboard_asset(filename: str) -> str:
    return files("taskledger.web_assets").joinpath(filename).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _dashboard_css_text() -> str:
    return _load_dashboard_asset("dashboard.css")


@lru_cache(maxsize=1)
def _dashboard_script_template() -> str:
    return _load_dashboard_asset("dashboard.js")


def _render_dashboard_css() -> str:
    return "<style>\n" + _dashboard_css_text().strip() + "\n</style>"


def _render_dashboard_body() -> str:
    return dedent(
        """\
        <body>
          <header class="app-header">
            <div>
              <p class="eyebrow">Taskledger</p>
              <h1>Taskledger dashboard</h1>
              <p id="status-headline" class="app-subtitle">Waiting for first refresh.</p>
              <p id="status-detail" class="status-detail">The dashboard will load the selected task automatically.</p>
            </div>
            <div class="header-tools">
              <div class="header-meta">
                <div class="meta-card">
                  <span class="meta-label">Selected task</span>
                  <strong id="selected-task-label">active</strong>
                </div>
                <div class="meta-card">
                  <span class="meta-label">Last refresh</span>
                  <strong id="last-updated-label">never</strong>
                </div>
                <div class="meta-card">
                  <span class="meta-label">Review status</span>
                  <strong id="live-status-label" class="status-live">Live</strong>
                </div>
              </div>
              <div class="header-controls">
                <button id="toggle-polling-button" class="action-button" type="button">Pause updates</button>
                <button id="refresh-now-button" class="action-button action-button-primary" type="button">Refresh now</button>
              </div>
            </div>
          </header>
          <div class="dashboard-layout">
            <aside aria-label="Tasks">
              <div class="sidebar-sticky">
                <section class="card muted-card">
                  <div class="search-stack">
                    <label for="task-search">Search tasks</label>
                    <input
                      id="task-search"
                      class="task-search"
                      type="search"
                      placeholder="Filter by title, task id, or slug"
                    >
                    <nav id="task-filters" class="filter-row" aria-label="Task filters"></nav>
                  </div>
                </section>
                <div id="tasks" class="task-list"></div>
              </div>
            </aside>
            <main class="main-column">
              <div id="hero-slot" class="hero-grid"></div>
              <section id="metric-grid" class="metric-grid" aria-label="Progress overview"></section>
              <div id="sections" class="section-stack"></div>
            </main>
            <aside class="right-rail" aria-label="Current work">
              <div id="rail-content" class="rail-sticky"></div>
            </aside>
          </div>
        """
    ).strip()


def _render_dashboard_script(refresh_ms: int, task_ref: str | None) -> str:
    script = (
        _dashboard_script_template()
        .replace("__REFRESH_MS__", json.dumps(refresh_ms))
        .replace("__DEFAULT_TASK_REF__", _safe_script_literal(task_ref))
        .strip()
    )
    return "<script>\n" + script + "\n</script>"


def launch_dashboard_server(config: DashboardServerConfig) -> DashboardServerHandle:
    _validate_host(config.host)
    if config.port < 0 or config.port > 65535:
        raise LaunchError("taskledger serve requires --port between 0 and 65535.")
    if config.refresh_ms <= 0:
        raise LaunchError("taskledger serve requires --refresh-ms greater than 0.")
    server = _create_server(config)
    host = config.host
    port = int(server.server_address[1])
    url = _server_url(host, port)
    handle = DashboardServerHandle(server=server, host=host, port=port, url=url)
    if config.open_browser:
        webbrowser.open(url)
    return handle


def serve_dashboard(config: DashboardServerConfig) -> None:
    handle = launch_dashboard_server(config)
    try:
        handle.serve_forever()
    finally:
        handle.close()


def _validate_host(host: str) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise LaunchError("taskledger serve only binds to localhost in the MVP.")


def _create_server(config: DashboardServerConfig) -> _DashboardHTTPServer:
    address_family = socket.AF_INET6 if ":" in config.host else socket.AF_INET

    class DashboardHTTPServer(_DashboardHTTPServer):
        pass

    DashboardHTTPServer.address_family = address_family
    server = DashboardHTTPServer((config.host, config.port), _DashboardRequestHandler)
    server.workspace_root = config.workspace_root
    server.default_task_ref = config.task_ref
    server.refresh_ms = config.refresh_ms
    server.cache = {}
    return server


class _DashboardRequestHandler(BaseHTTPRequestHandler):
    server: _DashboardHTTPServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                self._send_text(
                    200,
                    render_index_html(
                        refresh_ms=self.server.refresh_ms,
                        task_ref=self.server.default_task_ref,
                    ),
                    content_type="text/html; charset=utf-8",
                )
                return
            if parsed.path == "/api/project":
                revision = _storage_revision_for_project(self.server.workspace_root)
                self._send_cached_json(
                    200,
                    revision,
                    lambda: serve_project_summary(self.server.workspace_root),
                )
                return
            if parsed.path == "/api/tasks":
                revision = _storage_revision_for_tasks(self.server.workspace_root)
                self._send_cached_json(
                    200,
                    revision,
                    lambda: serve_task_summaries(self.server.workspace_root),
                )
                return
            if parsed.path == "/api/dashboard":
                task_ref = _task_ref_from_query(query, self.server.default_task_ref)
                revision = _storage_revision_for_dashboard(
                    self.server.workspace_root, task_ref
                )
                self._send_cached_json(
                    200,
                    revision,
                    lambda: serve_dashboard_snapshot(
                        self.server.workspace_root,
                        ref=task_ref,
                    ),
                )
                return
            if parsed.path == "/api/events":
                task_ref = _task_ref_from_query(query, self.server.default_task_ref)
                revision = _storage_revision_for_events(
                    self.server.workspace_root, task_ref
                )
                self._send_cached_json(
                    200,
                    revision,
                    lambda: serve_task_events(
                        self.server.workspace_root,
                        ref=task_ref,
                        limit=_limit_from_query(query),
                    ),
                )
                return
            self._send_api_error(404, "NotFound", f"Unknown path: {parsed.path}")
        except LaunchError as exc:
            error_status, error_type = _status_for_launch_error(exc)
            self._send_api_error(error_status, error_type, str(exc))
        except ValueError as exc:
            self._send_api_error(400, "BadRequest", str(exc))
        except Exception as exc:  # noqa: BLE001
            self._send_api_error(500, "InternalError", str(exc))

    def do_POST(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_HEAD(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _method_not_allowed(self) -> None:
        self._send_api_error(405, "MethodNotAllowed", "Only GET requests are allowed.")

    def _send_text(self, status: int, text: str, *, content_type: str) -> None:
        body = text.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except _CLIENT_DISCONNECT_ERRORS:
            return

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        self._send_text(
            status,
            json.dumps(payload, sort_keys=True) + "\n",
            content_type="application/json",
        )

    def _send_cached_json(
        self,
        status: int,
        revision: str,
        payload_factory: Callable[[], dict[str, object]],
    ) -> None:
        if self.headers.get("If-None-Match") == revision:
            try:
                self.send_response(304)
                self.send_header("ETag", revision)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
            except _CLIENT_DISCONNECT_ERRORS:
                return
            return

        cache_key = f"{self.path}:{revision}"
        cached = self.server.cache.get(cache_key)
        if cached is None:
            payload = payload_factory()
            payload["revision"] = revision
            cached = CachedResponse(
                revision=revision,
                body=(json.dumps(payload, sort_keys=True).encode("utf-8") + b"\n"),
                content_type="application/json",
            )
            if len(self.server.cache) > 128:
                self.server.cache.clear()
            self.server.cache[cache_key] = cached

        try:
            self.send_response(status)
            self.send_header("Content-Type", cached.content_type)
            self.send_header("Content-Length", str(len(cached.body)))
            self.send_header("ETag", revision)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(cached.body)
        except _CLIENT_DISCONNECT_ERRORS:
            return

    def _send_api_error(self, status: int, error_type: str, message: str) -> None:
        self._send_json(
            status,
            {
                "ok": False,
                "error": {
                    "type": error_type,
                    "message": message,
                },
            },
        )


def _task_ref_from_query(
    query: dict[str, list[str]],
    default_task_ref: str | None,
) -> str | None:
    raw = _first_query_value(query, "task")
    if raw is None or raw == "active":
        return default_task_ref
    return raw


def _limit_from_query(query: dict[str, list[str]]) -> int:
    raw = _first_query_value(query, "limit")
    if raw is None:
        return 50
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ValueError("Invalid limit value.") from exc
    if limit <= 0:
        raise ValueError("limit must be greater than 0.")
    return limit


def _first_query_value(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name, [])
    if not values:
        return None
    return values[0].strip() or None


def _storage_revision_for_project(workspace_root: Path) -> str:
    paths = resolve_v2_paths(workspace_root)
    return _revision_for_paths(
        paths.project_dir,
        [paths.active_task_path, *sorted(paths.tasks_dir.glob("task-*/task.md"))],
    )


def _storage_revision_for_tasks(workspace_root: Path) -> str:
    paths = resolve_v2_paths(workspace_root)
    return _revision_for_paths(
        paths.project_dir,
        [
            *sorted(paths.tasks_dir.glob("task-*/task.md")),
            *sorted(paths.tasks_dir.glob("task-*/lock.yaml")),
        ],
    )


def _storage_revision_for_dashboard(
    workspace_root: Path,
    task_ref: str | None,
) -> str:
    task = resolve_task_or_active(workspace_root, task_ref)
    paths = resolve_v2_paths(workspace_root)
    bundle = task_dir(paths, task.id)
    return _revision_for_paths(
        paths.project_dir,
        [bundle / "lock.yaml", *sorted(bundle.rglob("*.md"))],
    )


def _storage_revision_for_events(
    workspace_root: Path,
    task_ref: str | None,
) -> str:
    resolve_task_or_active(workspace_root, task_ref)
    paths = resolve_v2_paths(workspace_root)
    return _revision_for_paths(
        paths.project_dir,
        sorted(paths.events_dir.glob("*.ndjson")),
    )


def _revision_for_paths(project_dir: Path, paths: list[Path]) -> str:
    parts: list[str] = []
    seen: set[Path] = set()
    for path in sorted(paths, key=lambda item: str(item)):
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            stat = path.stat()
            parts.append(
                f"{_relative_path(project_dir, path)}:{stat.st_mtime_ns}:{stat.st_size}"
            )
        else:
            parts.append(f"{_relative_path(project_dir, path)}:missing")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _relative_path(project_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(project_dir))
    except ValueError:
        return str(path)


def _safe_script_literal(value: str | None) -> str:
    encoded = json.dumps(value)
    return (
        encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )


def _server_url(host: str, port: int) -> str:
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/"


def _status_for_launch_error(exc: LaunchError) -> tuple[int, str]:
    message = str(exc)
    if "Task not found:" in message or "Active task" in message:
        return 404, "NotFound"
    return 400, "BadRequest"


_CLIENT_DISCONNECT_ERRORS = (
    BrokenPipeError,
    ConnectionAbortedError,
    ConnectionResetError,
)


__all__ = [
    "DashboardServerConfig",
    "DashboardServerHandle",
    "launch_dashboard_server",
    "render_index_html",
    "serve_dashboard",
]
