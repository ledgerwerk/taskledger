from __future__ import annotations

from typing import Annotated, cast

import typer

from taskledger.api.tasks import (
    reindex,
)
from taskledger.cli_common import (
    CLIState,
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    resolve_cli_task,
)
from taskledger.errors import LaunchError
from taskledger.services.doctor import (
    inspect_v2_indexes,
    inspect_v2_locks,
    inspect_v2_project,
    inspect_v2_schema,
)


def emit_reindex_command(ctx: typer.Context) -> None:
    state = cli_state_from_context(ctx)
    try:
        payload = reindex(state.cwd)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
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


def _render_lock_entries(
    lines: list[str],
    section_name: str,
    entries: object,
    *,
    show_remediation: bool = False,
    show_assessment: bool = False,
    show_path: bool = False,
) -> None:
    """Render a section of lock entries."""
    lines.append(section_name)
    if not isinstance(entries, list) or not entries:
        lines.append("  (empty)")
        return
    for item in entries:
        if not isinstance(item, dict):
            continue
        task_id = item.get("task_id", "?")
        classification = item.get("classification", "?")
        if show_path:
            lines.append(f"  {item.get('path', '?')}")
        else:
            lines.append(f"  {task_id}  {classification}")
        diag = item.get("diagnostics")
        if isinstance(diag, dict):
            if show_assessment:
                summary_text = diag.get("summary")
                if summary_text:
                    lines.append(f"    assessment: {summary_text}")
            if show_remediation:
                for cmd in diag.get("remediation", []):
                    if isinstance(cmd, str) and not cmd.startswith("#"):
                        lines.append(f"    next: {cmd}")
        parse_error = item.get("parse_error")
        if parse_error and show_path:
            lines.append(f"    error: {parse_error}")


def _lock_inspection_human(payload: dict[str, object]) -> str:
    lines: list[str] = []

    # Summary section.
    summary = payload.get("summary", {})
    if isinstance(summary, dict):
        lines.append("SUMMARY")
        for key in (
            "total",
            "live",
            "expired",
            "stale",
            "malformed",
            "unverifiable",
        ):
            val = summary.get(key)
            if val is not None:
                lines.append(f"  {key}: {val}")
        lines.append("")

    errors = payload.get("errors", [])
    if isinstance(errors, list) and errors:
        lines.append("ERRORS")
        for err in errors:
            if isinstance(err, str):
                lines.append(f"  - {err}")
        lines.append("")

    _render_lock_entries(
        lines,
        "EXPIRED LOCKS",
        payload.get("expired_locks"),
        show_remediation=True,
    )

    stale = payload.get("stale_locks")
    if isinstance(stale, list) and stale:
        lines.append("")
        _render_lock_entries(
            lines,
            "STALE LOCKS",
            stale,
            show_assessment=True,
            show_remediation=True,
        )

    malformed = payload.get("malformed_locks")
    if isinstance(malformed, list) and malformed:
        lines.append("")
        _render_lock_entries(
            lines,
            "MALFORMED LOCK FILES",
            malformed,
            show_path=True,
        )

    unverifiable = payload.get("unverifiable_locks")
    if isinstance(unverifiable, list) and unverifiable:
        lines.append("")
        _render_lock_entries(
            lines,
            "UNVERIFIABLE LOCKS",
            unverifiable,
            show_assessment=True,
        )

    mismatches = payload.get("run_lock_mismatches")
    lines.append("")
    lines.append("RUN/LOCK MISMATCHES")
    if isinstance(mismatches, list) and mismatches:
        for item in mismatches:
            if isinstance(item, dict):
                lines.append(
                    f"  {item.get('task_id')} "
                    f"{item.get('run_type')} "
                    f"{item.get('run_id')} "
                    f"next: {item.get('next_command')}"
                )
                note = item.get("note")
                if isinstance(note, str) and note.strip():
                    lines.append(f"    note: {note}")
    else:
        lines.append("  (empty)")

    next_commands = payload.get("next_commands")
    if isinstance(next_commands, list) and next_commands:
        lines.append("")
        lines.append("NEXT COMMANDS")
        for idx, cmd in enumerate(next_commands, 1):
            if isinstance(cmd, str):
                lines.append(f"  {idx}. {cmd}")

    return "\n".join(lines)


