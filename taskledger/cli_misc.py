from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, cast

import typer

from taskledger.api.handoff import (
    cancel_handoff_api,
    claim_handoff_api,
    close_handoff_api,
    create_handoff,
    list_all_handoffs,
    render_handoff,
    show_handoff,
)
from taskledger.api.introductions import (
    create_introduction,
    link_introduction,
    list_introductions,
    resolve_introduction,
)
from taskledger.api.locks import break_lock, list_locks, show_lock
from taskledger.api.tasks import (
    add_file_link,
    add_requirement,
    add_todo,
    can_perform,
    list_file_links,
    next_action,
    next_todo,
    reindex,
    remove_file_link,
    remove_requirement,
    set_todo_done,
    show_todo,
    todo_status,
    waive_requirement,
)
from taskledger.api.tasks import (
    file_status as file_status_api,
)
from taskledger.api.tasks import (
    refresh_file_baseline as refresh_file_baseline_api,
)
from taskledger.cli_common import (
    TaskOption,
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    read_text_input,
    render_json,
    resolve_cli_task,
)
from taskledger.errors import LaunchError
from taskledger.services.doctor import (
    inspect_v2_indexes,
    inspect_v2_locks,
    inspect_v2_project,
    inspect_v2_schema,
)
from taskledger.storage.task_store import (
    load_active_locks,
    load_requirements,
    load_todos,
)


def _todo_status_label(todo: Any) -> str:
    status = (
        getattr(todo, "status", None) if hasattr(todo, "status") else todo.get("status")
    )
    if isinstance(status, str) and status.strip():
        return status
    done = getattr(todo, "done", None) if hasattr(todo, "done") else todo.get("done")
    return "done" if done else "open"


def _todo_done_command_hint(todo: dict[str, object]) -> str | None:
    if todo.get("done") or todo.get("status") == "done":
        return None
    todo_id = todo.get("id")
    if not isinstance(todo_id, str) or not todo_id:
        return None
    return f'taskledger todo done {todo_id} --evidence "..."'


def _todo_detail_lines(todo: dict[str, object]) -> list[str]:
    lines: list[str] = []
    text = todo.get("text")
    if isinstance(text, str) and text.strip():
        lines.append(text.strip())
    validation_hint = todo.get("validation_hint")
    if isinstance(validation_hint, str) and validation_hint.strip():
        if lines:
            lines.append("")
        lines.append("Validation hint:")
        lines.append(validation_hint.strip())
    done_command = _todo_done_command_hint(todo)
    if done_command is not None:
        if lines:
            lines.append("")
        lines.append("Done command:")
        lines.append(done_command)
    return lines


def _compact_todo_dict(todo: Any) -> dict[str, object]:
    """Extract compact fields for a todo mutation response."""
    return {
        "id": todo.id,
        "text": todo.text,
        "status": _todo_status_label(todo),
        "done": todo.done,
        "mandatory": todo.mandatory,
        "source": todo.source,
        "evidence_count": len(todo.evidence or ()),
    }


def _todo_progress_from_task(task: Any) -> dict[str, object]:
    """Compute todo progress from a task object."""
    todos = getattr(task, "todos", []) or []
    total = len(todos)
    done = sum(1 for t in todos if getattr(t, "done", False))
    open_ids = [getattr(t, "id", None) for t in todos if not getattr(t, "done", False)]
    return {"total": total, "done": done, "open": total - done, "open_ids": open_ids}


def _next_todo_or_finish_command(progress: dict[str, object]) -> str:
    """Return the next command hint based on todo progress."""
    open_ids = progress.get("open_ids", [])
    if open_ids and isinstance(open_ids, list) and len(open_ids) > 0:
        next_id = open_ids[0]
        return f"taskledger todo show {next_id}"
    return "taskledger implement finish --summary SUMMARY"


