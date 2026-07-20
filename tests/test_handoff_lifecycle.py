"""Tests for handoff lifecycle operations."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from taskledger.api.handoff import create_handoff, list_all_handoffs
from taskledger.api.project import init_project
from taskledger.api.tasks import create_task
from taskledger.domain.models import ActorRef
from taskledger.errors import LaunchError
from taskledger.services.handoff_lifecycle import (
    cancel_handoff,
    claim_handoff,
    close_handoff,
)
from taskledger.services.tasks import add_todo
from taskledger.storage.project_context import load_project_context
from taskledger.storage.task_store import resolve_handoff


# specmason: req=REQ-0023 ac=AC-0298
def test_handoff_creation():
    """Test creating a handoff."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")

        result = create_handoff(
            workspace,
            "task-0001",
            mode="implementation",
            intended_actor_name="alice",
            summary="Implement feature X",
        )

        assert result["handoff_id"].startswith("handoff-")
        assert result["status"] == "open"
        assert result["mode"] == "implementation"
        assert result["intended_actor_name"] == "alice"


# specmason: req=REQ-0023 ac=AC-0298
def test_handoff_claim():
    """Test claiming a handoff."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")

        handoff = create_handoff(workspace, "task-0001", mode="implementation")

        claimed = claim_handoff(workspace, "task-0001", handoff["handoff_id"])

        assert claimed.status == "claimed"
        assert claimed.claimed_by is not None
        assert claimed.claimed_at is not None


# specmason: req=REQ-0023 ac=AC-0299
def test_handoff_close():
    """Test closing a handoff."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")

        handoff = create_handoff(workspace, "task-0001", mode="implementation")

        claim_handoff(workspace, "task-0001", handoff["handoff_id"])
        closed = close_handoff(
            workspace, "task-0001", handoff["handoff_id"], reason="Complete"
        )

        assert closed.status == "closed"


# specmason: req=REQ-0023 ac=AC-0297
def test_handoff_cancel():
    """Test cancelling a handoff."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")

        handoff = create_handoff(workspace, "task-0001", mode="implementation")

        cancelled = cancel_handoff(
            workspace, "task-0001", handoff["handoff_id"], reason="No longer needed"
        )

        assert cancelled.status == "cancelled"


def test_cannot_claim_already_claimed():
    """Test that claiming twice fails."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")

        handoff = create_handoff(workspace, "task-0001", mode="implementation")

        claim_handoff(workspace, "task-0001", handoff["handoff_id"])

        with pytest.raises(LaunchError, match="Cannot claim"):
            claim_handoff(workspace, "task-0001", handoff["handoff_id"])


# specmason: req=REQ-0023 ac=AC-0295
# specmason: req=REQ-0023 ac=AC-0296
# specmason: req=REQ-0023 ac=AC-0303
# specmason: req=REQ-0023 ac=AC-0305
# specmason: req=REQ-0023 ac=AC-0306
def test_actor_intent_validation():
    """Test that actor intent is validated on claim."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")

        handoff = create_handoff(
            workspace,
            "task-0001",
            mode="implementation",
            intended_actor_name="alice",
        )

        wrong_actor = ActorRef(actor_type="user", actor_name="bob")

        with pytest.raises(LaunchError, match="mismatch"):
            claim_handoff(
                workspace,
                "task-0001",
                handoff["handoff_id"],
                actor=wrong_actor,
            )


# specmason: req=REQ-0023 ac=AC-0298
def test_handoff_list():
    """Test listing handoffs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")

        create_handoff(workspace, "task-0001", mode="implementation")
        create_handoff(workspace, "task-0001", mode="validation")
        create_handoff(workspace, "task-0001", mode="review")

        handoffs = list_all_handoffs(workspace, "task-0001")

        assert len(handoffs) == 3


# specmason: req=REQ-0023 ac=AC-0300
def test_handoff_list_raises_for_malformed_record() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")
        handoff_dir = (
            load_project_context(workspace).paths.data_root
            / "ledgers"
            / "main"
            / "tasks"
            / "task-0001"
            / "handoffs"
        )
        handoff_dir.mkdir(parents=True, exist_ok=True)
        (handoff_dir / "handoff-0001.md").write_text(
            "---\nobject_type: handoff\ncontext_hash: [\n---\n",
            encoding="utf-8",
        )

        with pytest.raises(LaunchError, match="Malformed handoff record"):
            list_all_handoffs(workspace, "task-0001")