def _expired_locks_human(payload: object) -> str:
    if not isinstance(payload, list) or not payload:
        return "EXPIRED LOCKS\n(empty)"
    lines = ["EXPIRED LOCKS"]
    for item in payload:
        if isinstance(item, dict):
            lines.append(str(item.get("task_id")))
    return "\n".join(lines)


def doctor_command(
    ctx: typer.Context,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Show expanded doctor output including raw warnings.",
        ),
    ] = False,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    emit_doctor_command(ctx, verbose=verbose)


def doctor_locks_command(ctx: typer.Context) -> None:
    emit_doctor_locks_command(ctx)


def doctor_schema_command(ctx: typer.Context) -> None:
    emit_doctor_schema_command(ctx)


def doctor_indexes_command(ctx: typer.Context) -> None:
    emit_doctor_indexes_command(ctx)


def repair_index_command(ctx: typer.Context) -> None:
    emit_reindex_command(ctx)


def repair_lock_command(
    ctx: typer.Context,
    reason: Annotated[str, typer.Option("--reason")],
    task_ref: Annotated[
        str | None,
        typer.Option("--task", help="Task ref. Defaults to the active task."),
    ] = None,
) -> None:
    from taskledger.api.locks import break_lock

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = break_lock(state.cwd, task.id, reason=reason)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    human = f"repaired lock for {payload['task_id']}"
    orphaned_run = payload.get("orphaned_run")
    next_commands = payload.get("next_commands")
    if (
        isinstance(orphaned_run, dict)
        and isinstance(next_commands, list)
        and next_commands
        and isinstance(next_commands[0], str)
    ):
        run_id = orphaned_run.get("run_id", "unknown")
        run_type = orphaned_run.get("run_type", "task")
        if run_type == "planning":
            follow_up = (
                "Finish this orphaned planning run before starting or revising "
                "planning again:"
            )
        elif run_type == "implementation":
            follow_up = (
                "Resume the existing implementation run before starting new work:"
            )
        else:
            follow_up = "Inspect the task's next action before continuing:"
        human += (
            f"\n\nThe matching {run_type} run {run_id} is still marked running.\n"
            f"{follow_up}\n  {next_commands[0]}"
        )
    emit_payload(ctx, payload, human=human)


def repair_locks_command(
    ctx: typer.Context,
    apply: Annotated[
        bool, typer.Option("--apply", help="Apply repairs (default is dry-run).")
    ] = False,
    reason: Annotated[
        str, typer.Option("--reason", help="Reason for breaking locks.")
    ] = "",
) -> None:
    from taskledger.api.repair import repair_locks

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = repair_locks(state.cwd, apply=apply, reason=reason)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    if payload.get("dry_run"):
        entries_raw = payload.get("entries", [])
        entries = entries_raw if isinstance(entries_raw, list) else []
        lines = [f"BULK LOCK REPAIR (dry-run): {len(entries)} lock(s)"]
        for entry in entries:
            if isinstance(entry, dict):
                lines.append(f"  {entry.get('task_id')}  {entry.get('classification')}")
        next_cmd = payload.get("next_command")
        if next_cmd:
            lines.append(f"\nNext: {next_cmd}")
        emit_payload(ctx, payload, human="\n".join(lines))
    else:
        repaired_raw = payload.get("repaired", [])
        repaired = repaired_raw if isinstance(repaired_raw, list) else []
        failed_raw = payload.get("failed", [])
        failed = failed_raw if isinstance(failed_raw, list) else []
        lines = [f"repaired {len(repaired)} lock(s)"]
        for item in failed:
            if isinstance(item, dict):
                task_or_path = item.get("task_id", item.get("path"))
                err = item.get("error")
                lines.append(f"  failed: {task_or_path}: {err}")
        emit_payload(ctx, payload, human="\n".join(lines))