def register_todo_v2_commands(app: typer.Typer) -> None:  # noqa: C901
    @app.command("add")
    def add_command(
        ctx: typer.Context,
        text: Annotated[str, typer.Option("--text")],
        mandatory: Annotated[
            bool | None,
            typer.Option("--mandatory", help="Mark todo as mandatory gate."),
        ] = None,
        optional: Annotated[
            bool,
            typer.Option("--optional", help="Explicitly mark todo as optional."),
        ] = False,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            resolved_mandatory: bool
            if optional:
                resolved_mandatory = False
            elif mandatory is not None:
                resolved_mandatory = mandatory
            else:
                locks = load_active_locks(state.cwd)
                active_impl = any(
                    lock.task_id == task.id and lock.stage == "implementing"
                    for lock in locks
                )
                resolved_mandatory = active_impl
            task = add_todo(state.cwd, task.id, text=text, mandatory=resolved_mandatory)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        # Find the newly added todo (last in the list)
        new_todo = task.todos[-1]
        progress = _todo_progress_from_task(task)
        next_command = _next_todo_or_finish_command(progress)
        compact = {
            "kind": "todo_added",
            "todo": _compact_todo_dict(new_todo),
            "task_id": task.id,
            "progress": progress,
            "next_command": next_command,
        }
        emit_payload(
            ctx,
            compact,
            result_type="todo_added",
            human=(
                f"added {new_todo.id} on {task.id}"
                f"  ({progress['done']}/{progress['total']} done)"
            ),
        )

    @app.command("list")
    def list_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            todos = load_todos(state.cwd, task.id).todos
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        payload = {
            "kind": "todo_list",
            "task_id": task.id,
            "todos": [todo.to_dict() for todo in todos],
        }
        lines = ["TODOS"]
        for todo in todos:
            status = "done" if todo.done else "open"
            lines.append(f"{todo.id}  {status}  {todo.text}")
        emit_payload(
            ctx, payload, human="\n".join(lines) if todos else "TODOS\n(empty)"
        )

    @app.command("done")
    def done_command(
        ctx: typer.Context,
        todo_id: Annotated[str, typer.Argument(...)],
        evidence: Annotated[str | None, typer.Option("--evidence")] = None,
        artifact: Annotated[list[str] | None, typer.Option("--artifact")] = None,
        change: Annotated[list[str] | None, typer.Option("--change")] = None,
        task_ref: TaskOption = None,
    ) -> None:
        _emit_todo_update(
            ctx,
            task_ref,
            todo_id,
            done=True,
            evidence=evidence,
            artifacts=tuple(artifact or ()),
            changes=tuple(change or ()),
        )

    @app.command("undone")
    def undone_command(
        ctx: typer.Context,
        todo_id: Annotated[str, typer.Argument(...)],
        task_ref: TaskOption = None,
    ) -> None:
        _emit_todo_update(ctx, task_ref, todo_id, done=False)

    @app.command("show")
    def show_command(
        ctx: typer.Context,
        todo_id: Annotated[str, typer.Argument(...)],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = show_todo(state.cwd, task.id, todo_id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        todo = payload["todo"]
        assert isinstance(todo, dict)
        lines = [f"{todo['id']}  {_todo_status_label(todo)}", *_todo_detail_lines(todo)]
        emit_payload(ctx, payload, human="\n".join(lines))

    @app.command("status")
    def status_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = todo_status(state.cwd, task.id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc

        # Build human-readable output
        total = payload.get("total", 0)
        done = payload.get("done", 0)
        can_finish = payload.get("can_finish_implementation", False)
        lines = [f"TODOS {payload['task_id']}  {done}/{total} done"]

        todos = load_todos(state.cwd, task.id).todos
        for todo in todos:
            status_mark = "[x]" if todo.done else "[ ]"
            lines.append(f"{status_mark} {todo.id}  {todo.text}")

        if can_finish:
            lines.append("\nFinish: Ready to implement finish.")
        else:
            lines.append(
                f"\nFinish blocked: "
                f"{cast(int, total) - cast(int, done)} todos are not done."
            )

        emit_payload(ctx, payload, human="\n".join(lines))

    @app.command("next")
    def next_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = next_todo(state.cwd, task.id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc

        # Build human-readable output
        next_todo_id = payload.get("next_todo_id")
        if next_todo_id is None:
            human = "No unfinished todos. Ready to finish implementation."
        else:
            next_todo_obj = cast(dict[str, object], payload.get("next_todo", {}))
            lines = [f"Next todo: {next_todo_id}", *_todo_detail_lines(next_todo_obj)]
            human = "\n".join(lines)

        emit_payload(ctx, payload, human=human)


def register_intro_v2_commands(app: typer.Typer) -> None:
    @app.command("create")
    def create_command(
        ctx: typer.Context,
        title: Annotated[str, typer.Argument(...)],
        text: Annotated[str | None, typer.Option("--text")] = None,
        from_file: Annotated[Path | None, typer.Option("--from-file")] = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            intro = create_introduction(
                state.cwd,
                title=title,
                body=read_text_input(text=text, from_file=from_file),
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, intro.to_dict(), human=f"created intro {intro.id}")

    @app.command("list")
    def list_command(ctx: typer.Context) -> None:
        state = cli_state_from_context(ctx)
        payload = [intro.to_dict() for intro in list_introductions(state.cwd)]
        human = "\n".join(
            ["INTRODUCTIONS", *[f"{intro['id']}  {intro['slug']}" for intro in payload]]
        )
        emit_payload(
            ctx,
            payload,
            human=human if payload else "INTRODUCTIONS\n(empty)",
        )

    @app.command("show")
    def show_command(
        ctx: typer.Context,
        intro_ref: Annotated[str, typer.Argument(...)],
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            intro = resolve_introduction(state.cwd, intro_ref)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, intro.to_dict(), human=intro.body)

    @app.command("link")
    def link_command(
        ctx: typer.Context,
        intro_ref: Annotated[str, typer.Argument(...)],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            task = link_introduction(state.cwd, task.id, intro_ref)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"linked intro to {task.id}")


def register_file_v2_commands(app: typer.Typer) -> None:  # noqa: C901
    def _resolve_snapshot_option(snapshot: bool, no_snapshot: bool) -> bool | None:
        if snapshot and no_snapshot:
            raise LaunchError(
                "Use either --snapshot or --no-snapshot, not both.",
                code="USAGE_ERROR",
                exit_code=2,
            )
        if snapshot:
            return True
        if no_snapshot:
            return False
        return None

    @app.command("add")
    def add_command(
        ctx: typer.Context,
        path: Annotated[str, typer.Option("--path")],
        kind: Annotated[str, typer.Option("--kind")] = "code",
        label: Annotated[str | None, typer.Option("--label")] = None,
        required_for_validation: Annotated[
            bool,
            typer.Option("--required-for-validation"),
        ] = False,
        snapshot: Annotated[bool, typer.Option("--snapshot")] = False,
        no_snapshot: Annotated[bool, typer.Option("--no-snapshot")] = False,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            task = add_file_link(
                state.cwd,
                task.id,
                path=path,
                kind=kind,
                label=label,
                required_for_validation=required_for_validation,
                snapshot=_resolve_snapshot_option(snapshot, no_snapshot),
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"linked file on {task.id}")

    @app.command("link")
    def link_command(
        ctx: typer.Context,
        task_ref_arg: Annotated[str, typer.Argument(help="Task ref.")],
        path: Annotated[str, typer.Argument(help="Linked file path.")],
        kind: Annotated[str, typer.Option("--kind")] = "code",
        label: Annotated[str | None, typer.Option("--label")] = None,
        required_for_validation: Annotated[
            bool,
            typer.Option("--required-for-validation"),
        ] = False,
        snapshot: Annotated[bool, typer.Option("--snapshot")] = False,
        no_snapshot: Annotated[bool, typer.Option("--no-snapshot")] = False,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = add_file_link(
                state.cwd,
                task_ref_arg,
                path=path,
                kind=kind,
                label=label,
                required_for_validation=required_for_validation,
                snapshot=_resolve_snapshot_option(snapshot, no_snapshot),
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"linked {path} on {task.id}")

    @app.command("remove")
    def remove_command(
        ctx: typer.Context,
        path: Annotated[str, typer.Option("--path")],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            task = remove_file_link(state.cwd, task.id, path=path)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"unlinked file on {task.id}")

    @app.command("list")
    def list_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = list_file_links(state.cwd, task.id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        file_links = payload["file_links"]
        assert isinstance(file_links, list)
        lines = ["FILES"]
        for item in file_links:
            if isinstance(item, dict):
                lines.append(f"@{item.get('path')} [{item.get('kind')}]")
        emit_payload(
            ctx, payload, human="\n".join(lines) if file_links else "FILES\n(empty)"
        )

    @app.command("status")
    def status_command(
        ctx: typer.Context,
        task_ref_arg: Annotated[str, typer.Argument(help="Task ref.")],
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = file_status_api(state.cwd, task_ref_arg)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        links = payload.get("links", [])
        lines = [f"FILES {payload['task_id']}"]
        if isinstance(links, list) and links:
            for item in links:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "").ljust(10)
                path = str(item.get("path") or "")
                kind = str(item.get("kind") or "")
                reason = str(item.get("reason") or "")
                current = item.get("current")
                hash_text = ""
                if isinstance(current, dict):
                    hash_value = current.get("hash")
                    if isinstance(hash_value, str) and hash_value:
                        hash_text = f" {hash_value[:16]}..."
                detail = reason if status.strip() != "unchanged" else hash_text.strip()
                lines.append(
                    f"  {status} {path} [{kind}]" + (f" {detail}" if detail else "")
                )
        else:
            lines.append("  (empty)")
        emit_payload(ctx, payload, human="\n".join(lines))

    @app.command("refresh")
    def refresh_command(
        ctx: typer.Context,
        task_ref_arg: Annotated[str, typer.Argument(help="Task ref.")],
        path: Annotated[str, typer.Argument(help="Linked file path.")],
        reason: Annotated[str, typer.Option("--reason")],
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = refresh_file_baseline_api(
                state.cwd,
                task_ref_arg,
                path=path,
                reason=reason,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            human=f"refreshed baseline for {path} on {payload['task_id']}",
        )


def register_link_v2_commands(app: typer.Typer) -> None:
    @app.command("add")
    def add_command(
        ctx: typer.Context,
        url: Annotated[str, typer.Option("--url")],
        label: Annotated[str | None, typer.Option("--label")] = None,
        task_ref: TaskOption = None,
    ) -> None:
        _emit_link_add(
            ctx,
            task_ref,
            path=url,
            kind="other",
            label=label,
            required_for_validation=False,
        )

    @app.command("remove")
    def remove_command(
        ctx: typer.Context,
        link_ref: Annotated[str, typer.Argument(help="Link URL or path.")],
        task_ref: TaskOption = None,
    ) -> None:
        _emit_link_remove(ctx, task_ref, path=link_ref)

    @app.command("list")
    def list_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
        _emit_link_list(ctx, task_ref)


def register_require_v2_commands(app: typer.Typer) -> None:
    @app.command("add")
    def add_command(
        ctx: typer.Context,
        required_task_ref: Annotated[str, typer.Argument(...)],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            task = add_requirement(state.cwd, task.id, required_task_ref)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"added requirement on {task.id}")

    @app.command("list")
    def list_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            requirements = load_requirements(state.cwd, task.id).requirements
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        refs = [item.task_id for item in requirements]
        emit_payload(
            ctx,
            [item.to_dict() for item in requirements],
            human="\n".join(["REQUIREMENTS", *refs])
            if refs
            else "REQUIREMENTS\n(empty)",
        )

    @app.command("remove")
    def remove_command(
        ctx: typer.Context,
        required_task_ref: Annotated[str, typer.Argument(...)],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            task = remove_requirement(state.cwd, task.id, required_task_ref)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"removed requirement on {task.id}")

    @app.command("waive")
    def waive_command(
        ctx: typer.Context,
        required_task_ref: Annotated[str, typer.Argument(...)],
        actor: Annotated[str, typer.Option("--actor")] = "user",
        reason: Annotated[str, typer.Option("--reason")] = "",
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            task = waive_requirement(
                state.cwd,
                task.id,
                required_task_ref,
                actor_type=actor,
                reason=reason,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, task.to_dict(), human=f"waived requirement on {task.id}")


def _emit_link_add(
    ctx: typer.Context,
    task_ref: str | None,
    *,
    path: str,
    kind: str,
    label: str | None,
    required_for_validation: bool,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        task = add_file_link(
            state.cwd,
            task.id,
            path=path,
            kind=kind,
            label=label,
            required_for_validation=required_for_validation,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, task.to_dict(), human=f"linked file on {task.id}")


def _emit_link_remove(ctx: typer.Context, task_ref: str | None, *, path: str) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        task = remove_file_link(state.cwd, task.id, path=path)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, task.to_dict(), human=f"unlinked file on {task.id}")


def _emit_link_list(ctx: typer.Context, task_ref: str | None) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = list_file_links(state.cwd, task.id)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    file_links = payload["file_links"]
    assert isinstance(file_links, list)
    lines = ["FILES"]
    for item in file_links:
        if isinstance(item, dict):
            lines.append(f"@{item.get('path')} [{item.get('kind')}]")
    emit_payload(
        ctx, payload, human="\n".join(lines) if file_links else "FILES\n(empty)"
    )


def _render_lock_show(payload: dict[str, object]) -> str:
    lock: dict[str, object] | None = payload.get("lock")  # type: ignore[assignment]
    task_id = str(payload.get("task_id", ""))
    if lock is None:
        return f"LOCK {task_id}\nstatus: no lock"

    diagnostics = payload.get("diagnostics") or {}
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    status_value = "active"
    expired = bool(diagnostics.get("expired"))
    if expired:
        status_value = "expired"

    lines: list[str] = []
    lines.append(f"LOCK {task_id}")
    lines.append(f"status: {status_value}")
    classification = diagnostics.get("classification")
    if classification:
        lines.append(f"classification: {classification}")

    def _str(field: str) -> str:
        value = lock.get(field)
        return "" if value is None else str(value)

    lines.append(f"stage: {_str('stage')}")
    lines.append(f"run: {_str('run_id')}")

    holder = lock.get("holder")
    if isinstance(holder, dict):
        actor_type = holder.get("actor_type", "?")
        actor_name = holder.get("actor_name", "?")
        host = holder.get("host") or "-"
        pid = holder.get("pid")
        pid_part = f" pid={pid}" if pid else ""
        lines.append(f"holder: {actor_type}:{actor_name} host={host}{pid_part}")

    harness = lock.get("harness")
    if isinstance(harness, dict):
        harness_name = harness.get("name", "unknown")
        harness_kind = harness.get("kind", "unknown")
        lines.append(f"harness: {harness_name} ({harness_kind})")

    lines.append(f"created: {_str('created_at')}")
    expires_at = _str("expires_at")
    expiry_label = diagnostics.get("expiry_label", "")
    if expiry_label:
        lines.append(f"expires: {expires_at} ({expiry_label})")
    else:
        lines.append(f"expires: {expires_at}")

    reason = _str("reason")
    if reason:
        lines.append(f"reason: {reason}")

    storage_root = payload.get("storage_root")
    if isinstance(storage_root, str) and storage_root:
        lines.append(f"storage: {storage_root}")
    lock_file = payload.get("lock_file")
    if isinstance(lock_file, str) and lock_file:
        lines.append(f"lock file: {lock_file}")

    summary = diagnostics.get("summary")
    if summary:
        lines.append("")
        lines.append("Assessment:")
        lines.append(str(summary))

    remediation = diagnostics.get("remediation") or []
    if isinstance(remediation, list | tuple) and remediation:
        lines.append("")
        lines.append("Next commands:")
        for index, command in enumerate(remediation, start=1):
            command_text = str(command)
            if command_text.startswith("#"):
                lines.append(f"- {command_text.lstrip('#').strip()}")
            else:
                lines.append(f"{index}. {command_text}")

    return "\n".join(lines)


def register_lock_v2_commands(app: typer.Typer) -> None:
    @app.command("show")
    def show_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = show_lock(state.cwd, task.id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_lock_show(payload))

    @app.command("break")
    def break_command(
        ctx: typer.Context,
        reason: Annotated[str, typer.Option("--reason")],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = break_lock(state.cwd, task.id, reason=reason)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=f"broke lock for {payload['task_id']}")

    @app.command("list")
    def list_command(ctx: typer.Context) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = list_locks(state.cwd)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        locks = payload["locks"]
        assert isinstance(locks, list)
        lines = ["LOCKS"]
        for item in locks:
            if isinstance(item, dict):
                lines.append(
                    f"{item.get('task_id')}  {item.get('stage')}  {item.get('run_id')}"
                )
        emit_payload(
            ctx, payload, human="\n".join(lines) if locks else "LOCKS\n(empty)"
        )


def register_handoff_v2_commands(app: typer.Typer) -> None:
    @app.command("create")
    def create_command(
        ctx: typer.Context,
        mode: Annotated[str | None, typer.Option("--mode")] = None,
        context_for: Annotated[str | None, typer.Option("--for")] = None,
        worker_step_id: Annotated[
            str | None, typer.Option("--worker", help="Configured worker step id.")
        ] = None,
        scope: Annotated[str | None, typer.Option("--scope")] = None,
        todo_id: Annotated[str | None, typer.Option("--todo")] = None,
        focus_run_id: Annotated[str | None, typer.Option("--run")] = None,
        intended_actor: Annotated[str | None, typer.Option("--intended-actor")] = None,
        intended_harness: Annotated[
            str | None, typer.Option("--intended-harness")
        ] = None,
        summary: Annotated[str | None, typer.Option("--summary")] = None,
        next_action: Annotated[str | None, typer.Option("--next-action")] = None,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = create_handoff(
                state.cwd,
                task.id,
                mode=mode,
                context_for=context_for,
                worker_step_id=worker_step_id,
                scope=scope,
                todo_id=todo_id,
                focus_run_id=focus_run_id,
                intended_actor_type=intended_actor,
                intended_harness=intended_harness,
                summary=summary,
                next_action=next_action,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=f"created handoff {payload['handoff_id']}")

    @app.command("list")
    def list_handoff_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            handoffs = list_all_handoffs(state.cwd, task.id)
            payload = {"kind": "handoff_list", "task_id": task.id, "handoffs": handoffs}
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(
            ctx,
            payload,
            human="\n".join(str(h["handoff_id"]) for h in handoffs),
        )

    @app.command("claim")
    def claim_command(
        ctx: typer.Context,
        handoff_id: Annotated[str, typer.Argument(help="Handoff id.")],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = claim_handoff_api(state.cwd, task.id, handoff_id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=f"claimed handoff {payload['handoff_id']}")

    @app.command("close")
    def close_command(
        ctx: typer.Context,
        handoff_id: Annotated[str, typer.Argument(help="Handoff id.")],
        reason: Annotated[str | None, typer.Option("--reason")] = None,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = close_handoff_api(state.cwd, task.id, handoff_id, reason=reason)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=f"closed handoff {payload['handoff_id']}")

    @app.command("cancel")
    def cancel_command(
        ctx: typer.Context,
        handoff_id: Annotated[str, typer.Argument(help="Handoff id.")],
        reason: Annotated[str | None, typer.Option("--reason")] = None,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = cancel_handoff_api(state.cwd, task.id, handoff_id, reason=reason)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=f"cancelled handoff {payload['handoff_id']}")

    @app.command("show")
    def show_command(
        ctx: typer.Context,
        handoff_id: Annotated[str, typer.Argument(help="Handoff id.")],
        format_name: Annotated[str, typer.Option("--format")] = "text",
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            payload = show_handoff(
                state.cwd, task.id, handoff_id, format_name=format_name
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        human = (
            payload
            if isinstance(payload, str)
            else render_json(payload)
            if format_name == "json"
            else None
        )
        emit_payload(ctx, payload, human=human)

    @app.command("plan-context")
    def plan_context_command(
        ctx: typer.Context,
        format_name: Annotated[str, typer.Option("--format")] = "text",
        task_ref: TaskOption = None,
    ) -> None:
        _emit_handoff(
            ctx,
            task_ref,
            mode="plan-context",
            format_name=format_name,
        )

    @app.command("implementation-context")
    def implementation_context_command(
        ctx: typer.Context,
        format_name: Annotated[str, typer.Option("--format")] = "text",
        task_ref: TaskOption = None,
    ) -> None:
        _emit_handoff(
            ctx,
            task_ref,
            mode="implementation-context",
            format_name=format_name,
        )

    @app.command("validation-context")
    def validation_context_command(
        ctx: typer.Context,
        format_name: Annotated[str, typer.Option("--format")] = "text",
        task_ref: TaskOption = None,
    ) -> None:
        _emit_handoff(
            ctx,
            task_ref,
            mode="validation-context",
            format_name=format_name,
        )


def emit_next_action_command(
    ctx: typer.Context,
    task_ref: str | None,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = next_action(state.cwd, task.id)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(ctx, payload, human=_next_action_human(payload))


def _next_action_human(payload: dict[str, object]) -> str:
    lines = [f"{payload['action']}: {payload['reason']}"]

    next_item = payload.get("next_item")
    if isinstance(next_item, dict):
        kind = next_item.get("kind")
        item_id = next_item.get("id")
        text = next_item.get("text")
        if kind and kind != "none":
            label = f"Next {kind}:"
            if item_id and text:
                lines.append(f"{label} {item_id} -- {text}")
            elif item_id:
                lines.append(f"{label} {item_id}")

    command = payload.get("next_command")
    if command:
        lines.append(f"Command: {command}")
    _append_worker_pipeline_hint_lines(lines, payload)
    _append_planning_hint_lines(lines, payload)

    commands = payload.get("commands")
    if isinstance(commands, list):
        for item in commands:
            if not isinstance(item, dict) or item.get("primary"):
                continue
            command_label = item.get("label")
            command_text = item.get("command")
            if isinstance(command_label, str) and isinstance(command_text, str):
                lines.append(f"{command_label}: {command_text}")

    progress = payload.get("progress")
    if isinstance(progress, dict):
        todos = progress.get("todos")
        if isinstance(todos, dict):
            lines.append(
                f"Progress: {todos.get('done', 0)}/{todos.get('total', 0)} todos done"
            )
        questions = progress.get("questions")
        if isinstance(questions, dict) and questions.get("required_open") is not None:
            lines.append(f"Open required questions: {questions.get('required_open')}")
        validation = progress.get("validation")
        if isinstance(validation, dict):
            lines.append(
                "Validation progress: "
                f"{validation.get('satisfied', 0)}/"
                f"{validation.get('total', 0)} satisfied"
            )

    blockers = payload.get("blocking")
    if isinstance(blockers, list):
        for blocker in blockers:
            if isinstance(blocker, dict):
                msg = blocker.get("message")
                if msg:
                    lines.append(f"Blocker: {msg}")

    return "\n".join(lines)


def _append_worker_pipeline_hint_lines(
    lines: list[str],
    payload: dict[str, object],
) -> None:
    worker_pipeline = payload.get("worker_pipeline")
    if not isinstance(worker_pipeline, dict):
        return
    next_step = worker_pipeline.get("next_step")
    if isinstance(next_step, dict):
        step_id = next_step.get("id")
        if step_id:
            lines.append(f"Worker step: {step_id}")
    context_command = worker_pipeline.get("context_command")
    if isinstance(context_command, str):
        lines.append(f"Worker context: {context_command}")
    handoff_command = worker_pipeline.get("handoff_command")
    if isinstance(handoff_command, str):
        lines.append(f"Worker handoff: {handoff_command}")


def _append_planning_hint_lines(
    lines: list[str],
    payload: dict[str, object],
) -> None:
    guidance_command = payload.get("guidance_command")
    if isinstance(guidance_command, str):
        lines.append(f"Guidance: {guidance_command}")
    template_command = payload.get("template_command")
    if isinstance(template_command, str):
        lines.append(f"Template: {template_command}")
    required_plan_fields = payload.get("required_plan_fields")
    if isinstance(required_plan_fields, list) and required_plan_fields:
        lines.append(
            "Required plan fields: "
            + ", ".join(str(item) for item in required_plan_fields)
        )
    recommended_plan_fields = payload.get("recommended_plan_fields")
    if isinstance(recommended_plan_fields, list) and recommended_plan_fields:
        lines.append(
            "Recommended plan fields: "
            + ", ".join(str(item) for item in recommended_plan_fields)
        )


def emit_can_command(ctx: typer.Context, task_ref: str | None, action: str) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = can_perform(state.cwd, task.id, action)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    prefix = "yes" if payload["ok"] else "no"
    emit_payload(ctx, payload, human=f"{prefix}: {payload['reason']}")


def emit_reindex_command(ctx: typer.Context) -> None:
    state = cli_state_from_context(ctx)
    payload = reindex(state.cwd)
    emit_payload(ctx, payload, human="reindexed v2 task state")


def _doctor_human(
    payload: dict[str, object], *, limit: int = 20, verbose: bool = False
) -> str:
    """Render doctor diagnostics in human-readable format."""
    diagnostics = [
        item
        for item in cast(list[object], payload.get("diagnostics", []))
        if isinstance(item, dict)
    ]
    raw_errors = [str(item) for item in cast(list[object], payload.get("errors", []))]
    raw_warnings = [
        str(item) for item in cast(list[object], payload.get("warnings", []))
    ]
    mismatches = [
        item
        for item in cast(list[object], payload.get("run_lock_mismatches", []))
        if isinstance(item, dict)
    ]
    lines = [
        f"healthy: {str(payload['healthy']).lower()}",
        f"errors: {len(raw_errors)}  warnings: {len(raw_warnings)}",
    ]
    if raw_errors:
        lines.append("")
        lines.append("Errors:")
        max_errors = limit if verbose else min(limit, 8)
        for message in raw_errors[:max_errors]:
            lines.append(f"- {message}")
        if len(raw_errors) > max_errors:
            lines.append(
                f"... {len(raw_errors) - max_errors} more error(s); "
                "use --verbose or --json."
            )
    if raw_warnings and verbose:
        lines.append("")
        lines.append("Warnings:")
        for message in raw_warnings[:limit]:
            lines.append(f"- {message}")
        if len(raw_warnings) > limit:
            lines.append(
                f"... {len(raw_warnings) - limit} more warning(s); use --json."
            )

    if mismatches:
        lines.append("")
        lines.append("Run/lock mismatches:")
        for item in mismatches[:limit]:
            task_id = item.get("task_id", "?")
            run_type = item.get("run_type", "?")
            run_id = item.get("run_id", "?")
            lines.append(f"- {task_id} {run_type} {run_id}")
            next_command = item.get("next_command")
            if isinstance(next_command, str) and next_command.strip():
                lines.append(f"  next: {next_command}")
            note = item.get("note")
            if isinstance(note, str) and note.strip():
                lines.append(f"  note: {note}")
        if len(mismatches) > limit:
            lines.append(
                f"... {len(mismatches) - limit} more mismatch(es); use --json."
            )

    if diagnostics:
        lines.append("")
        lines.append("Diagnostics:")
        for item in diagnostics[:limit]:
            code = item.get("code", "unknown")
            severity = item.get("severity", "error")
            message = item.get("message", "")
            task_id = item.get("task_id")
            prefix = f"- [{severity}:{code}]"
            if task_id:
                prefix += f" {task_id}"
            lines.append(f"{prefix} {message}")
            for key in ("change_path", "run_path"):
                value = item.get(key)
                if value:
                    lines.append(f"  {key}: {value}")
            for hint in cast(list[object], item.get("repair_hints", []))[:2]:
                if isinstance(hint, str):
                    lines.append(f"  next: {hint}")
        if len(diagnostics) > limit:
            lines.append(
                f"... {len(diagnostics) - limit} more diagnostics; "
                "use --json for full details."
            )
    return "\n".join(lines)


def emit_doctor_command(ctx: typer.Context, *, verbose: bool = False) -> None:
    state = cli_state_from_context(ctx)
    payload = inspect_v2_project(state.cwd)
    emit_payload(
        ctx,
        payload,
        human=_doctor_human(payload, verbose=verbose),
    )


def emit_doctor_locks_command(ctx: typer.Context) -> None:
    state = cli_state_from_context(ctx)
    payload = inspect_v2_locks(state.cwd)
    emit_payload(
        ctx,
        payload,
        human=_lock_inspection_human(payload),
    )


def emit_doctor_schema_command(ctx: typer.Context) -> None:
    state = cli_state_from_context(ctx)
    payload = inspect_v2_schema(state.cwd)
    emit_payload(
        ctx,
        payload,
        human=f"schema healthy: {payload['healthy']}",
    )


def emit_doctor_indexes_command(ctx: typer.Context) -> None:
    state = cli_state_from_context(ctx)
    payload = inspect_v2_indexes(state.cwd)
    emit_payload(
        ctx,
        payload,
        human=f"indexes healthy: {payload['healthy']}",
    )


def _emit_todo_update(
    ctx: typer.Context,
    task_ref: str | None,
    todo_id: str,
    *,
    done: bool,
    evidence: str | None = None,
    artifacts: tuple[str, ...] = (),
    changes: tuple[str, ...] = (),
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        task = set_todo_done(
            state.cwd,
            task.id,
            todo_id,
            done=done,
            evidence=evidence,
            artifacts=artifacts,
            changes=changes,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    updated_todo = next((t for t in task.todos if t.id == todo_id), None)
    progress = _todo_progress_from_task(task)
    next_command = _next_todo_or_finish_command(progress)
    compact: dict[str, object] = {
        "kind": "todo_update",
        "todo_id": todo_id,
        "task_id": task.id,
        "status": _todo_status_label(updated_todo) if updated_todo else None,
        "done": updated_todo.done if updated_todo else None,
        "evidence_recorded": bool(evidence),
        "artifact_refs_added": len(artifacts or ()),
        "change_refs_added": len(changes or ()),
        "progress": progress,
        "next_command": next_command,
    }
    label = "done" if done else "undone"
    emit_payload(
        ctx,
        compact,
        result_type="todo_update",
        human=(
            f"{label} {todo_id} on {task.id}"
            f"  ({progress['done']}/{progress['total']} done)"
        ),
    )


def _emit_handoff(
    ctx: typer.Context,
    task_ref: str | None,
    *,
    mode: str,
    format_name: str,
) -> None:
    state = cli_state_from_context(ctx)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = render_handoff(
            state.cwd,
            task.id,
            mode=mode,
            format_name=format_name,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    human = (
        payload
        if isinstance(payload, str)
        else render_json(payload)
        if format_name == "json"
        else None
    )
    emit_payload(ctx, payload, human=human)


def _lock_inspection_human(payload: dict[str, object]) -> str:
    expired = payload.get("expired_locks")
    mismatches = payload.get("run_lock_mismatches")
    lines = ["EXPIRED LOCKS"]
    if isinstance(expired, list) and expired:
        for item in expired:
            if isinstance(item, dict):
                lines.append(str(item.get("task_id")))
    else:
        lines.append("(empty)")
    lines.append("RUN/LOCK MISMATCHES")
    if isinstance(mismatches, list) and mismatches:
        for item in mismatches:
            if isinstance(item, dict):
                lines.append(
                    f"{item.get('task_id')} {item.get('run_type')} "
                    f"{item.get('run_id')} next: {item.get('next_command')}"
                )
                note = item.get("note")
                if isinstance(note, str) and note.strip():
                    lines.append(f"  note: {note}")
    else:
        lines.append("(empty)")
    return "\n".join(lines)


def _expired_locks_human(payload: object) -> str:
    if not isinstance(payload, list) or not payload:
        return "EXPIRED LOCKS\n(empty)"
    lines = ["EXPIRED LOCKS"]
    for item in payload:
        if isinstance(item, dict):
            lines.append(str(item.get("task_id")))
    return "\n".join(lines)
