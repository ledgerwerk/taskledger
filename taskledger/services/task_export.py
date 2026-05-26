"""Compiled task Markdown export service.

Generates a Markdown file with a deterministic body combining a curated
archive report, raw task-bundle record files, and optional source-file
snapshots. The body is deterministic across renders; the front matter
contains generated_at metadata that varies per render.
Read-only: does not mutate storage or append events.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_TEXT_EXTENSIONS = frozenset({".md", ".yaml", ".yml", ".json", ".txt", ".log"})

_LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".md": "markdown",
    ".rst": "rst",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".sh": "bash",
    ".txt": "text",
    ".log": "text",
}

_SKIP_PREFIXES = (
    ".git",
    ".taskledger",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
)


@dataclass(frozen=True)
class TaskMarkdownExportOptions:
    include_source_files: bool = True
    extra_source_files: tuple[str, ...] = ()
    include_command_output: bool = False
    command_log_limit: int = 200
    events_limit: int = 200
    include_empty: bool = True
    max_record_file_bytes: int = 256_000
    max_source_file_bytes: int = 128_000
    max_total_source_bytes: int = 1_000_000


def _fenced(content: str, language: str = "text") -> list[str]:
    """Build fenced code block lines, extending fence length if needed."""
    longest = 3
    for run in re.findall(r"`{3,}", content):
        longest = max(longest, len(run) + 1)
    fence = "`" * longest
    return [f"{fence}{language}", content.rstrip("\n"), fence]


def _language_for(path: Path) -> str:
    return _LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "text")


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_EXTENSIONS


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except OSError:
        return True


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result


def _collect_source_candidates(
    changes: Sequence[object],
    links: Sequence[object],
    plans: Sequence[object],
    extra: tuple[str, ...],
) -> list[str]:
    values: list[str] = []
    from taskledger.domain.change import CodeChangeRecord

    for change in changes:
        if isinstance(change, CodeChangeRecord):
            if change.kind != "command" and change.path:
                values.append(change.path)
    for link in links:
        if hasattr(link, "path"):
            values.append(link.path)
    for plan in plans:
        if hasattr(plan, "files"):
            values.extend(plan.files)
    values.extend(extra)
    return _dedupe_preserve_order(values)


def _resolve_workspace_file(workspace_root: Path, raw: str) -> Path | None:
    value = raw.strip().removeprefix("@")
    if not value:
        return None
    candidate = (
        (workspace_root / value).resolve()
        if not Path(value).is_absolute()
        else Path(value).resolve()
    )
    root = workspace_root.resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    return None


def _should_skip_source(path: Path, workspace_root: Path) -> bool:
    """Return True if path should be skipped as a source snapshot."""
    try:
        rel = path.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        return True
    parts = rel.parts
    if not parts:
        return True
    skipped_parts = set(_SKIP_PREFIXES)
    if any(part in skipped_parts for part in parts):
        return True
    return False


def _collect_raw_bundle_files(
    bundle_dir: Path,
    max_bytes: int,
) -> tuple[list[str], list[str], list[dict[str, str]]]:
    """Collect raw text files from the task bundle directory."""
    included: list[str] = []
    skipped: list[dict[str, str]] = []
    sections: list[str] = []

    raw_files: list[tuple[str, Path]] = []
    if bundle_dir.is_dir():
        for fp in sorted(bundle_dir.rglob("*")):
            if not fp.is_file() or not _is_text_file(fp):
                continue
            try:
                rel = fp.relative_to(bundle_dir)
            except ValueError:
                continue
            raw_files.append((str(rel), fp))

    for rel_path, fp in raw_files:
        try:
            size = fp.stat().st_size
        except OSError:
            skipped.append({"path": rel_path, "reason": "cannot stat file"})
            continue
        if size > max_bytes:
            skipped.append({"path": rel_path, "reason": f"exceeds {max_bytes} bytes"})
            continue
        try:
            text = fp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            skipped.append({"path": rel_path, "reason": "cannot read as UTF-8 text"})
            continue
        included.append(rel_path)
        lang = _language_for(fp)
        sections.append(f"### `{rel_path}`")
        sections.append("")
        sections.extend(_fenced(text, language=lang))
        sections.append("")
    return included, sections, skipped


def _collect_source_snapshots(
    workspace_root: Path,
    task_id: str,
    options: TaskMarkdownExportOptions,
    skipped: list[dict[str, str]],
) -> tuple[list[str], list[str]]:
    """Collect source-file snapshots from changes, links, plans."""
    from taskledger.storage.task_store import (
        list_changes,
        list_plans,
        load_links,
    )

    included: list[str] = []
    sections: list[str] = []
    changes = list_changes(workspace_root, task_id)
    link_collection = load_links(workspace_root, task_id)
    links = link_collection.links if hasattr(link_collection, "links") else []
    plans = list_plans(workspace_root, task_id)
    candidates = _collect_source_candidates(
        changes, links, plans, options.extra_source_files
    )

    total_bytes = 0
    seen_resolved: set[Path] = set()
    for raw_candidate in candidates:
        resolved = _resolve_workspace_file(workspace_root, raw_candidate)
        if resolved is None:
            skipped.append({"path": raw_candidate, "reason": "outside workspace"})
            continue
        if resolved in seen_resolved:
            continue
        seen_resolved.add(resolved)
        if not resolved.is_file():
            skipped.append({"path": raw_candidate, "reason": "not a file or missing"})
            continue
        if _should_skip_source(resolved, workspace_root):
            skipped.append({"path": raw_candidate, "reason": "skipped directory"})
            continue
        if _is_binary(resolved):
            skipped.append({"path": raw_candidate, "reason": "binary file"})
            continue
        try:
            size = resolved.stat().st_size
        except OSError:
            skipped.append({"path": raw_candidate, "reason": "cannot stat"})
            continue
        if size > options.max_source_file_bytes:
            skipped.append(
                {
                    "path": raw_candidate,
                    "reason": (f"exceeds {options.max_source_file_bytes} bytes"),
                }
            )
            continue
        if total_bytes + size > options.max_total_source_bytes:
            skipped.append(
                {
                    "path": raw_candidate,
                    "reason": "exceeds total source budget",
                }
            )
            continue
        total_bytes += size
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            skipped.append({"path": raw_candidate, "reason": "cannot read as UTF-8"})
            continue
        try:
            rel = resolved.relative_to(workspace_root)
            display = str(rel)
        except ValueError:
            display = str(resolved)
        included.append(display)
        lang = _language_for(resolved)
        sections.append(f"### `{display}`")
        sections.append("")
        sections.extend(_fenced(text, language=lang))
        sections.append("")
    return included, sections


def build_task_markdown_export_payload(
    workspace_root: Path,
    task_ref: str,
    *,
    options: TaskMarkdownExportOptions | None = None,
) -> dict[str, object]:
    """Build the export payload: metadata + sections content."""
    if options is None:
        options = TaskMarkdownExportOptions()

    from taskledger.services.task_reports import (
        TaskReportOptions,
        render_task_report,
    )
    from taskledger.storage.task_store import (
        resolve_task,
        resolve_v2_paths,
        task_dir,
    )

    task = resolve_task(workspace_root, task_ref)
    paths = resolve_v2_paths(workspace_root)
    bundle_dir = task_dir(paths, task.id)

    # 1. Curated archive report
    report_payload = render_task_report(
        workspace_root,
        task.id,
        options=TaskReportOptions(
            preset="archive",
            include_sections=("command-log",),
            command_log_limit=options.command_log_limit,
            events_limit=options.events_limit,
            include_command_output=options.include_command_output,
            include_empty=options.include_empty,
        ),
    )
    report_content = report_payload.get("content")
    if not isinstance(report_content, str):
        report_content = ""

    # 2. Raw task-bundle files
    (
        included_record_files,
        raw_sections,
        skipped_files,
    ) = _collect_raw_bundle_files(bundle_dir, options.max_record_file_bytes)

    # 3. Source-file snapshots
    included_source_files: list[str] = []
    source_sections: list[str] = []
    if options.include_source_files:
        (included_source_files, source_sections) = _collect_source_snapshots(
            workspace_root, task.id, options, skipped_files
        )

    return {
        "task": task,
        "report_content": report_content,
        "raw_sections": raw_sections,
        "source_sections": source_sections,
        "included_record_files": included_record_files,
        "included_source_files": included_source_files,
        "skipped_files": skipped_files,
        "options": options,
        "task_ref": task_ref,
        "ledger_ref": paths.ledger_ref,
    }


def render_task_markdown_export(payload: dict[str, object]) -> str:
    """Render the compiled export Markdown from a payload."""
    from taskledger._version import __version__
    from taskledger.domain.models import TaskRecord
    from taskledger.timeutils import utc_now_iso

    task = payload["task"]
    assert isinstance(task, TaskRecord)
    report_content = payload["report_content"]
    assert isinstance(report_content, str)
    raw_sections = payload["raw_sections"]
    assert isinstance(raw_sections, list)
    source_sections = payload["source_sections"]
    assert isinstance(source_sections, list)
    included_record_files = payload["included_record_files"]
    assert isinstance(included_record_files, list)
    included_source_files = payload["included_source_files"]
    assert isinstance(included_source_files, list)
    skipped_files = payload["skipped_files"]
    assert isinstance(skipped_files, list)
    options = payload["options"]
    assert isinstance(options, TaskMarkdownExportOptions)
    ledger_ref = payload["ledger_ref"]
    assert isinstance(ledger_ref, str)

    lines: list[str] = []

    # YAML front matter
    lines.append("---")
    lines.append("object_type: task_markdown_export")
    lines.append("export_version: 1")
    lines.append(f'generated_at: "{utc_now_iso()}"')
    lines.append(f"task_id: {task.id}")
    lines.append(f"ledger_ref: {ledger_ref}")
    lines.append(f"taskledger_version: {__version__}")
    lines.append(f"include_source_files: {options.include_source_files}")
    lines.append(f"include_command_output: {options.include_command_output}")
    lines.append("---")
    lines.append("")

    # Title
    lines.append(f"# Compiled Task Export: {task.id} — {task.title}")
    lines.append("")

    # How to use
    lines.append("## How to use this file")
    lines.append("")
    lines.append(
        "This is a compiled export of a Taskledger task bundle. It contains a "
        "curated task report, the raw taskledger record files, and optional "
        "source-file snapshots. Use it to understand what happened in this "
        "task without opening individual record files."
    )
    lines.append("")

    # Export summary
    lines.append("## Export Summary")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Task ID | {task.id} |")
    lines.append(f"| Title | {task.title} |")
    lines.append(f"| Status | {task.status_stage} |")
    lines.append(f"| Created | {task.created_at} |")
    lines.append(f"| Updated | {task.updated_at} |")
    if task.accepted_plan_version is not None:
        lines.append(f"| Accepted plan | plan-v{task.accepted_plan_version} |")
    lines.append(f"| Record files included | {len(included_record_files)} |")
    lines.append(f"| Source files included | {len(included_source_files)} |")
    lines.append(f"| Files skipped | {len(skipped_files)} |")
    lines.append("")

    # Curated report
    lines.append("## Curated Task Report")
    lines.append("")
    lines.append(report_content.rstrip("\n"))
    lines.append("")

    # Raw record files
    lines.append("## Raw Taskledger Record Files")
    lines.append("")
    if raw_sections:
        lines.extend(raw_sections)
    else:
        lines.append("(no record files found)")
        lines.append("")

    # Source file snapshots
    if source_sections:
        lines.append("## Source File Snapshots")
        lines.append("")
        lines.extend(source_sections)

    # Skipped files
    if skipped_files:
        lines.append("## Skipped Files")
        lines.append("")
        for entry in skipped_files:
            p = entry.get("path", "?")
            reason = entry.get("reason", "unknown")
            lines.append(f"- `{p}`: {reason}")
        lines.append("")

    result = "\n".join(lines)
    if result and not result.endswith("\n"):
        result += "\n"
    return result


def export_task_markdown(
    workspace_root: Path,
    task_ref: str,
    *,
    options: TaskMarkdownExportOptions | None = None,
) -> dict[str, object]:
    """Build and render a compiled task Markdown export."""
    payload = build_task_markdown_export_payload(
        workspace_root, task_ref, options=options
    )
    markdown = render_task_markdown_export(payload)
    from taskledger.domain.models import TaskRecord

    task = payload["task"]
    assert isinstance(task, TaskRecord)
    included_record_files = payload["included_record_files"]
    assert isinstance(included_record_files, list)
    included_source_files = payload["included_source_files"]
    assert isinstance(included_source_files, list)
    skipped_files = payload["skipped_files"]
    assert isinstance(skipped_files, list)

    return {
        "kind": "task_markdown_export",
        "task_id": task.id,
        "title": task.title,
        "content": markdown,
        "included_record_files": included_record_files,
        "included_source_files": included_source_files,
        "skipped_files": skipped_files,
        "bytes": len(markdown.encode("utf-8")),
    }