def _allocation_repair_dry_run_human(payload: dict[str, object]) -> str:
    entries_raw = payload.get("incomplete_allocations", [])
    entries = entries_raw if isinstance(entries_raw, list) else []
    lines = [
        f"INCOMPLETE TASK ALLOCATION REPAIR (dry-run): {len(entries)} allocation(s)"
    ]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        lines.append(f"  {entry.get('physical_source')}")
        display_id = entry.get("display_task_id")
        if display_id is not None:
            lines.append(f"    display={display_id}")
        lines.append(f"    mode={entry.get('repair_mode')}")
        survivor = entry.get("surviving_identity")
        if isinstance(survivor, dict):
            lines.append(f"    owner={survivor.get('task_uuid')}")
        tombstone = entry.get("planned_tombstone")
        tombstone_display = tombstone if tombstone is not None else "none"
        lines.append(f"    tombstone={tombstone_display}")
        findings = entry.get("collision_findings", [])
        if isinstance(findings, list):
            for finding in findings:
                if isinstance(finding, dict):
                    lines.append(
                        "    conflict="
                        f"{finding.get('kind')} {finding.get('path')} "
                        f"state={finding.get('state')}"
                    )
    next_command = payload.get("next_command")
    if isinstance(next_command, str) and next_command:
        lines.append(f"\nNext: {next_command}")
    elif payload.get("apply_safe") is False:
        lines.append("\nNo apply command: resolve the identity ambiguity first.")
    return "\n".join(lines)


def _allocation_conflict_repair_dry_run_human(
    payload: dict[str, object],
) -> str:
    actions_raw = payload.get("actions", [])
    actions = actions_raw if isinstance(actions_raw, list) else []
    lines = [f"IDENTITY CONFLICT REPAIR (dry-run): {len(actions)} action(s)"]
    for action in actions:
        if not isinstance(action, dict):
            continue
        lines.append(
            f"  {action.get('legacy_task_id', action.get('identity'))} "
            f"mode={action.get('repair_mode')} "
            f"evidence={action.get('evidence_status')}"
        )
        if action.get("requires_operator_override"):
            lines.append("    requires --allow-unverifiable")
        reason = action.get("reason")
        if isinstance(reason, str) and reason:
            lines.append(f"    reason={reason}")
    plan_id = payload.get("plan_id")
    if isinstance(plan_id, str):
        lines.append(f"plan_id: {plan_id}")
    transaction_id = payload.get("transaction_id")
    if isinstance(transaction_id, str):
        lines.append(f"transaction_id: {transaction_id}")
    next_command = payload.get("next_command")
    if isinstance(next_command, str) and next_command:
        lines.append(f"Next: {next_command}")
    elif not actions:
        lines.append("No identity conflicts are available to repair.")
    else:
        lines.append("No apply command: resolve the identity ambiguity first.")
    return "\n".join(lines)


def _list_allocation_transactions(
    ctx: typer.Context,
    state: CLIState,
    *,
    requested: bool,
    apply: bool,
    reason: str,
    plan_id: str | None,
    task_id: str | None,
    all_allocations: bool,
    recover: str | None,
    reconcile_source_id: str | None,
    tombstone_id: str | None,
    conflicts: bool,
    allow_unverifiable: bool,
) -> bool:
    if not requested:
        return False
    if any(
        (
            apply,
            bool(reason),
            plan_id is not None,
            task_id is not None,
            all_allocations,
            recover is not None,
            reconcile_source_id is not None,
            tombstone_id is not None,
            conflicts,
            allow_unverifiable,
        )
    ):
        raise LaunchError("--transactions cannot be combined with repair options.")
    from taskledger.api.repair import list_allocation_repair_transactions

    payload = list_allocation_repair_transactions(state.cwd)
    transaction_rows = payload.get("transactions", [])
    count = len(transaction_rows) if isinstance(transaction_rows, list) else 0
    emit_payload(ctx, payload, human=f"allocation repair transactions: {count}")
    return True


def _recover_allocation_transaction(
    ctx: typer.Context,
    state: CLIState,
    transaction_id: str,
    *,
    apply: bool,
    plan_id: str | None,
    reason: str,
) -> None:
    if not apply and (reason or plan_id):
        raise LaunchError("Recovery plan options require --apply.")
    from taskledger.api.repair import recover_allocation_repair_transaction

    payload = recover_allocation_repair_transaction(
        state.cwd,
        transaction_id,
        apply=apply,
        plan_id=plan_id,
        reason=reason,
    )
    if payload.get("dry_run"):
        emit_payload(
            ctx,
            payload,
            human=(
                f"allocation transaction recovery plan: {payload.get('action')} "
                f"({payload.get('phase')})\nNext: {payload.get('next_command')}"
            ),
        )
        return

    status = str(payload.get("status", "unknown"))
    if status in {"rollback_incomplete", "audit_pending", "failed"}:
        error = LaunchError(
            f"Allocation transaction recovery did not complete: {status}.",
            code="TASKLEDGER_ALLOCATION_REPAIR_FAILED",
            details=payload,
        )
        emit_error(ctx, error)
        raise typer.Exit(code=launch_error_exit_code(error)) from error
    emit_payload(
        ctx,
        payload,
        human=f"allocation transaction recovery: {status}",
    )