# specmason: req=REQ-0023 ac=AC-0299
def test_handoff_modes():
    """Test different handoff modes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")

        modes = ["planning", "implementation", "validation", "review", "full"]
        for mode in modes:
            result = create_handoff(workspace, "task-0001", mode=mode)
            assert result["mode"] == mode

        with pytest.raises(LaunchError, match="Unsupported handoff mode"):
            create_handoff(workspace, "task-0001", mode="delivery")


# specmason: req=REQ-0023 ac=AC-0298
def test_handoff_with_summary():
    """Test creating handoff with summary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")

        summary = "Implement login feature with OAuth support"
        result = create_handoff(
            workspace,
            "task-0001",
            mode="implementation",
            summary=summary,
        )

        assert result["summary"] == summary


# specmason: req=REQ-0023 ac=AC-0304
def test_handoff_list_empty_task():
    """Test listing handoffs for task with no handoffs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")

        handoffs = list_all_handoffs(workspace, "task-0001")

        assert len(handoffs) == 0


# specmason: req=REQ-0023 ac=AC-0302
def test_handoff_lifecycle_sequence():
    """Test full handoff lifecycle: create -> claim -> close."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")

        # Create
        h = create_handoff(
            workspace, "task-0001", mode="implementation", summary="Work item"
        )
        assert h["status"] == "open"
        handoff_id = h["handoff_id"]

        # Claim
        claimed = claim_handoff(workspace, "task-0001", handoff_id)
        assert claimed.status == "claimed"

        # Close
        closed = close_handoff(
            workspace, "task-0001", handoff_id, reason="Work completed"
        )
        assert closed.status == "closed"


# specmason: req=REQ-0023 ac=AC-0300
def test_handoff_create_stores_generated_context_for_todo() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")
        add_todo(
            workspace,
            "task-0001",
            text="Implement the focused todo",
            mandatory=True,
        )

        result = create_handoff(
            workspace,
            "task-0001",
            mode="implementation",
            todo_id="todo-0001",
        )

        assert result["context_for"] == "implementer"
        assert result["scope"] == "todo"
        assert result["todo_id"] == "todo-0001"
        assert str(result["context_hash"]).startswith("sha256:")

        handoff = resolve_handoff(workspace, "task-0001", result["handoff_id"])
        assert handoff.context_body
        assert "## Focused Todo" in handoff.context_body
        assert "todo-0001" in handoff.context_body


# specmason: req=REQ-0023 ac=AC-0301
def test_handoff_lifecycle_preserves_context_metadata_on_claim_close_cancel() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        init_project(workspace)
        create_task(workspace, title="Test Task", description="Test", slug="task-0001")
        add_todo(
            workspace,
            "task-0001",
            text="Implement the focused todo",
            mandatory=True,
        )

        created = create_handoff(
            workspace,
            "task-0001",
            mode="implementation",
            todo_id="todo-0001",
        )
        handoff_id = str(created["handoff_id"])

        claim_handoff(workspace, "task-0001", handoff_id)
        claimed = resolve_handoff(workspace, "task-0001", handoff_id)
        assert claimed.context_for == "implementer"
        assert claimed.scope == "todo"
        assert claimed.todo_id == "todo-0001"
        assert claimed.focus_run_id is None
        assert claimed.context_hash == created["context_hash"]
        assert claimed.context_body

        close_handoff(workspace, "task-0001", handoff_id, reason="done")
        closed = resolve_handoff(workspace, "task-0001", handoff_id)
        assert closed.context_for == "implementer"
        assert closed.scope == "todo"
        assert closed.todo_id == "todo-0001"
        assert closed.context_hash == created["context_hash"]
        assert closed.context_body == claimed.context_body

        second = create_handoff(
            workspace,
            "task-0001",
            mode="implementation",
            todo_id="todo-0001",
        )
        cancel_handoff(workspace, "task-0001", str(second["handoff_id"]), reason="skip")
        cancelled = resolve_handoff(workspace, "task-0001", str(second["handoff_id"]))
        assert cancelled.context_for == "implementer"
        assert cancelled.scope == "todo"
        assert cancelled.todo_id == "todo-0001"
        assert cancelled.context_hash == second["context_hash"]
        assert cancelled.context_body
