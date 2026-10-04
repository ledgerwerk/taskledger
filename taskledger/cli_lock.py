from __future__ import annotations

from typing import Annotated

import typer

from taskledger.api.locks import list_locks, show_lock
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
            current_actor, current_harness = resolve_effective_identity(
                state.cwd, cwd=state.cwd
            )
            payload = show_lock(
                state.cwd,
                task.id,
                current_actor=current_actor,
                current_harness=current_harness,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_lock_show(payload))

    @app.command("list")
    def list_command(
        ctx: typer.Context,
        problematic: Annotated[
            bool, typer.Option("--problematic", help="Show only locks with issues.")
        ] = False,
        expired: Annotated[
            bool, typer.Option("--expired", help="Show only expired locks.")
        ] = False,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = list_locks(state.cwd)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        locks = payload["locks"]
        assert isinstance(locks, list)
        # Apply filters.
        filtered = locks
        if problematic:
            filtered = [
                item
                for item in filtered
                if isinstance(item, dict)
                and item.get("classification", "none")
                not in {"none", "active_live_local_process", "active_same_actor"}
            ]
        if expired:
            filtered = [
                item
                for item in filtered
                if isinstance(item, dict) and item.get("status", {}).get("expired")
            ]
        lines = ["LOCKS"]
        for item in filtered:
            if isinstance(item, dict):
                task_id = item.get("task_id", "?")
                classification = item.get("classification", "?")
                stage = item.get("stage", "?")
                expired_flag = ""
                status = item.get("status")
                if isinstance(status, dict) and status.get("expired"):
                    expired_flag = " expired=yes"
                lines.append(f"{task_id}  {stage}  {classification}{expired_flag}")
                diag = item.get("diagnostics")
                if isinstance(diag, dict):
                    summary = diag.get("summary")
                    if summary:
                        lines.append(f"  assessment: {summary}")
                    remediation = diag.get("remediation", [])
                    if isinstance(remediation, list) and remediation:
                        first_cmd = remediation[0]
                        if isinstance(first_cmd, str):
                            lines.append(f"  next: {first_cmd}")
                parse_error = item.get("parse_error")
                if isinstance(parse_error, str):
                    lines.append(f"  error: {parse_error}")
        # Summary line.
        summary = payload.get("summary")
        if isinstance(summary, dict):
            total = summary.get("lock_file_count", len(locks))
            active = summary.get("active_count", 0)
            exp = summary.get("expired_count", 0)
            mal = summary.get("malformed_count", 0)
            lines.append(
                f"\nTotal: {total}, Active: {active}, Expired: {exp}, Malformed: {mal}"
            )
        emit_payload(
            ctx, payload, human="\n".join(lines) if filtered else "LOCKS\n(empty)"
        )