def _identity_conflict_repair_payload(
    state: CLIState,
    *,
    requested: bool,
    allow_unverifiable: bool,
    apply: bool,
    plan_id: str | None,
    reason: str,
    task_id: str | None,
    all_allocations: bool,
    reconcile_source_id: str | None,
    tombstone_id: str | None,
) -> dict[str, object] | None:
    if allow_unverifiable and not requested:
        raise LaunchError("--allow-unverifiable requires --conflicts.")
    if not requested:
        return None
    if task_id is not None or reconcile_source_id is not None:
        raise LaunchError(
            "Conflict repair cannot combine with allocation or "
            "reconciliation selectors."
        )
    if all_allocations and tombstone_id is not None:
        raise LaunchError("Choose either --all or --tombstone-id for conflict repair.")
    from taskledger.api.repair import repair_allocation_conflicts

    return repair_allocation_conflicts(
        state.cwd,
        apply=apply,
        plan_id=plan_id,
        reason=reason,
        allow_unverifiable=allow_unverifiable,
        tombstone_id=tombstone_id,
    )


def _validate_allocation_audit_options(
    *,
    conflicts: bool,
    allow_unverifiable: bool,
    apply: bool,
    reason: str,
    task_id: str | None,
    all_allocations: bool,
    plan_id: str | None,
    reconcile_source_id: str | None,
    tombstone_id: str | None,
    transactions: bool,
    recover: str | None,
) -> None:
    if any(
        (
            conflicts,
            allow_unverifiable,
            apply,
            bool(reason),
            task_id is not None,
            all_allocations,
            plan_id is not None,
            reconcile_source_id is not None,
            tombstone_id is not None,
            transactions,
            recover is not None,
        )
    ):
        raise LaunchError(
            "--audit cannot be combined with repair or reconciliation options."
        )


