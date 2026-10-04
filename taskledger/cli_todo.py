from __future__ import annotations

from typing import Annotated, Any, cast

import typer

from taskledger.api.tasks import (
    add_todo,
    next_todo,
    set_todo_done,
    show_todo,
    todo_status,
)
from taskledger.cli_common import (
    TaskOption,
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    resolve_cli_task,
)
from taskledger.errors import LaunchError
from taskledger.services.actors import resolve_effective_identity
from taskledger.storage.task_store import (
    load_active_locks,
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


def register_todo_v2_commands(app: typer.Typer) -> None:
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
        current_actor, current_harness = resolve_effective_identity(
            state.cwd, cwd=state.cwd
        )
        task = set_todo_done(
            state.cwd,
            task.id,
            todo_id,
            done=done,
            evidence=evidence,
            artifacts=artifacts,
            changes=changes,
            actor=current_actor,
            harness=current_harness,
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
