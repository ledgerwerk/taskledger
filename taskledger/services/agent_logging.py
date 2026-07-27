from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import typer

from taskledger.cli_common import _error_code, _task_id_from_value
from taskledger.command_inventory import COMMAND_METADATA, HUMAN_ORIENTED
from taskledger.domain.models import ActorRef, AgentCommandLogRecord, HarnessRef
from taskledger.errors import LaunchError
from taskledger.storage.agent_logs import (
    append_agent_command_log,
    load_agent_command_logs,
    write_agent_command_artifact,
)
from taskledger.storage.project_config import (
    AgentLoggingConfig,
    load_project_config_overrides,
    merge_project_config,
)
from taskledger.storage.task_store import (
    load_harness_state,
    resolve_lock,
    resolve_v2_paths,
)
from taskledger.timeutils import utc_now_iso

_current_recorder: ContextVar[AgentCommandRecorder | None] = ContextVar(
    "taskledger_agent_command_recorder",
    default=None,
)

_SAFE_READ_ONLY = "safe_read_only"
_LEDGER_MUTATION = "ledger_mutation"
_TRUTHY = {"1", "true", "yes", "on"}
_GLOBAL_VALUE_OPTIONS = {"--cwd", "--root"}
_GLOBAL_BOOL_OPTIONS = {"--json", "--no-log", "--version"}
_HELP_FLAGS = {"--help", "-h", "--show-completion", "--install-completion"}


def _env_no_log() -> bool:
    """Check if TASKLEDGER_NO_LOG environment variable is set to a truthy value."""
    value = os.environ.get("TASKLEDGER_NO_LOG", "")
    return value.strip().lower() in _TRUTHY


def _command_key_from_argv(argv: tuple[str, ...]) -> str | None:
    """Extract the command key from argv, handling global options."""
    parts: list[str] = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue

        if arg in _GLOBAL_VALUE_OPTIONS:
            skip_next = True
            continue
        if any(arg.startswith(f"{opt}=") for opt in _GLOBAL_VALUE_OPTIONS):
            continue
        if arg in _GLOBAL_BOOL_OPTIONS:
            continue

        # Stop before command-specific options.
        if arg.startswith("-"):
            continue

        parts.append(arg)
        if len(parts) >= 2:
            break

    if not parts:
        return None

    # Prefer the longest metadata match.
    two = " ".join(parts[:2])
    if len(parts) >= 2 and two in COMMAND_METADATA:
        return two
    one = parts[0]
    if one in COMMAND_METADATA:
        return one
    return one


def _should_skip_cli_recording(
    *,
    argv: tuple[str, ...],
    config: AgentLoggingConfig,
    no_log: bool,
) -> bool:
    """Determine whether CLI recording should be skipped."""
    if _HELP_FLAGS.intersection(argv):
        return True
    if no_log or _env_no_log():
        return True
    if not config.enabled or not config.capture_taskledger_cli:
        return True

    command_key = _command_key_from_argv(argv)
    if command_key is None:
        return False

    metadata = COMMAND_METADATA.get(command_key)
    if metadata is None:
        # Conservative default: unknown commands remain logged.
        return False

    if metadata.audience == HUMAN_ORIENTED and not config.capture_human_oriented:
        return True
    # Use new effect fields when available, fall back to legacy effect.
    has_process_exec = metadata.external_effect == "process_exec"
    is_read_only = (
        metadata.ledger_effect in ("", "none", "read")
        and metadata.workspace_effect in ("", "none", "read")
        and metadata.external_effect in ("", "none")
    )
    # Process exec commands are always logged regardless of config.
    if has_process_exec:
        return False
    if is_read_only and not config.capture_safe_read_only:
        return True
    if not is_read_only and metadata.effect == _SAFE_READ_ONLY:
        # Legacy classification says safe_read_only but new fields disagree.
        # Trust the new fields.
        return False
    return False


class TeeTextStream:
    def __init__(self, wrapped: TextIO, sink: Callable[[str], None]) -> None:
        self._wrapped = wrapped
        self._sink = sink

    def write(self, text: str) -> int:
        self._sink(text)
        return self._wrapped.write(text)

    def flush(self) -> None:
        self._wrapped.flush()

    @property
    def encoding(self) -> str | None:
        return self._wrapped.encoding

    def isatty(self) -> bool:
        return self._wrapped.isatty()

    def fileno(self) -> int:
        return self._wrapped.fileno()

    def __getattr__(self, name: str) -> object:
        return getattr(self._wrapped, name)


@dataclass(slots=True)
class _CaptureBuffers:
    stdout: str = ""
    stderr: str = ""