def _emit_allocation_repair_result(
    ctx: typer.Context, state: CLIState, payload: dict[str, object]
) -> None:
    if payload.get("kind") == "task_allocation_conflict_repair" and payload.get(
        "dry_run"
    ):
        emit_payload(
            ctx,
            payload,
            human=_allocation_conflict_repair_dry_run_human(payload),
        )
    elif payload.get("kind") == "task_allocation_tombstone_reconciliation":
        status = str(payload.get("status", "unknown"))
        human = f"allocation tombstone reconciliation: {status}"
        warning = payload.get("warning")
        if isinstance(warning, str) and warning:
            human += f"\nwarning: {warning}"
        next_command = payload.get("next_command")
        if isinstance(next_command, str):
            human += f"\nNext: {next_command}"
        emit_payload(ctx, payload, human=human)
    elif payload.get("dry_run"):
        emit_payload(
            ctx,
            payload,
            human=_allocation_repair_dry_run_human(payload),
        )
    else:
        repaired_raw = payload.get("repaired", [])
        repaired = repaired_raw if isinstance(repaired_raw, list) else []
        failed_raw = payload.get("failed", [])
        failed = failed_raw if isinstance(failed_raw, list) else []
        repaired_count_raw = payload.get("repaired_count", len(repaired))
        failed_count_raw = payload.get("failed_count", len(failed))
        attempted_raw = payload.get("attempted_count", len(repaired) + len(failed))
        repaired_count = (
            repaired_count_raw if isinstance(repaired_count_raw, int) else len(repaired)
        )
        failed_count = max(
            failed_count_raw if isinstance(failed_count_raw, int) else 0,
            len(failed),
        )
        attempted_count = (
            attempted_raw
            if isinstance(attempted_raw, int)
            else repaired_count + failed_count
        )
        status = str(payload.get("status", "unknown"))
        ledger_healthy = payload.get("ledger_healthy")
        ledger_state = (
            "ledger healthy"
            if ledger_healthy is True
            else "ledger still blocked"
            if ledger_healthy is False
            else "ledger status unknown"
        )
        summary = (
            f"{attempted_count} planned · {repaired_count} committed · "
            f"{failed_count} failed · {ledger_state}"
        )
        if failed_count > 0 or status != "applied" or attempted_count > repaired_count:
            error_data: dict[str, object] = {
                "status": status,
                "plan_id": payload.get("plan_id"),
                "transaction_id": payload.get("transaction_id"),
                "attempted_count": attempted_count,
                "repaired_count": repaired_count,
                "failed_count": failed_count,
                "repaired": repaired,
                "failed": failed,
                "rollback_state": status,
                "rollback_errors": payload.get("rollback_errors", []),
                "journal_path": payload.get("journal_path"),
                "ledger_healthy": ledger_healthy,
                "remaining_conflicts": payload.get("remaining_conflicts", []),
                "audit_errors": payload.get("audit_errors", []),
            }
            next_commands = payload.get("next_commands", [])
            next_command = payload.get("next_command")
            remediation = (
                [str(next_commands[0])]
                if isinstance(next_commands, list) and next_commands
                else [next_command]
                if isinstance(next_command, str)
                else ["Inspect the transaction journal and run a fresh Doctor report."]
            )
            error = LaunchError(
                f"Allocation repair failed: {summary} (status={status}).",
                code="TASKLEDGER_ALLOCATION_REPAIR_FAILED",
                details=error_data,
                remediation=remediation,
            )
            if not state.json_output:
                typer.echo(summary, err=True)
                for item in failed:
                    if isinstance(item, dict):
                        typer.echo(
                            f"  failed: {item.get('source_id', item.get('task_id'))}: "
                            f"{item.get('error')}",
                            err=True,
                        )
            emit_error(ctx, error)
            raise typer.Exit(code=launch_error_exit_code(error)) from error

        emit_payload(ctx, payload, human=summary)


