"""Textual application entrypoint for ``taskledger tui``.

This module imports Textual. It is loaded lazily by the ``tui`` CLI command,
so ``taskledger --help`` and other commands never trigger the textual import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import (
    Footer,
    Header,
    Input,
    ListItem,
    ListView,
    Static,
    TabbedContent,
    TabPane,
)

from taskledger.errors import LaunchError
from taskledger.services.tui_read_model import load_tui_snapshot
from taskledger.tui import widgets as tui_widgets

# Stage filter shortcuts: key -> (label, statuses to keep). Empty tuple means
# "all". A stage filter value of None means "no filtering applied".
_STAGE_FILTERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "a": ("all", ()),
    "n": ("plan_review", ("plan_review",)),
    "p": ("planning", ("planning",)),
    "i": ("implementing", ("implementing",)),
    "m": ("implemented", ("implemented",)),
    "v": ("validating", ("validating",)),
    "f": ("failed_validation", ("failed_validation",)),
    "d": ("done", ("done",)),
    "c": ("cancelled", ("cancelled",)),
}

# Width (columns) below which ``--layout auto`` switches to compact mode.
_COMPACT_WIDTH = 88
_VALID_LAYOUTS = {"auto", "wide", "compact"}
_COMPACT_VIEWS = {"list", "detail"}

# Shortened stage labels for compact task list rows. Unknown stages fall back
# to the first 5 characters of the raw status_stage.
_STAGE_LABELS_SHORT: dict[str, str] = {
    "plan_review": "plan",
    "planning": "plan",
    "implementing": "impl",
    "implemented": "impld",
    "validating": "val",
    "failed_validation": "fail",
    "done": "done",
    "cancelled": "cncl",
    "draft": "draft",
    "approved": "appr",
}


class CommandCopyModal(Static):
    """Simple modal-style widget that displays the next-action commands.

    Textual modal screens are heavier than we need for the MVP.
    This widget is pushed onto a normal Static overlay region
    by :meth:`TaskledgerTui.action_copy_command`.
    """

    DEFAULT_CSS = """
    CommandCopyModal {
        layer: overlay;
        width: 80;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        border: thick $primary;
        background: $panel;
        color: $text;
    }
    """

    def __init__(self, commands: list[str], primary: str | None) -> None:
        super().__init__()
        self._commands = commands
        self._primary = primary

    def render(self) -> str:
        lines: list[str] = ["Command palette  — press Esc or c to dismiss", ""]
        if self._primary:
            lines.append("Primary:")
            lines.append(f"  $ {self._primary}")
            lines.append("")
        if self._commands:
            lines.append("All commands:")
            for command in self._commands:
                lines.append(f"  $ {command}")
        else:
            lines.append("No commands available for the current selection.")
        lines.append("")
        lines.append(
            "Copy with your terminal's selection shortcut or by selecting the line."
        )
        return "\n".join(lines)


class HelpOverlay(Static):
    DEFAULT_CSS = """
    HelpOverlay {
        layer: overlay;
        width: 80;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        border: thick $primary;
        background: $panel;
        color: $text;
    }
    """

    def render(self) -> str:
        lines = [
            "taskledger tui — read-only navigator",
            "",
            "Key bindings:",
            "  q          quit",
            "  r / F5     refresh snapshot",
            "  /          focus search/filter input",
            "  Enter      open selected task",
            "  b          compact mode: back to task list",
            "  l          compact mode: toggle list/detail",
            "  Tab        cycle focus / tabs",
            "  1..9       jump to a tab",
            "  c          show command copy palette",
            "  o          write a static HTML report for the selected task",
            "  a n p i m v f d c   stage filters",
            "  t          toggle archived tasks",
            "  ?          this help",
            "",
            "This TUI is read-only. Mutating actions still require the CLI.",
        ]
        return "\n".join(lines)


def _safe_query_one(app: App[None], selector: str, widget_type: type) -> Any:
    """Return the queried widget or None if it does not (yet) exist.

    Keeps the renderer paths free of broad ``except Exception`` blocks.
    """

    try:
        return app.query_one(selector, widget_type)
    except NoMatches:
        return None


class TaskledgerTui(App[None]):
    """Read-only Textual navigator over the taskledger read models."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #main { height: 1fr; }
    #tasks-pane { width: 34; height: 1fr; border-right: solid $primary; }
    #detail-pane { width: 2fr; height: 1fr; }
    #filter-input { dock: top; margin: 0 0 1 0; }
    #tabs { height: 1fr; }
    .tab-scroll { height: 1fr; }
    #status-bar { dock: bottom; height: 1; background: $boost; color: $text; }
    ListView > ListItem { padding: 0 1; }

    /* compact: full-width single-pane mode */
    Screen.-compact #main { layout: vertical; }
    Screen.-compact #tasks-pane { width: 1fr; height: 1fr; border-right: none; }
    Screen.-compact #detail-pane { width: 1fr; height: 1fr; }
    Screen.-compact.-list #detail-pane { display: none; }
    Screen.-compact.-detail #tasks-pane { display: none; }
    Screen.-compact Footer { display: none; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("f5", "refresh", "Refresh", show=False),
        Binding("slash", "focus_filter", "Filter", show=False),
        Binding("c", "copy_command", "Copy cmd"),
        Binding("o", "open_report", "Open report"),
        Binding("t", "toggle_archived", "Toggle archived"),
        Binding("b", "show_list", "Back", show=False),
        Binding("l", "toggle_compact_view", "List/detail", show=False),
        Binding("question_mark", "help", "Help", show=False),
        Binding("escape", "dismiss_overlay", "Dismiss", show=False),
        Binding("1", "switch_tab('summary')", "Summary", show=False),
        Binding("2", "switch_tab('plan')", "Plan", show=False),
        Binding("3", "switch_tab('todos')", "Todos", show=False),
        Binding("4", "switch_tab('implementation')", "Impl", show=False),
        Binding("5", "switch_tab('reviews')", "Reviews", show=False),
        Binding("6", "switch_tab('validation')", "Valid", show=False),
        Binding("7", "switch_tab('files')", "Files", show=False),
        Binding("8", "switch_tab('events')", "Events", show=False),
        Binding("9", "switch_tab('raw-report')", "Raw", show=False),
    ]
    # Stage filter bindings are generated dynamically because they overlap
    # with tab-switching keys (we use letters that aren't 1..9).
    for _key, (_label, _statuses) in _STAGE_FILTERS.items():
        if _key in {"a", "n", "p", "i", "m", "v", "f", "d", "c"}:
            BINDINGS.append(
                Binding(
                    _key,
                    f"filter_stage('{_key}')",
                    f"Filter {_label}",
                    show=False,
                )
            )
    del _key, _label, _statuses

    def __init__(
        self,
        *,
        workspace_root: Path,
        task_ref: str | None = None,
        refresh_seconds: int | None = None,
        include_archived: bool = False,
        layout: str = "auto",
    ) -> None:
        super().__init__()
        self.workspace_root = workspace_root
        self.task_ref = task_ref
        self.refresh_seconds = refresh_seconds
        self.include_archived = include_archived
        self.snapshot: dict[str, Any] = {}
        self._stage_filter: tuple[str, ...] = ()  # empty = all
        self._filter_text = ""
        self._refresh_timer: Any = None
        layout_mode = (layout or "auto").strip().lower()
        if layout_mode not in _VALID_LAYOUTS:
            layout_mode = "auto"
        self.layout = layout_mode
        # Initial compact pane: detail if a task_ref was provided, else list.
        self._compact_view: str = "detail" if task_ref else "list"

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="tasks-pane"):
                yield Input(
                    placeholder="/ filter by id, slug, title, label",
                    id="filter-input",
                )
                yield ListView(id="tasks")
            with Vertical(id="detail-pane"):
                with TabbedContent(id="tabs"):
                    yield TabPane(
                        "Summary",
                        VerticalScroll(
                            Static(id="summary-tab"),
                            classes="tab-scroll",
                        ),
                        id="summary",
                    )
                    yield TabPane(
                        "Plan",
                        VerticalScroll(
                            Static(id="plan-tab"),
                            classes="tab-scroll",
                        ),
                        id="plan",
                    )
                    yield TabPane(
                        "Todos",
                        VerticalScroll(
                            Static(id="todos-tab"),
                            classes="tab-scroll",
                        ),
                        id="todos",
                    )
                    yield TabPane(
                        "Implementation",
                        VerticalScroll(
                            Static(id="implementation-tab"),
                            classes="tab-scroll",
                        ),
                        id="implementation",
                    )
                    yield TabPane(
                        "Reviews",
                        VerticalScroll(
                            Static(id="reviews-tab"),
                            classes="tab-scroll",
                        ),
                        id="reviews",
                    )
                    yield TabPane(
                        "Validation",
                        VerticalScroll(
                            Static(id="validation-tab"),
                            classes="tab-scroll",
                        ),
                        id="validation",
                    )
                    yield TabPane(
                        "Files",
                        VerticalScroll(
                            Static(id="files-tab"),
                            classes="tab-scroll",
                        ),
                        id="files",
                    )
                    yield TabPane(
                        "Events",
                        VerticalScroll(
                            Static(id="events-tab"),
                            classes="tab-scroll",
                        ),
                        id="events",
                    )
                    yield TabPane(
                        "Raw Report",
                        VerticalScroll(
                            Static(id="raw-report-tab"),
                            classes="tab-scroll",
                        ),
                        id="raw-report",
                    )
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._sync_layout_classes()
        self.action_refresh()
        if self.refresh_seconds and self.refresh_seconds > 0:
            self._refresh_timer = self.set_interval(
                self.refresh_seconds, self.action_refresh
            )

    def on_resize(self, event: events.Resize) -> None:  # noqa: ARG002
        # Re-evaluate auto layout. Wide/compact are explicit and unaffected by
        # resize, but _sync_layout_classes still keeps the screen classes
        # consistent if future state changes occur.
        self._sync_layout_classes()

    # ------------------------------------------------------------------
    # Compact layout helpers
    # ------------------------------------------------------------------

    def _is_compact_layout(self) -> bool:
        if self.layout == "compact":
            return True
        if self.layout == "wide":
            return False
        return self.size.width < _COMPACT_WIDTH

    def _set_screen_class(self, class_name: str, enabled: bool) -> None:
        # The screen may not exist yet during early compose; skip silently.
        screen = getattr(self, "screen", None)
        if screen is None:
            return
        try:
            if enabled:
                screen.add_class(class_name)
            else:
                screen.remove_class(class_name)
        except Exception:
            # Defensive: avoid crashing the app over stale class state during
            # shutdown/teardown. This is not expected to fire in normal use.
            pass

    def _sync_layout_classes(self) -> None:
        compact = self._is_compact_layout()
        view = self._compact_view if self._compact_view in _COMPACT_VIEWS else "list"
        self._compact_view = view
        for class_name in ("-compact", "-wide", "-list", "-detail"):
            self._set_screen_class(class_name, False)
        self._set_screen_class("-compact" if compact else "-wide", True)
        if compact:
            self._set_screen_class(
                "-detail" if view == "detail" else "-list",
                True,
            )

    # ------------------------------------------------------------------
    # Snapshot refresh and rendering
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        try:
            self.snapshot = load_tui_snapshot(
                self.workspace_root,
                task_ref=self.task_ref,
                include_events=True,
                include_archived=self.include_archived,
            )
        except LaunchError as exc:
            self._set_status(f"refresh blocked: {exc.code}: {exc.message}")
            return
        except OSError as exc:
            self._set_status(f"refresh io error: {exc}")
            return
        self._render_snapshot()

    def _render_snapshot(self) -> None:
        self._render_task_list()
        self._render_detail()
        self._set_status(self._render_status_text())

    def _render_status_text(self) -> str:
        parts: list[str] = []
        if self._is_compact_layout():
            parts.append(f"compact:{self._compact_view}")
        selected = self.snapshot.get("selected")
        task_raw = None
        next_action: dict[str, Any] = {}
        if isinstance(selected, dict):
            raw = selected.get("task")
            task_raw = raw if isinstance(raw, dict) else None
            na_raw = selected.get("next_action")
            next_action = na_raw if isinstance(na_raw, dict) else {}
        if task_raw is not None:
            parts.append(str(task_raw.get("id", "")))
            status = str(task_raw.get("status_stage", ""))
            if self._is_compact_layout():
                status = _STAGE_LABELS_SHORT.get(status, status[:5])
            if status:
                parts.append(status)
        else:
            parts.append("no task selected")
        if next_action.get("action"):
            parts.append(f"next: {next_action.get('action')}")
        if self._stage_filter:
            label = "+".join(self._stage_filter) or "all"
            parts.append(f"filter: {label}")
        if self._filter_text:
            parts.append(f"search: {self._filter_text}")
        if self._is_compact_layout():
            if self._compact_view == "list":
                parts.append("Enter=open")
            else:
                parts.append("b=list")
        return " | ".join(part for part in parts if part)

    def _set_status(self, text: str) -> None:
        widget = _safe_query_one(self, "#status-bar", Static)
        if widget is not None:
            widget.update(text)

    # ------------------------------------------------------------------
    # Task list rendering
    # ------------------------------------------------------------------

    def _iter_candidate_tasks(self) -> list[dict[str, Any]]:
        visible = list(self.snapshot.get("tasks") or [])
        archived = list(self.snapshot.get("archived_tasks") or [])
        return visible + archived

    def _matches_filters(self, task: dict[str, Any]) -> bool:
        if self._stage_filter:
            status = str(task.get("status_stage") or "")
            if status not in self._stage_filter:
                return False
        if self._filter_text:
            haystack_parts = [
                str(task.get("id") or ""),
                str(task.get("slug") or ""),
                str(task.get("title") or ""),
            ]
            labels = task.get("labels") or []
            if labels:
                haystack_parts.extend(str(label) for label in labels)
            haystack = " ".join(haystack_parts).lower()
            if self._filter_text.lower() not in haystack:
                return False
        return True

    def _task_label(self, task: dict[str, Any], active_task_id: str) -> str:
        marker = "*" if task.get("id") == active_task_id else " "
        task_id = str(task.get("id", ""))
        title = str(task.get("title", ""))
        status_raw = str(task.get("status_stage") or "")
        archived_flag = bool(task.get("archived"))
        if self._is_compact_layout():
            status = _STAGE_LABELS_SHORT.get(status_raw, status_raw[:5])
            archived = " A" if archived_flag else ""
            return f"{marker} {task_id} [{status}]{archived} {title}"
        archived = " (archived)" if archived_flag else ""
        return f"{marker} {task_id} [{status_raw}]{archived} {title}"

    def _render_task_list(self) -> None:
        task_list = _safe_query_one(self, "#tasks", ListView)
        if task_list is None:
            return
        task_list.clear()
        active_task_id = ""
        project = self.snapshot.get("project") or {}
        active = project.get("active_task") if isinstance(project, dict) else None
        if isinstance(active, dict):
            active_task_id = str(active.get("task_id") or "")
        for task in self._iter_candidate_tasks():
            if not self._matches_filters(task):
                continue
            label = self._task_label(task, active_task_id)
            task_list.append(ListItem(Static(label)))

    def _render_detail(self) -> None:
        selected = self.snapshot.get("selected")
        self._update_static("#summary-tab", tui_widgets.render_summary(selected))
        self._update_static(
            "#plan-tab",
            tui_widgets.render_plan(
                self.snapshot.get("plan_review_markdown"), selected
            ),
        )
        self._update_static("#todos-tab", tui_widgets.render_todos(selected))
        self._update_static(
            "#implementation-tab", tui_widgets.render_implementation(selected)
        )
        self._update_static(
            "#reviews-tab",
            tui_widgets.render_reviews(self.snapshot.get("reviews") or []),
        )
        self._update_static("#validation-tab", tui_widgets.render_validation(selected))
        self._update_static("#files-tab", tui_widgets.render_files(selected))
        self._update_static("#events-tab", tui_widgets.render_events(selected))
        self._update_static(
            "#raw-report-tab",
            tui_widgets.render_raw_report(self.snapshot.get("report_markdown")),
        )

        target_tab = tui_widgets.default_tab_for_selected(selected)
        tabs = _safe_query_one(self, "#tabs", TabbedContent)
        if tabs is not None:
            tabs.active = target_tab

    def _update_static(self, selector: str, content: str) -> None:
        widget = _safe_query_one(self, selector, Static)
        if widget is not None:
            widget.update(content)

    # ------------------------------------------------------------------
    # List + input events
    # ------------------------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        # Each ListItem's first child is the Static that holds the label.
        text = ""
        try:
            label_widget = next(iter(item.children))
            text = str(getattr(label_widget, "renderable", "") or "")
        except (StopIteration, IndexError):
            pass
        # Label format: "{marker} {task_id} [...]"
        parts = text.split()
        if len(parts) >= 2:
            self.task_ref = parts[1]
            self.action_refresh()
            self.action_show_detail()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "filter-input":
            return
        self._filter_text = event.value.strip()
        self._render_task_list()
        self._set_status(self._render_status_text())

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def action_focus_filter(self) -> None:
        if self._is_compact_layout():
            self.action_show_list()
        widget = _safe_query_one(self, "#filter-input", Input)
        if widget is not None:
            widget.focus()

    def action_filter_stage(self, key: str) -> None:
        spec = _STAGE_FILTERS.get(key)
        if spec is None:
            return
        _, statuses = spec
        self._stage_filter = statuses
        self._render_task_list()
        self._set_status(self._render_status_text())

    def action_toggle_archived(self) -> None:
        self.include_archived = not self.include_archived
        self.action_refresh()

    def action_copy_command(self) -> None:
        selected = self.snapshot.get("selected")
        if not isinstance(selected, dict):
            self._set_status("no task selected")
            return
        na_raw = selected.get("next_action")
        next_action: dict[str, Any] = na_raw if isinstance(na_raw, dict) else {}
        commands: list[str] = []
        for entry in next_action.get("commands") or []:
            if isinstance(entry, dict):
                cmd = entry.get("command")
                if isinstance(cmd, str) and cmd:
                    commands.append(cmd)
            elif isinstance(entry, str):
                commands.append(entry)
        primary: str | None = None
        if isinstance(next_action.get("next_command"), str):
            primary = next_action["next_command"]
        if not commands and not primary:
            self._set_status("no commands available")
            return
        self.push_screen(_CommandScreen(commands, primary))  # type: ignore[call-overload]

    def action_open_report(self) -> None:
        selected = self.snapshot.get("selected")
        if not isinstance(selected, dict):
            self._set_status("no task selected")
            return
        task_raw = selected.get("task")
        task: dict[str, Any] = task_raw if isinstance(task_raw, dict) else {}
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            self._set_status("selected task has no id")
            return
        try:
            from taskledger.services.html_reports import (
                HtmlReportOptions,
                render_task_report_html,
            )
        except ImportError as exc:
            self._set_status(f"html reports unavailable: {exc}")
            return
        try:
            payload = render_task_report_html(
                self.workspace_root,
                task_id,
                options=HtmlReportOptions(),
            )
        except LaunchError as exc:
            self._set_status(f"report blocked: {exc.code}: {exc.message}")
            return
        except OSError as exc:
            self._set_status(f"report io error: {exc}")
            return
        content = payload.get("html") if isinstance(payload, dict) else None
        if not isinstance(content, str):
            self._set_status("report payload missing html")
            return
        target = self.workspace_root / f"{task_id}.tui-report.html"
        try:
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            self._set_status(f"report write failed: {exc}")
            return
        self._set_status(f"static report written to {target}")

    def action_dismiss_overlay(self) -> None:
        # Textual's pop_screen handles modal screens. If no modal is open,
        # ScreenStackError is raised; in compact detail mode we then return
        # to the list view so Esc works as a back button.
        try:
            self.pop_screen()
        except self._ScreenStackError:
            if self._is_compact_layout() and self._compact_view == "detail":
                self.action_show_list()
            return

    def action_switch_tab(self, tab_id: str) -> None:
        tabs = _safe_query_one(self, "#tabs", TabbedContent)
        if tabs is not None:
            tabs.active = tab_id
        if self._is_compact_layout() and self._compact_view != "detail":
            # Tab switch from compact list view should reveal the detail pane.
            self.action_show_detail()

    def action_help(self) -> None:
        self.push_screen(_HelpScreen())  # type: ignore[call-overload]

    # ------------------------------------------------------------------
    # Compact navigation actions
    # ------------------------------------------------------------------

    def action_show_list(self) -> None:
        self._compact_view = "list"
        self._sync_layout_classes()
        self._set_status(self._render_status_text())
        tasks = _safe_query_one(self, "#tasks", ListView)
        if tasks is not None:
            tasks.focus()

    def action_show_detail(self) -> None:
        selected = self.snapshot.get("selected")
        if not isinstance(selected, dict):
            self._set_status("no task selected")
            return
        self._compact_view = "detail"
        self._sync_layout_classes()
        self._set_status(self._render_status_text())
        # Focus the tabbed content so 1..9 bindings land on tabs immediately.
        tabs = _safe_query_one(self, "#tabs", TabbedContent)
        if tabs is not None:
            tabs.focus()

    def action_toggle_compact_view(self) -> None:
        if not self._is_compact_layout():
            return
        if self._compact_view == "detail":
            self.action_show_list()
        else:
            self.action_show_detail()

    # Alias for the ScreenStackError type without forcing callers to import it.
    from textual.app import ScreenStackError as _ScreenStackError


class _CommandScreen(CommandCopyModal):
    """Screen wrapper so the modal can be popped via App.push_screen."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Close", show=False)]
    BINDINGS.append(Binding("c", "app.pop_screen", "Close", show=False))


class _HelpScreen(HelpOverlay):
    BINDINGS = [Binding("escape", "app.pop_screen", "Close", show=False)]
    BINDINGS.append(Binding("question_mark", "app.pop_screen", "Close", show=False))
    BINDINGS.append(Binding("?", "app.pop_screen", "Close", show=False))


def run_tui(
    *,
    workspace_root: Path,
    task_ref: str | None = None,
    refresh_seconds: int | None = None,
    include_archived: bool = False,
    layout: str = "auto",
) -> None:
    """Launch the Textual app. Blocking; returns when the user quits."""

    app_instance = TaskledgerTui(
        workspace_root=workspace_root,
        task_ref=task_ref,
        refresh_seconds=refresh_seconds,
        include_archived=include_archived,
        layout=layout,
    )
    app_instance.run()
