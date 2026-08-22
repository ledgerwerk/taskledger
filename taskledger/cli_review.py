from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from taskledger.api.reviews import (
    list_code_review_records,
    record_code_review,
    show_code_review,
)
from taskledger.cli_common import (
    TaskOption,
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    read_text_input,
    resolve_cli_task,
)
from taskledger.errors import LaunchError
from taskledger.services.actors import resolve_actor, resolve_harness


def register_review_commands(app: typer.Typer) -> None:
    @app.command("record")
    def record_command(
        ctx: typer.Context,
        result: Annotated[str, typer.Option("--result")],
        summary: Annotated[str | None, typer.Option("--summary")] = None,
        summary_file: Annotated[Path | None, typer.Option("--summary-file")] = None,
        from_git: Annotated[bool, typer.Option("--from-git")] = False,
        commit: Annotated[str | None, typer.Option("--commit")] = None,
        worker_step_id: Annotated[str | None, typer.Option("--worker")] = None,
        handoff_id: Annotated[str | None, typer.Option("--handoff")] = None,
        run_id: Annotated[str | None, typer.Option("--run")] = None,
        task_ref: TaskOption = None,
        actor_type: Annotated[str | None, typer.Option("--reviewer")] = None,
        actor_name: Annotated[str | None, typer.Option("--reviewer-name")] = None,
        harness_name: Annotated[str | None, typer.Option("--harness")] = None,
        session_id: Annotated[str | None, typer.Option("--session-id")] = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            body = read_text_input(
                text=summary,
                from_file=summary_file,
                text_label="--summary",
                file_label="--summary-file",
            )
            actor = resolve_actor(
                actor_type=actor_type,
                actor_name=actor_name,
                role="reviewer",
                session_id=session_id,
                workspace_root=state.cwd,
            )
            harness = resolve_harness(
                name=harness_name,
                session_id=session_id,
                cwd=state.cwd,
                workspace_root=state.cwd,
            )
            review = record_code_review(
                state.cwd,
                task.id,
                result=result,
                body=body,
                summary=summary if summary and summary.strip() else None,
                from_git=from_git,
                commit=commit,
                run_id=run_id,
                worker_step_id=worker_step_id,
                handoff_id=handoff_id,
                actor=actor,
                harness=harness,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc

        changed_paths_count = len(review.git_changed_paths)
        payload = {
            "kind": "code_review_recorded",
            "task_id": review.task_id,
            "review_id": review.review_id,
            "implementation_run": review.implementation_run,
            "result": review.result,
            "source": review.source,
            "worker_step_id": review.worker_step_id,
            "handoff_id": review.handoff_id,
            "git_commit": review.git_commit,
            "git_branch": review.git_branch,
            "changed_paths_count": changed_paths_count,
            "review": review.to_dict(),
        }
        warnings: list[str] = []
        if review.source == "working_tree" and changed_paths_count == 0:
            warnings.append(
                "Working tree source is clean; review recorded without changed paths."
            )
        if review.snapshot_drift:
            warnings.append(
                "Review snapshot drift detected: the workspace changed after the handoff was created."  # noqa: E501
            )
        emit_payload(
            ctx,
            payload,
            human=(
                f"recorded code review {review.review_id}  "
                f"result={review.result}  source={review.source}"
                + (f"  handoff={review.handoff_id}" if review.handoff_id else "")
                + (
                    f'\nNext: taskledger handoff close {review.handoff_id} --reason "Review recorded as {review.review_id}."'  # noqa: E501
                    if review.handoff_id
                    else ""
                )
            ),
            warnings=warnings or None,
        )

    @app.command("list")
    def list_command(
        ctx: typer.Context,
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            reviews = list_code_review_records(state.cwd, task.id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc

        payload = {
            "kind": "code_review_list",
            "task_id": task.id,
            "reviews": [review.to_dict() for review in reviews],
        }
        lines = [
            "ID           RESULT    SOURCE        RUN        WORKER        SUMMARY"
        ]
        if not reviews:
            lines.append("(empty)")
        for review in reviews:
            lines.append(
                f"{review.review_id:<12} "
                f"{review.result:<9} "
                f"{review.source:<13} "
                f"{(review.implementation_run or ''):<10} "
                f"{(review.worker_step_id or ''):<12} "
                f"{(review.summary or '').strip()}"
            )
        emit_payload(ctx, payload, human="\n".join(lines))

    @app.command("show")
    def show_command(
        ctx: typer.Context,
        review_ref: Annotated[str, typer.Argument(help="Review id/ref.")],
        task_ref: TaskOption = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            task = resolve_cli_task(state.cwd, task_ref)
            review = show_code_review(state.cwd, task.id, review_ref)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        payload = {
            "kind": "code_review_show",
            "task_id": task.id,
            "review": review.to_dict(),
        }
        lines = [
            f"{review.review_id}  {review.result}",
            f"source: {review.source}",
            f"run: {review.implementation_run or '(none)'}",
            f"worker: {review.worker_step_id or '(none)'}",
            "",
            review.body.strip(),
        ]
        emit_payload(ctx, payload, human="\n".join(lines))