def repair_allocations_command(
    ctx: typer.Context,
    apply: Annotated[
        bool, typer.Option("--apply", help="Apply repairs (default is dry-run).")
    ] = False,
    conflicts: Annotated[
        bool,
        typer.Option(
            "--conflicts",
            help="Plan or apply repairs for authoritative identity conflicts.",
        ),
    ] = False,
    allow_unverifiable: Annotated[
        bool,
        typer.Option(
            "--allow-unverifiable",
            help="Allow reviewed retirement of unverifiable shadowing tombstones.",
        ),
    ] = False,
    reason: Annotated[
        str, typer.Option("--reason", help="Reason for quarantining allocations.")
    ] = "",
    task_id: Annotated[
        str | None, typer.Option("--task-id", help="Physical legacy ID or UUID source.")
    ] = None,
    all_allocations: Annotated[
        bool, typer.Option("--all", help="Apply to all incomplete allocations.")
    ] = False,
    plan_id: Annotated[
        str | None, typer.Option("--plan-id", help="Reviewed dry-run plan fingerprint.")
    ] = None,
    audit: Annotated[
        bool, typer.Option("--audit", help="Audit prior allocation repair provenance.")
    ] = False,
    transactions: Annotated[
        bool,
        typer.Option("--transactions", help="List allocation repair transactions."),
    ] = False,
    recover: Annotated[
        str | None,
        typer.Option("--recover", help="Review or recover a transaction ID."),
    ] = None,
    reconcile_source_id: Annotated[
        str | None,
        typer.Option(
            "--reconcile-source-id", help="Evidence-backed physical source ID."
        ),
    ] = None,
    tombstone_id: Annotated[
        str | None,
        typer.Option("--tombstone-id", help="Misattributed tombstone ID to correct."),
    ] = None,
) -> None:
    from taskledger.api.repair import (
        audit_allocation_repairs,
        reconcile_allocation_tombstone,
        repair_allocations,
    )

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        if audit:
            _validate_allocation_audit_options(
                conflicts=conflicts,
                allow_unverifiable=allow_unverifiable,
                apply=apply,
                reason=reason,
                task_id=task_id,
                all_allocations=all_allocations,
                plan_id=plan_id,
                reconcile_source_id=reconcile_source_id,
                tombstone_id=tombstone_id,
                transactions=transactions,
                recover=recover,
            )
            payload = audit_allocation_repairs(state.cwd)
            entries_raw = payload.get("entries", [])
            entries = entries_raw if isinstance(entries_raw, list) else []
            summary = payload.get("summary", {})
            lines = [f"allocation repair provenance audit: {len(entries)} event(s)"]
            if isinstance(summary, dict):
                lines.extend(f"  {key}: {value}" for key, value in summary.items())
            emit_payload(ctx, payload, human="\n".join(lines))
            return

        if _list_allocation_transactions(
            ctx,
            state,
            requested=transactions,
            apply=apply,
            reason=reason,
            plan_id=plan_id,
            task_id=task_id,
            all_allocations=all_allocations,
            recover=recover,
            reconcile_source_id=reconcile_source_id,
            tombstone_id=tombstone_id,
            conflicts=conflicts,
            allow_unverifiable=allow_unverifiable,
        ):
            return

        if recover is not None:
            if (
                conflicts
                or allow_unverifiable
                or task_id is not None
                or all_allocations
                or transactions
                or reconcile_source_id
                or tombstone_id
            ):
                raise LaunchError(
                    "--recover cannot be combined with allocation selectors."
                )
            _recover_allocation_transaction(
                ctx,
                state,
                recover,
                apply=apply,
                plan_id=plan_id,
                reason=reason,
            )
            return

        conflict_payload = _identity_conflict_repair_payload(
            state,
            requested=conflicts,
            allow_unverifiable=allow_unverifiable,
            apply=apply,
            plan_id=plan_id,
            reason=reason,
            task_id=task_id,
            all_allocations=all_allocations,
            reconcile_source_id=reconcile_source_id,
            tombstone_id=tombstone_id,
        )
        if conflict_payload is not None:
            payload = conflict_payload
        elif reconcile_source_id is not None or tombstone_id is not None:
            if reconcile_source_id is None or tombstone_id is None:
                raise LaunchError(
                    "Tombstone reconciliation requires both --reconcile-source-id "
                    "and --tombstone-id."
                )
            if task_id is not None or all_allocations:
                raise LaunchError(
                    "Tombstone reconciliation cannot combine with allocation selectors."
                )
            payload = reconcile_allocation_tombstone(
                state.cwd,
                source_id=reconcile_source_id,
                tombstone_id=tombstone_id,
                apply=apply,
                plan_id=plan_id,
                reason=reason,
            )
        else:
            payload = repair_allocations(
                state.cwd,
                apply=apply,
                reason=reason,
                task_id=task_id,
                all_allocations=all_allocations,
                plan_id=plan_id,
            )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    _emit_allocation_repair_result(ctx, state, payload)


def repair_active_task_command(
    ctx: typer.Context,
    action: Annotated[
        str, typer.Option("--action", help="Explicit recovery action: clear or rebind.")
    ] = "clear",
    target_uuid: Annotated[
        str | None,
        typer.Option("--target-uuid", help="Explicit UUIDv7 target for rebind."),
    ] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Apply the reviewed recovery plan.")
    ] = False,
    plan_id: Annotated[
        str | None, typer.Option("--plan-id", help="Reviewed active-task plan ID.")
    ] = None,
    reason: Annotated[
        str, typer.Option("--reason", help="Reason for the active-task recovery.")
    ] = "",
) -> None:
    from taskledger.api.repair import repair_active_task

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = repair_active_task(
            state.cwd,
            action=action,
            target_uuid=target_uuid,
            apply=apply,
            plan_id=plan_id,
            reason=reason,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc

    if apply and payload.get("status") != "applied":
        error = LaunchError(
            f"Active-task recovery did not complete: "
            f"{payload.get('status', 'unknown')}.",
            code="TASKLEDGER_ACTIVE_TASK_REPAIR_FAILED",
            details=payload,
        )
        if not state.json_output:
            typer.echo(
                f"active-task {action}: {payload.get('status')} · "
                "audit or recovery remains pending",
                err=True,
            )
        emit_error(ctx, error)
        raise typer.Exit(code=launch_error_exit_code(error)) from error

    if payload.get("dry_run"):
        inspection = payload.get("inspection", {})
        inspection = inspection if isinstance(inspection, dict) else {}
        lines = [
            (
                "ACTIVE TASK REPAIR (dry-run): "
                f"{inspection.get('classification', 'unknown')}"
            ),
            f"action: {action}",
            f"apply_safe: {payload.get('apply_safe')}",
            f"plan_id: {payload.get('plan_id')}",
        ]
        for key in ("task_id", "task_uuid"):
            value = inspection.get(key)
            if value is not None:
                lines.append(f"{key}: {value}")
        blockers = payload.get("blocked_reasons", [])
        if isinstance(blockers, list):
            for blocker in blockers:
                lines.append(f"blocked: {blocker}")
        candidates = inspection.get("candidates", [])
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, dict):
                    lines.append(
                        f"candidate: {candidate.get('task_uuid')} "
                        f"{candidate.get('path')}"
                    )
        next_command = payload.get("next_command")
        if isinstance(next_command, str):
            lines.append(f"Next: {next_command}")
        emit_payload(ctx, payload, human="\n".join(lines))
        return

    human = (
        f"active-task {action}: {payload.get('status')}\n"
        f"backup: {payload.get('backup_path')}\n"
        f"journal: {payload.get('journal_path')}\n"
        f"Next: {payload.get('next_command')}"
    )
    emit_payload(ctx, payload, human=human)