class AgentCommandRecorder:
    def __init__(
        self,
        *,
        workspace_root: Path,
        argv: tuple[str, ...],
        json_output: bool,
        config: AgentLoggingConfig,
    ) -> None:
        self.workspace_root = workspace_root
        self.argv = argv
        self.json_output = json_output
        self.config = config
        self.started_at = utc_now_iso()
        self._started_monotonic = time.monotonic()
        self._buffers = _CaptureBuffers()
        self._stdout_original = sys.stdout
        self._stderr_original = sys.stderr
        self._stdout_tee: TeeTextStream | None = None
        self._stderr_tee: TeeTextStream | None = None
        self._redactions: list[str] = []
        self._compiled_redactions = [
            (pattern, re.compile(pattern)) for pattern in self.config.redact_patterns
        ]

        self.task_id: str | None = None
        self.run_id: str | None = None
        self.run_type: str | None = None
        self.active_stage: str | None = None
        self.actor: ActorRef | None = None
        self.harness: HarnessRef | None = None
        self.operation_name: str | None = None

        self.status: str = "unknown"
        self.exit_code: int | None = None
        self.payload_kind: str | None = None
        self.payload_ref: str | None = None
        self.error_code: str | None = None
        self.error_summary: str | None = None

    def install_streams(self) -> None:
        self._stdout_tee = TeeTextStream(self._stdout_original, self._capture_stdout)
        self._stderr_tee = TeeTextStream(self._stderr_original, self._capture_stderr)
        sys.stdout = self._stdout_tee
        sys.stderr = self._stderr_tee

    def note_task(self, task_id: str) -> None:
        self.task_id = task_id
        lock = resolve_lock(self.workspace_root, task_id)
        if lock is None:
            return
        self.run_id = lock.run_id
        self.run_type = lock.run_type
        self.active_stage = lock.stage
        self.actor = lock.actor or lock.holder
        self.harness = lock.harness

    def note_payload(
        self,
        payload: object,
        *,
        operation_name: str | None = None,
    ) -> None:
        if operation_name:
            self.operation_name = operation_name
        self.payload_kind = _payload_kind(payload)
        task_id = _task_id_from_value(payload)
        if isinstance(task_id, str) and self.task_id is None:
            self.task_id = task_id
            self.note_task(task_id)
        self.status = "succeeded"
        self.exit_code = 0
        if not self.config.capture_payload_metadata:
            return
        payload_text = _json_text(payload)
        payload_text = self._apply_redactions(payload_text)
        payload_text = _truncate_artifact(payload_text, self.config.max_artifact_bytes)
        if not payload_text:
            return
        log_id = _next_log_id(self.workspace_root, self.started_at)
        self.payload_ref = write_agent_command_artifact(
            self.workspace_root,
            log_id=log_id,
            suffix="payload.json",
            content=payload_text,
        )

    def note_error(
        self,
        error: Exception | str,
        *,
        exit_code: int | None = None,
    ) -> None:
        self.status = "failed"
        self.exit_code = exit_code if exit_code is not None else 1
        self.error_code = _error_code(error, explicit_exit_code=self.exit_code)
        self.error_summary = str(error)

    def finish(self) -> None:
        self._restore_streams()
        finished_at = utc_now_iso()
        duration_ms = max(0, int((time.monotonic() - self._started_monotonic) * 1000))
        stdout_text = self._apply_redactions(self._buffers.stdout)
        stderr_text = self._apply_redactions(self._buffers.stderr)
        combined_text = _combined_output(stdout_text, stderr_text)

        stdout_excerpt, stdout_ref = _capture_output_piece(
            workspace_root=self.workspace_root,
            log_id=_next_log_id(self.workspace_root, self.started_at),
            suffix="stdout.txt",
            content=stdout_text,
            enabled=self.config.capture_visible_stdout,
            config=self.config,
        )
        stderr_excerpt, stderr_ref = _capture_output_piece(
            workspace_root=self.workspace_root,
            log_id=_next_log_id(self.workspace_root, self.started_at),
            suffix="stderr.txt",
            content=stderr_text,
            enabled=self.config.capture_visible_stderr,
            config=self.config,
        )
        combined_excerpt, combined_ref = _capture_output_piece(
            workspace_root=self.workspace_root,
            log_id=_next_log_id(self.workspace_root, self.started_at),
            suffix="combined.txt",
            content=combined_text,
            enabled=self.config.capture_visible_combined,
            config=self.config,
        )

        if self.status == "unknown":
            if self.error_summary is not None:
                self.status = "failed"
            else:
                self.status = "succeeded"
        if self.exit_code is None:
            self.exit_code = 0 if self.status == "succeeded" else 1

        if self.harness is None:
            harness_state = load_harness_state(self.workspace_root)
            if harness_state is not None:
                self.harness = HarnessRef(
                    harness_id="harness-active",
                    name=harness_state.name,
                    kind=harness_state.kind,
                    session_id=harness_state.session_id,
                )

        record = AgentCommandLogRecord(
            log_id=_next_log_id(self.workspace_root, self.started_at),
            ledger_ref=resolve_v2_paths(self.workspace_root).ledger_ref,
            started_at=self.started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            command_kind="taskledger_cli",
            argv=self.argv,
            command_line=(shlex.join(self.argv) if self.argv else "taskledger"),
            cwd=str(self.workspace_root),
            exit_code=self.exit_code,
            status=self.status,  # type: ignore[arg-type]
            task_id=self.task_id,
            run_id=self.run_id,
            run_type=self.run_type,
            active_stage=self.active_stage,
            actor=self.actor,
            harness=self.harness,
            json_output=self.json_output,
            operation_name=self.operation_name,
            visible_stdout_ref=stdout_ref,
            visible_stderr_ref=stderr_ref,
            visible_combined_ref=combined_ref,
            visible_stdout_excerpt=stdout_excerpt,
            visible_stderr_excerpt=stderr_excerpt,
            visible_combined_excerpt=combined_excerpt,
            payload_ref=self.payload_ref,
            payload_kind=self.payload_kind,
            error_code=self.error_code,
            error_summary=self.error_summary,
            redactions_applied=tuple(self._redactions),
        )
        append_agent_command_log(self.workspace_root, record)

    def _restore_streams(self) -> None:
        if self._stdout_tee is not None:
            sys.stdout = self._stdout_original
            self._stdout_tee = None
        if self._stderr_tee is not None:
            sys.stderr = self._stderr_original
            self._stderr_tee = None

    def _capture_stdout(self, text: str) -> None:
        self._buffers.stdout += text

    def _capture_stderr(self, text: str) -> None:
        self._buffers.stderr += text

    def _apply_redactions(self, text: str) -> str:
        redacted = text
        for pattern_text, pattern in self._compiled_redactions:
            updated = pattern.sub("[REDACTED]", redacted)
            if updated != redacted and pattern_text not in self._redactions:
                self._redactions.append(pattern_text)
            redacted = updated
        return redacted


