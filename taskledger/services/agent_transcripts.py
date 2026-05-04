from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from taskledger.errors import LaunchError
from taskledger.services.workflow_guidance import has_planning_profile
from taskledger.storage.agent_logs import load_agent_command_logs
from taskledger.storage.task_store import resolve_task, resolve_v2_paths


def render_task_transcript(
    workspace_root: Path,
    task_ref: str,
    *,
    format_name: str = "markdown",
    include_output: bool = False,
    mode: str = "table",
    limit: int | None = None,
) -> dict[str, object]:
    if format_name not in {"markdown", "json"}:
        raise LaunchError(f"Unsupported transcript format: {format_name}")
    if mode not in {"table", "review", "failures"}:
        raise LaunchError(f"Unsupported transcript mode: {mode}")
    if format_name == "json" and mode != "table":
        raise LaunchError("JSON transcript mode supports only the default table view.")
    if limit is not None and limit <= 0:
        raise LaunchError("--limit must be a positive integer.")

    task = resolve_task(workspace_root, task_ref)
    logs = load_agent_command_logs(
        workspace_root,
        task_id=task.id,
        limit=limit,
    )

    if format_name == "json":
        return {
            "kind": "task_transcript",
            "task_id": task.id,
            "format": "json",
            "mode": mode,
            "include_output": include_output,
            "limit": limit,
            "logs": [item.to_dict() for item in logs],
        }

    if mode == "review":
        content = _render_review_markdown(workspace_root, task_id=task.id, logs=logs)
    elif mode == "failures":
        content = _render_failures_markdown(task_id=task.id, logs=logs)
    else:
        content = _render_markdown(
            workspace_root,
            task_id=task.id,
            logs=logs,
            include_output=include_output,
        )
    return {
        "kind": "task_transcript",
        "task_id": task.id,
        "format": "markdown",
        "mode": mode,
        "include_output": include_output,
        "limit": limit,
        "content": content,
    }


def _render_markdown(
    workspace_root: Path,
    *,
    task_id: str,
    logs: Sequence[object],
    include_output: bool,
) -> str:
    from taskledger.domain.models import AgentCommandLogRecord

    lines: list[str] = ["## Command Transcript", ""]
    lines.append("| Time | Exit | Kind | Command | Output |")
    lines.append("| --- | ---: | --- | --- | --- |")

    typed_logs = [item for item in logs if isinstance(item, AgentCommandLogRecord)]
    if not typed_logs:
        lines.append("| - | - | - | (no command logs) | - |")
        lines.append("")
        return "\n".join(lines) + "\n"

    for item in typed_logs:
        output_refs = _output_ref_summary(item)
        lines.append(
            "| "
            f"{item.started_at} | "
            f"{item.exit_code if item.exit_code is not None else '-'} | "
            f"{item.command_kind} | "
            f"{item.command_line} | "
            f"{output_refs} |"
        )

    lines.append("")

    if include_output:
        paths = resolve_v2_paths(workspace_root)
        for item in typed_logs:
            lines.append(f"### {item.log_id} — {item.command_line}")
            lines.append("")
            exit_value = item.exit_code if item.exit_code is not None else "-"
            lines.append(f"Exit: {exit_value}")
            lines.append(f"Kind: {item.command_kind}")
            if item.run_id:
                lines.append(f"Run: {item.run_id}")
            lines.append("")

            stdout_text = _output_text(
                paths.project_dir,
                item.managed_stdout_ref
                if item.command_kind == "managed_shell"
                else item.visible_stdout_ref,
                item.visible_stdout_excerpt,
            )
            stderr_text = _output_text(
                paths.project_dir,
                item.managed_stderr_ref
                if item.command_kind == "managed_shell"
                else item.visible_stderr_ref,
                item.visible_stderr_excerpt,
            )

            lines.append("#### stdout")
            lines.append("")
            lines.append("```text")
            lines.append(stdout_text if stdout_text else "(empty)")
            lines.append("```")
            lines.append("")

            lines.append("#### stderr")
            lines.append("")
            lines.append("```text")
            lines.append(stderr_text if stderr_text else "(empty)")
            lines.append("```")
            lines.append("")

    return "\n".join(lines) + "\n"