def repair_project_identity_command(
    ctx: typer.Context,
    apply: Annotated[
        bool, typer.Option("--apply", help="Generate and persist a project UUID.")
    ] = False,
    project_uuid: Annotated[
        str | None,
        typer.Option("--project-uuid", help="Explicit UUID to set."),
    ] = None,
) -> None:
    from taskledger.api.repair import repair_project_identity

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = repair_project_identity(
            state.cwd, apply=apply, project_uuid=project_uuid
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    status = payload.get("status", "unknown")
    config_path = payload.get("config_path", "")
    uuid_val = payload.get("project_uuid")
    lines = [
        "PROJECT IDENTITY",
        f"status: {status}",
        f"config: {config_path}",
        f"uuid: {uuid_val}",
    ]
    if payload.get("changed"):
        lines.append("changed: yes")
        next_commands_raw = payload.get("next_commands", [])
        next_commands = next_commands_raw if isinstance(next_commands_raw, list) else []
        for cmd in next_commands:
            lines.append(f"next: {cmd}")
    elif status == "missing":
        lines.append("action: generate and persist a UUID")
        next_cmd = payload.get("next_command")
        if next_cmd:
            lines.append(f"next: {next_cmd}")
    emit_payload(ctx, payload, human="\n".join(lines))


def repair_task_command(
    ctx: typer.Context,
    reason: Annotated[str, typer.Option("--reason")],
    task_ref: Annotated[
        str | None,
        typer.Option("--task", help="Task ref. Defaults to the active task."),
    ] = None,
) -> None:
    from taskledger.api.tasks import repair_task_record

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = repair_task_record(state.cwd, task.id, reason=reason)
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    human_lines = [f"recorded repair inspection for {payload['task_id']}"]
    for warning in cast(list[str], payload.get("warnings", [])):
        human_lines.append(f"warning: {warning}")
    for command in cast(list[str], payload.get("recovery_commands", [])):
        human_lines.append(f"recovery: {command}")
    emit_payload(ctx, payload, human="\n".join(human_lines))


def repair_run_command(
    ctx: typer.Context,
    reason: Annotated[str, typer.Option("--reason")],
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    task_ref: Annotated[
        str | None,
        typer.Option("--task", help="Task ref. Defaults to the active task."),
    ] = None,
) -> None:
    from taskledger.api.tasks import repair_orphaned_planning_run

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = repair_orphaned_planning_run(
            state.cwd,
            task.id,
            run_id=run_id,
            reason=reason,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    emit_payload(
        ctx,
        payload,
        human=(
            f"finished orphaned {payload['run_type']} run {payload['run_id']} "
            f"for {payload['task_id']}\nnext: {payload['next_command']}"
        ),
    )


def repair_planning_command_changes_command(
    ctx: typer.Context,
    reason: Annotated[str, typer.Option("--reason")],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show what would be repaired without making changes.",
        ),
    ] = False,
    task_ref: Annotated[
        str | None,
        typer.Option("--task", help="Task ref. Defaults to the active task."),
    ] = None,
) -> None:
    from taskledger.api.tasks import repair_planning_command_changes

    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        task = resolve_cli_task(state.cwd, task_ref)
        payload = repair_planning_command_changes(
            state.cwd,
            task.id,
            reason=reason,
            dry_run=dry_run,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    repaired = cast(list[str], payload.get("repaired_changes", []))
    dry_run_str = " (dry run)" if payload.get("dry_run") else ""
    if repaired:
        human_lines = [
            f"repaired {len(repaired)} planning command changes{dry_run_str}:",
        ]
        for change_id in repaired:
            human_lines.append(f"  - {change_id}")
        human = "\n".join(human_lines)
    else:
        human = f"no planning command changes to repair{dry_run_str}"
    emit_payload(ctx, payload, human=human)


def repair_relation_command(
    ctx: typer.Context,
    task_uuid: Annotated[
        str,
        typer.Option("--task-uuid", help="UUID of the task containing the relation."),
    ],
    field: Annotated[
        str,
        typer.Option(
            "--field",
            help="Relation UUID field: parent_task_uuid or required_task_uuid.",
        ),
    ],
    requirement_id: Annotated[
        str | None,
        typer.Option("--requirement-id", help="Target a requirement sidecar record."),
    ] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Apply the reviewed dry-run plan.")
    ] = False,
    plan_id: Annotated[
        str | None, typer.Option("--plan-id", help="Reviewed dry-run plan ID.")
    ] = None,
    reason: Annotated[
        str, typer.Option("--reason", help="Reason for repairing this relation.")
    ] = "",
) -> None:
    from taskledger.api.repair import repair_task_relation

    state = cli_state_from_context(ctx)
    try:
        payload = repair_task_relation(
            state.cwd,
            task_uuid=task_uuid,
            field=field,
            requirement_id=requirement_id,
            apply=apply,
            plan_id=plan_id,
            reason=reason,
        )
    except LaunchError as exc:
        emit_error(ctx, exc)
        raise typer.Exit(code=launch_error_exit_code(exc)) from exc
    status = str(payload.get("status", "unknown"))
    human_lines = [f"task relation repair: {status}"]
    if isinstance(payload.get("field"), str):
        human_lines.append(f"field: {payload['field']}")
    if isinstance(payload.get("source_path"), str):
        human_lines.append(f"source: {payload['source_path']}")
    if isinstance(payload.get("target_task_uuid"), str):
        human_lines.append(f"target: {payload['target_task_uuid']}")
    if isinstance(payload.get("plan_id"), str):
        human_lines.append(f"plan_id: {payload['plan_id']}")
    if isinstance(payload.get("audit_event_id"), str):
        human_lines.append(f"audit_event_id: {payload['audit_event_id']}")
    emit_payload(ctx, payload, human="\n".join(human_lines))


