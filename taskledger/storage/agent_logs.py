from __future__ import annotations

import json
from pathlib import Path

from taskledger.domain.models import AgentCommandLogRecord
from taskledger.errors import LaunchError
from taskledger.storage.atomic import atomic_write_text
from taskledger.storage.task_store import V2Paths, require_v2_layout, resolve_v2_paths


def agent_logs_dir(paths: V2Paths) -> Path:
    return paths.events_dir.parent / "agent-logs"


def agent_log_artifacts_dir(paths: V2Paths) -> Path:
    return agent_logs_dir(paths) / "artifacts"


def append_agent_command_log(
    workspace_root: Path,
    record: AgentCommandLogRecord,
) -> Path:
    paths = require_v2_layout(workspace_root)
    logs_dir = agent_logs_dir(paths)
    logs_dir.mkdir(parents=True, exist_ok=True)
    agent_log_artifacts_dir(paths).mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"{record.started_at[:10]}.ndjson"
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
    except OSError as exc:
        raise LaunchError(f"Failed to append agent command log {path}: {exc}") from exc
    return path


def load_agent_command_logs(
    workspace_root: Path,
    *,
    task_id: str | None = None,
    run_id: str | None = None,
    limit: int | None = None,
    strict_duplicates: bool = False,
) -> list[AgentCommandLogRecord]:
    if limit is not None and limit <= 0:
        return []
    paths = resolve_v2_paths(workspace_root)
    logs_dir = agent_logs_dir(paths)
    if not logs_dir.exists():
        return []

    seen_ids: set[str] = set()
    records: list[AgentCommandLogRecord] = []
    for path in sorted(logs_dir.glob("*.ndjson")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise LaunchError(
                f"Failed to read agent command log {path}: {exc}"
            ) from exc
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LaunchError(
                    f"Failed to read agent command log {path}: {exc}"
                ) from exc
            if not isinstance(payload, dict):
                continue
            record = AgentCommandLogRecord.from_dict(payload)
            if record.log_id in seen_ids:
                if strict_duplicates:
                    raise LaunchError(
                        f"Duplicate agent command log id detected: {record.log_id}"
                    )
                continue
            seen_ids.add(record.log_id)
            if task_id is not None and record.task_id != task_id:
                continue
            if run_id is not None and record.run_id != run_id:
                continue
            records.append(record)

    records = sorted(records, key=lambda item: (item.started_at, item.log_id))
    if limit is not None:
        return records[-limit:]
    return records


def detect_duplicate_log_ids(
    workspace_root: Path,
    *,
    task_id: str | None = None,
) -> list[str]:
    """Return log IDs that appear more than once for the given task."""
    paths = resolve_v2_paths(workspace_root)
    logs_dir = agent_logs_dir(paths)
    if not logs_dir.exists():
        return []

    id_counts: dict[str, int] = {}
    for path in sorted(logs_dir.glob("*.ndjson")):
        try:
            file_lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in file_lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            log_id = payload.get("log_id")
            if not isinstance(log_id, str):
                continue
            if task_id is not None and payload.get("task_id") != task_id:
                continue
            id_counts[log_id] = id_counts.get(log_id, 0) + 1

    return sorted(lid for lid, count in id_counts.items() if count > 1)


def write_agent_command_artifact(
    workspace_root: Path,
    *,
    log_id: str,
    suffix: str,
    content: str,
) -> str:
    paths = require_v2_layout(workspace_root)
    artifacts_dir = agent_log_artifacts_dir(paths)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    safe_suffix = suffix.replace("/", "-").replace("\\", "-")
    artifact_path = artifacts_dir / f"{log_id}.{safe_suffix}"
    atomic_write_text(artifact_path, content)
    try:
        return str(artifact_path.relative_to(paths.project_dir))
    except ValueError:
        return f"logs/{artifact_path.relative_to(paths.events_dir.parent)}"


__all__ = [
    "agent_log_artifacts_dir",
    "agent_logs_dir",
    "append_agent_command_log",
    "detect_duplicate_log_ids",
    "load_agent_command_logs",
    "write_agent_command_artifact",
]