def _render_review_markdown(
    workspace_root: Path,
    *,
    task_id: str,
    logs: Sequence[object],
) -> str:
    rows = _logical_rows(logs)
    failed_rows = [row for row in rows if row["failed"]]
    retries = _retry_map(rows)
    first_validation_finish = _first_validation_finish_index(rows)
    late_rows = [
        row
        for row in rows
        if (
            first_validation_finish is not None
            and (row_index := _row_index(row)) is not None
            and row_index > first_validation_finish
        )
    ]
    missing_guidance = _missing_planning_guidance(workspace_root, rows)

    lines = ["## Transcript Review", "", "### Summary", ""]
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Task | {task_id} |")
    lines.append(f"| Commands | {len(rows)} |")
    lines.append(f"| Failed commands | {len(failed_rows)} |")
    lines.append(f"| Commands after validation | {len(late_rows)} |")
    lines.append(
        "| Planning guidance during planning | "
        + ("missing" if missing_guidance else "observed / not applicable")
        + " |"
    )
    lines.append("")

    lines.append("### Failures and retries")
    lines.append("")
    lines.append("| Command | Wrapper exit | Managed exit | Retried | |")
    lines.append("| --- | ---: | ---: | --- | --- |")
    if not failed_rows:
        lines.append("| (none) | - | - | - | - |")
    for row in failed_rows:
        row_index = _row_index(row)
        retry_state = (
            "yes" if row_index is not None and retries.get(row_index) else "no"
        )
        lines.append(
            "| "
            f"{row['display_command']} | "
            f"{_cell_int(row.get('wrapper_exit'))} | "
            f"{_cell_int(row.get('managed_exit'))} | "
            f"{retry_state} | "
            f"{row['result']} |"
        )
    lines.append("")

    lines.append("### Late Commands")
    lines.append("")
    lines.append("| Command | Classification |")
    lines.append("| --- | --- |")
    if not late_rows:
        lines.append("| (none) | - |")
    for row in late_rows:
        command = str(row["display_command"])
        classification = _late_command_classification(command)
        lines.append(f"| {command} | {classification} |")
    lines.append("")

    warnings: list[str] = []
    mismatches = [row for row in rows if row.get("mismatch") is True]
    if mismatches:
        warnings.append(
            "Wrapper and managed-shell exits differ for at least one command."
        )
    if missing_guidance:
        warnings.append(
            "Planning guidance was not observed between planning start "
            "and first plan drafting command."
        )
    if warnings:
        lines.append("### Review warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _render_failures_markdown(
    *,
    task_id: str,
    logs: Sequence[object],
) -> str:
    rows = _logical_rows(logs)
    failed_rows = [row for row in rows if row["failed"]]
    retries = _retry_map(rows)

    lines = ["## Transcript Failures", ""]
    lines.append(f"Task: {task_id}")
    lines.append("")
    lines.append("| Command | Wrapper exit | Managed exit | Retried | Result |")
    lines.append("| --- | ---: | ---: | --- | --- |")
    if not failed_rows:
        lines.append("| (none) | - | - | - | - |")
    for row in failed_rows:
        row_index = _row_index(row)
        retry_state = (
            "yes" if row_index is not None and retries.get(row_index) else "no"
        )
        lines.append(
            "| "
            f"{row['display_command']} | "
            f"{_cell_int(row.get('wrapper_exit'))} | "
            f"{_cell_int(row.get('managed_exit'))} | "
            f"{retry_state} | "
            f"{row['result']} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def _logical_rows(logs: Sequence[object]) -> list[dict[str, object]]:
    from taskledger.domain.models import AgentCommandLogRecord

    typed_logs = [item for item in logs if isinstance(item, AgentCommandLogRecord)]
    rows: list[dict[str, object]] = []
    i = 0
    index = 0
    while i < len(typed_logs):
        current = typed_logs[i]
        if _is_wrapper_command(current):
            managed = typed_logs[i + 1] if i + 1 < len(typed_logs) else None
            if isinstance(managed, AgentCommandLogRecord) and _is_wrapper_pair(
                current, managed
            ):
                wrapper_exit = current.exit_code
                managed_exit = managed.exit_code
                if managed_exit is None:
                    managed_exit = managed.managed_command_exit_code
                command_text = managed.command_line
                failed = _is_failed(wrapper_exit) or _is_failed(managed_exit)
                mismatch = (
                    wrapper_exit is not None
                    and managed_exit is not None
                    and wrapper_exit != managed_exit
                )
                result = "failed"
                if not failed:
                    result = "passed"
                elif mismatch:
                    result = "failed, wrapper mismatch"
                rows.append(
                    {
                        "index": index,
                        "started_at": current.started_at,
                        "display_command": command_text,
                        "normalized_command": _normalize_command(command_text),
                        "wrapper_exit": wrapper_exit,
                        "managed_exit": managed_exit,
                        "effective_exit": managed_exit
                        if managed_exit is not None
                        else wrapper_exit,
                        "failed": failed,
                        "mismatch": mismatch,
                        "result": result,
                    }
                )
                i += 2
                index += 1
                continue

        exit_code = current.exit_code
        rows.append(
            {
                "index": index,
                "started_at": current.started_at,
                "display_command": current.command_line,
                "normalized_command": _normalize_command(current.command_line),
                "wrapper_exit": (
                    exit_code if current.command_kind == "taskledger_cli" else None
                ),
                "managed_exit": (
                    exit_code if current.command_kind == "managed_shell" else None
                ),
                "effective_exit": exit_code,
                "failed": _is_failed(exit_code),
                "mismatch": False,
                "result": "failed" if _is_failed(exit_code) else "passed",
            }
        )
        i += 1
        index += 1

    return rows


def _retry_map(rows: Sequence[dict[str, object]]) -> dict[int, bool]:
    retries: dict[int, bool] = {}
    for i, row in enumerate(rows):
        if not row["failed"]:
            continue
        command = str(row["normalized_command"])
        retried = False
        for later in rows[i + 1 :]:
            if str(later["normalized_command"]) == command and not later["failed"]:
                retried = True
                break
        row_index = _row_index(row)
        if row_index is not None:
            retries[row_index] = retried
    return retries


def _first_validation_finish_index(rows: Sequence[dict[str, object]]) -> int | None:
    for row in rows:
        command = str(row["display_command"])
        if command.startswith(
            "taskledger validate finish --result passed"
        ) or command.startswith(
            "taskledger validate finish --result failed",
        ):
            return _row_index(row)
    return None


def _missing_planning_guidance(
    workspace_root: Path,
    rows: Sequence[dict[str, object]],
) -> bool:
    if not has_planning_profile(workspace_root):
        return False
    planning_start = None
    first_plan_work = None
    guidance_seen = False
    for idx, row in enumerate(rows):
        command = str(row["display_command"])
        if planning_start is None and command.startswith("taskledger plan start"):
            planning_start = idx
            continue
        if planning_start is None:
            continue
        if command.startswith("taskledger plan guidance"):
            guidance_seen = True
        if (
            command.startswith("taskledger plan template")
            or command.startswith("taskledger plan upsert")
            or command.startswith("taskledger plan propose")
            or command.startswith("taskledger plan approve")
        ):
            first_plan_work = idx
            break
    if planning_start is None or first_plan_work is None:
        return False
    return not guidance_seen


def _late_command_classification(command: str) -> str:
    normal_prefixes = (
        "taskledger task show",
        "taskledger next-action",
        "taskledger task transcript",
        "taskledger view",
        "taskledger task report",
    )
    suspicious_prefixes = (
        "taskledger plan guidance",
        "taskledger plan upsert",
        "taskledger implement change",
        "taskledger todo done",
        "taskledger validate check",
    )
    if command.startswith(normal_prefixes):
        return "normal review command"
    if command.startswith(suspicious_prefixes):
        return "suspicious lifecycle mutation"
    return "late command"


def _is_wrapper_command(record: object) -> bool:
    from taskledger.domain.models import AgentCommandLogRecord

    if not isinstance(record, AgentCommandLogRecord):
        return False
    if record.command_kind != "taskledger_cli":
        return False
    return (
        " implement command --" in record.command_line
        or " plan command --" in record.command_line
    )


def _is_wrapper_pair(wrapper: object, managed: object) -> bool:
    from taskledger.domain.models import AgentCommandLogRecord

    if not isinstance(wrapper, AgentCommandLogRecord) or not isinstance(
        managed, AgentCommandLogRecord
    ):
        return False
    if managed.command_kind != "managed_shell":
        return False
    wrapper_inner = _wrapper_inner_command(wrapper.command_line)
    return wrapper_inner.strip() == managed.command_line.strip()


def _wrapper_inner_command(command_line: str) -> str:
    if " -- " not in command_line:
        return command_line
    return command_line.split(" -- ", 1)[1]


def _normalize_command(command_line: str) -> str:
    command = _wrapper_inner_command(command_line).strip()
    return " ".join(command.split())


def _is_failed(exit_code: object) -> bool:
    return isinstance(exit_code, int) and exit_code != 0


def _cell_int(value: object) -> str:
    return str(value) if isinstance(value, int) else "-"


def _row_index(row: dict[str, object]) -> int | None:
    value = row.get("index")
    if isinstance(value, int):
        return value
    return None


def _output_ref_summary(record: object) -> str:
    from taskledger.domain.models import AgentCommandLogRecord

    if not isinstance(record, AgentCommandLogRecord):
        return "-"
    refs = [
        record.visible_stdout_ref,
        record.visible_stderr_ref,
        record.visible_combined_ref,
        record.managed_stdout_ref,
        record.managed_stderr_ref,
        record.managed_combined_ref,
    ]
    shown = [ref for ref in refs if isinstance(ref, str)]
    if not shown:
        return "inline"
    return ", ".join(shown)


def _output_text(
    project_dir: Path,
    artifact_ref: str | None,
    excerpt: str | None,
) -> str:
    if artifact_ref:
        path = project_dir / artifact_ref
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            pass
    return excerpt or ""


__all__ = ["render_task_transcript"]