def start_cli_recorder(
    ctx: typer.Context,
    *,
    workspace_root: Path,
    argv: tuple[str, ...],
    json_output: bool,
    no_log: bool = False,
) -> None:
    try:
        config = _load_agent_logging_config(workspace_root)
    except LaunchError:
        # Discovery and diagnostics must remain usable before a canonical
        # Taskledger registration or initialized data mount exists.
        return
    if _should_skip_cli_recording(argv=argv, config=config, no_log=no_log):
        return
    recorder = AgentCommandRecorder(
        workspace_root=workspace_root,
        argv=argv,
        json_output=json_output,
        config=config,
    )
    recorder.install_streams()
    token = _current_recorder.set(recorder)

    def _close() -> None:
        try:
            recorder.finish()
        except (LaunchError, OSError, TypeError, ValueError):
            if recorder.config.fail_on_logging_error:
                raise
        finally:
            _current_recorder.reset(token)

    ctx.call_on_close(_close)


def note_task(task_id: str) -> None:
    recorder = _current_recorder.get()
    if recorder is None:
        return
    try:
        recorder.note_task(task_id)
    except (LaunchError, OSError, ValueError, TypeError):
        if recorder.config.fail_on_logging_error:
            raise


def note_payload(payload: object, *, operation_name: str | None = None) -> None:
    recorder = _current_recorder.get()
    if recorder is None:
        return
    try:
        recorder.note_payload(payload, operation_name=operation_name)
    except (LaunchError, OSError, ValueError, TypeError):
        if recorder.config.fail_on_logging_error:
            raise


def note_error(error: Exception | str, *, exit_code: int | None = None) -> None:
    recorder = _current_recorder.get()
    if recorder is None:
        return
    recorder.note_error(error, exit_code=exit_code)