def repair_task_dirs_command(ctx: typer.Context) -> None:
    from taskledger.services.doctor import cleanup_orphan_slug_dirs

    state = ctx.obj
    assert isinstance(state, CLIState)
    payload = cleanup_orphan_slug_dirs(state.cwd)
    removed = cast(list[str], payload.get("removed", []))
    names = ", ".join(removed) if removed else "(none)"
    emit_payload(
        ctx,
        payload,
        human=f"removed {payload['count']} orphan slug directories: {names}",
    )


def register_repair_commands(repair_app: typer.Typer, doctor_app: typer.Typer) -> None:
    doctor_app.callback()(doctor_command)
    doctor_app.command("locks")(doctor_locks_command)
    doctor_app.command("schema")(doctor_schema_command)
    doctor_app.command("indexes")(doctor_indexes_command)
    repair_app.command("index")(repair_index_command)
    repair_app.command("lock")(repair_lock_command)
    repair_app.command("locks")(repair_locks_command)
    repair_app.command("allocations")(repair_allocations_command)
    repair_app.command("active-task")(repair_active_task_command)
    repair_app.command("relation")(repair_relation_command)
    repair_app.command("project-identity")(repair_project_identity_command)
    repair_app.command("task")(repair_task_command)
    repair_app.command("run")(repair_run_command)
    repair_app.command("planning-command-changes")(
        repair_planning_command_changes_command
    )
    repair_app.command("task-dirs")(repair_task_dirs_command)
