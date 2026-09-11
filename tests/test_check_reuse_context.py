from __future__ import annotations

from pathlib import Path

from taskledger.services.handoff import (
    _append_checks_log,
    _append_required_commands,
)


def test_context_labels_reusable_and_unknown_checks() -> None:
    lines: list[str] = []
    _append_checks_log(
        lines,
        [
            {
                "check_id": "check-0001",
                "command": "python -m pytest",
                "exit_code": 0,
                "reuse": {
                    "eligible": True,
                    "reason_code": "eligible",
                    "message": "Exact snapshot match.",
                },
            },
            {
                "check_id": "check-0002",
                "command": "ruff check .",
                "exit_code": 0,
                "reuse": {
                    "eligible": False,
                    "reason_code": "missing_check_snapshot",
                    "message": "No tested-state provenance.",
                },
            },
        ],
        [],
    )

    rendered = "\n".join(lines)
    assert "## Implementation Checks" in rendered
    assert "check-0001 [reusable]" in rendered
    assert "check-0002 [unknown provenance]" in rendered


def test_required_commands_annotate_exact_reusable_evidence(tmp_path: Path) -> None:
    check = {
        "schema_version": 1,
        "object_type": "implementation_check",
        "file_version": "v2",
        "check_id": "check-0001",
        "task_id": "task-0001",
        "implementation_run": "run-0001",
        "timestamp": "2025-01-01T00:00:00Z",
        "command": "python -m pytest",
        "argv": ["python", "-m", "pytest"],
        "exit_code": 0,
        "status": "passed",
        "cwd": str(tmp_path.resolve()),
        "workspace_git_commit": "commit-1",
        "workspace_content_hash": "sha256:content",
        "workspace_paths_hash": "sha256:paths",
        "workspace_entry_count": 1,
        "workspace_snapshot_format": "worktree-content:v1",
        "reuse": {"eligible": True},
    }
    lines: list[str] = []
    _append_required_commands(
        lines,
        {"test_commands": ["python -m pytest"]},
        [check],
        workspace_root=tmp_path,
    )

    rendered = "\n".join(lines)
    assert "reusable implementation evidence: check-0001" in rendered
    assert "rerun only if fresh execution is required" in rendered