def record_managed_shell_command(
    workspace_root: Path,
    *,
    task_id: str,
    run_id: str,
    run_type: str,
    argv: tuple[str, ...],
    exit_code: int,
    stdout: str,
    stderr: str,
) -> None:
    config = _load_agent_logging_config(workspace_root)
    if not config.enabled or not config.capture_managed_shell:
        return

    started_at = utc_now_iso()
    log_id = _next_log_id(workspace_root, started_at)
    stdout_redacted, stdout_patterns = _apply_redactions(stdout, config.redact_patterns)
    stderr_redacted, stderr_patterns = _apply_redactions(stderr, config.redact_patterns)
    combined_redacted = _combined_output(stdout_redacted, stderr_redacted)

    stdout_excerpt, stdout_ref = _capture_output_piece(
        workspace_root=workspace_root,
        log_id=log_id,
        suffix="managed.stdout.txt",
        content=stdout_redacted,
        enabled=config.capture_visible_stdout,
        config=config,
    )
    stderr_excerpt, stderr_ref = _capture_output_piece(
        workspace_root=workspace_root,
        log_id=log_id,
        suffix="managed.stderr.txt",
        content=stderr_redacted,
        enabled=config.capture_visible_stderr,
        config=config,
    )
    combined_excerpt, combined_ref = _capture_output_piece(
        workspace_root=workspace_root,
        log_id=log_id,
        suffix="managed.combined.txt",
        content=combined_redacted,
        enabled=config.capture_visible_combined,
        config=config,
    )

    record = AgentCommandLogRecord(
        log_id=log_id,
        ledger_ref=resolve_v2_paths(workspace_root).ledger_ref,
        started_at=started_at,
        finished_at=started_at,
        duration_ms=0,
        command_kind="managed_shell",
        argv=argv,
        command_line=shlex.join(argv) if argv else "",
        cwd=str(workspace_root),
        exit_code=exit_code,
        status="succeeded" if exit_code == 0 else "failed",
        task_id=task_id,
        run_id=run_id,
        run_type=run_type,
        active_stage={
            "planning": "planning",
            "implementation": "implementing",
            "validation": "validating",
        }.get(run_type),
        managed_stdout_ref=stdout_ref,
        managed_stderr_ref=stderr_ref,
        managed_combined_ref=combined_ref,
        managed_command_exit_code=exit_code,
        visible_stdout_excerpt=stdout_excerpt,
        visible_stderr_excerpt=stderr_excerpt,
        visible_combined_excerpt=combined_excerpt,
        redactions_applied=tuple([*stdout_patterns, *stderr_patterns]),
    )
    append_agent_command_log(workspace_root, record)


def _load_agent_logging_config(workspace_root: Path) -> AgentLoggingConfig:
    from taskledger.storage.paths import resolve_project_paths

    paths = resolve_project_paths(workspace_root)
    overrides = load_project_config_overrides(paths)
    return merge_project_config(overrides).agent_logging


def _next_log_id(workspace_root: Path, timestamp: str) -> str:
    date_prefix = timestamp[:10]
    compact = (
        timestamp.replace(":", "").replace("-", "").replace("+00:00", "Z").split(".")[0]
    )
    logs = load_agent_command_logs(workspace_root, limit=None)
    sequence = 1 + sum(1 for item in logs if item.started_at.startswith(date_prefix))
    return f"cmd-{compact}-{sequence:06d}"


def _payload_kind(payload: object) -> str:
    if isinstance(payload, dict):
        kind = payload.get("kind")
        if isinstance(kind, str) and kind:
            return kind
        return "object"
    if isinstance(payload, list):
        return "collection"
    return type(payload).__name__


def _json_text(payload: object) -> str:
    try:
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError):
        return str(payload)


def _truncate_artifact(content: str, max_bytes: int | None) -> str:
    if max_bytes is None:
        return content
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content
    truncated = encoded[:max_bytes]
    return truncated.decode("utf-8", errors="ignore")


def _combined_output(stdout: str, stderr: str) -> str:
    return (
        "[stdout]\n"
        + (stdout if stdout else "(empty)")
        + "\n\n[stderr]\n"
        + (stderr if stderr else "(empty)")
        + "\n"
    )


def _capture_output_piece(
    *,
    workspace_root: Path,
    log_id: str,
    suffix: str,
    content: str,
    enabled: bool,
    config: AgentLoggingConfig,
) -> tuple[str | None, str | None]:
    if not enabled:
        return None, None
    excerpt = content[: config.max_inline_chars]
    if len(content) > config.max_inline_chars:
        excerpt = excerpt + "\n...[truncated]"
    if not config.store_full_output_artifacts:
        return excerpt, None
    artifact_text = _truncate_artifact(content, config.max_artifact_bytes)
    ref = write_agent_command_artifact(
        workspace_root,
        log_id=log_id,
        suffix=suffix,
        content=artifact_text,
    )
    return excerpt, ref


def _apply_redactions(
    text: str,
    patterns: tuple[str, ...],
) -> tuple[str, list[str]]:
    redacted = text
    applied: list[str] = []
    for pattern_text in patterns:
        pattern = re.compile(pattern_text)
        updated = pattern.sub("[REDACTED]", redacted)
        if updated != redacted and pattern_text not in applied:
            applied.append(pattern_text)
        redacted = updated
    return redacted, applied


__all__ = [
    "note_error",
    "note_payload",
    "note_task",
    "record_managed_shell_command",
    "start_cli_recorder",
]
