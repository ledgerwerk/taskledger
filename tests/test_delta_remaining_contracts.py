from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.services.tasks import (
    add_todo,
    finish_implementation,
    start_implementation,
    start_validation,
)
from tests.support.builders import create_approved_task, init_workspace

pytestmark = [pytest.mark.cli, pytest.mark.integration, pytest.mark.slow]


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


def _init(tmp_path: Path) -> None:
    init_workspace(tmp_path)


def _prepare_validating_task(tmp_path: Path) -> None:
    _init(tmp_path)
    task_id = create_approved_task(
        tmp_path,
        title="validation-gate",
        slug="validation-gate",
        description="Exercise validation gates.",
        plan_text="## Goal\n\nValidate objectively.",
        criteria=("Mandatory behavior is checked.",),
        allow_empty_todos=True,
        allow_lint_errors=True,
        approve_note="Approved.",
        approve_reason="test",
    )
    start_implementation(tmp_path, task_id)
    finish_implementation(tmp_path, task_id, summary="Implemented.")
    start_validation(tmp_path, task_id)


def _prepare_validating_task_with_mandatory_todo(tmp_path: Path) -> None:
    _init(tmp_path)
    task_id = create_approved_task(
        tmp_path,
        title="validation-gate",
        slug="validation-gate",
        description="Exercise validation gates.",
        plan_text="## Goal\n\nValidate objectively.",
        criteria=("Mandatory behavior is checked.",),
        allow_empty_todos=True,
        allow_lint_errors=True,
        approve_note="Approved.",
        approve_reason="test",
    )
    add_todo(
        tmp_path,
        task_id,
        text="Final sign-off",
        mandatory=True,
    )
    start_implementation(tmp_path, task_id)
    finish_implementation(tmp_path, task_id, summary="Implemented.")
    start_validation(tmp_path, task_id)


def test_validation_pass_requires_mandatory_criteria_checks(tmp_path: Path) -> None:
    _prepare_validating_task(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "validate",
            "finish",
            "--task",
            "validation-gate",
            "--result",
            "passed",
            "--summary",
            "No checks recorded.",
        ],
    )

    payload = _json(result)
    assert result.exit_code == 7
    assert payload["error"]["code"] == "VALIDATION_INCOMPLETE"
    assert payload["error"]["details"]["missing_criteria"] == ["ac-0001"]


def test_validation_pass_accepts_canonical_criterion_check(tmp_path: Path) -> None:
    _prepare_validating_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "validate",
                "check",
                "--task",
                "validation-gate",
                "--criterion",
                "ac-0001",
                "--status",
                "pass",
                "--evidence",
                "pytest -q",
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "validate",
            "finish",
            "--task",
            "validation-gate",
            "--result",
            "passed",
            "--summary",
            "All gates passed.",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert _json(result)["result"]["status"] == "done"


def test_context_dossier_and_link_alias_are_canonical(tmp_path: Path) -> None:
    _init(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "context-task",
                "--description",
                "Render context.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "file",
                "add",
                "--task",
                "context-task",
                "--path",
                "README.md",
                "--kind",
                "doc",
            ],
        ).exit_code
        == 0
    )

    context = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "context",
            "--task",
            "context-task",
            "--for",
            "planning",
            "--format",
            "markdown",
        ],
    )
    assert context.exit_code == 0
    assert "Planning Context" in context.stdout
    assert "@README.md" in context.stdout

    dossier = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "dossier",
            "--task",
            "context-task",
            "--format",
            "markdown",
        ],
    )
    assert dossier.exit_code == 0
    assert "Task Dossier" in dossier.stdout


def test_user_dependency_waiver_unblocks_implementation(tmp_path: Path) -> None:
    _init(tmp_path)
    for slug in ("dependency", "main-task"):
        assert (
            runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "task",
                    "create",
                    slug,
                    "--description",
                    slug,
                ],
            ).exit_code
            == 0
        )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "require",
                "add",
                "dependency",
                "--task",
                "main-task",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(tmp_path), "plan", "start", "--task", "main-task"]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "propose",
                "--task",
                "main-task",
                "--criterion",
                "Implementation starts.",
                "--text",
                "## Goal\n\nStart implementation.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "approve",
                "--task",
                "main-task",
                "--version",
                "1",
                "--actor",
                "user",
                "--note",
                "Approved.",
                "--allow-empty-todos",
                "--allow-lint-errors",
                "--reason",
                "test",
            ],
        ).exit_code
        == 0
    )

    blocked = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "implement", "start", "--task", "main-task"],
    )
    assert blocked.exit_code == 3

    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "require",
                "waive",
                "dependency",
                "--task",
                "main-task",
                "--actor",
                "user",
                "--reason",
                "Safe to proceed.",
            ],
        ).exit_code
        == 0
    )
    allowed = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "implement", "start", "--task", "main-task"],
    )
    assert allowed.exit_code == 0, allowed.stdout


def test_services_tasks_has_no_duplicate_top_level_function_names() -> None:
    """Static AST check: no duplicate top-level function definitions."""
    import ast

    path = Path(__file__).resolve().parents[1] / "taskledger" / "services" / "tasks.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    seen: set[str] = set()
    duplicates: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            if node.name in seen:
                duplicates.add(node.name)
            seen.add(node.name)

    assert duplicates == set(), f"Duplicate top-level functions: {duplicates}"


def test_import_smoke_tests() -> None:
    """Smoke tests for module imports."""
    from taskledger.domain.policies import Decision, PolicyDecision

    assert Decision is not None
    assert PolicyDecision is not None
    assert PolicyDecision is Decision

    decision = Decision(allowed=True, code="OK", message="Test message")
    assert decision.ok is True
    assert decision.reason == "Test message"


def test_taskledger_main_import() -> None:
    """Verify taskledger can be imported as a package."""
    import taskledger

    assert taskledger is not None


def test_resolve_criterion_ref_canonicalization(tmp_path: Path) -> None:
    """Test criterion reference canonicalization."""
    from taskledger.domain.models import AcceptanceCriterion, PlanRecord
    from taskledger.services.tasks import _resolve_criterion_ref

    plan = PlanRecord(
        task_id="test-task",
        plan_version=1,
        body="Test plan",
        criteria=(
            AcceptanceCriterion(id="ac-0001", text="First criterion", mandatory=True),
            AcceptanceCriterion(id="ac-0002", text="Second criterion", mandatory=True),
        ),
    )

    assert _resolve_criterion_ref(plan, "ac-0001") == "ac-0001"
    assert _resolve_criterion_ref(plan, "AC-0001") == "ac-0001"
    assert _resolve_criterion_ref(plan, "ac-1") == "ac-0001"
    assert _resolve_criterion_ref(plan, "1") == "ac-0001"

    assert _resolve_criterion_ref(plan, "ac-0002") == "ac-0002"
    assert _resolve_criterion_ref(plan, "AC-0002") == "ac-0002"
    assert _resolve_criterion_ref(plan, "ac-2") == "ac-0002"
    assert _resolve_criterion_ref(plan, "2") == "ac-0002"


def test_resolve_criterion_ref_unknown(tmp_path: Path) -> None:
    """Test criterion resolver with unknown reference."""
    from taskledger.domain.models import AcceptanceCriterion, PlanRecord
    from taskledger.errors import LaunchError
    from taskledger.services.tasks import _resolve_criterion_ref

    plan = PlanRecord(
        task_id="test-task",
        plan_version=1,
        body="Test plan",
        criteria=(
            AcceptanceCriterion(id="ac-0001", text="First criterion", mandatory=True),
        ),
    )

    try:
        _resolve_criterion_ref(plan, "ac-9999")
        raise AssertionError("Should have raised LaunchError")
    except LaunchError as e:
        assert "Unknown acceptance criterion" in str(e)
        assert "ac-9999" in str(e)
        assert "ac-0001" in str(e)


def test_reject_unknown_criterion_at_check_time(tmp_path: Path) -> None:
    """Test that unknown criterion is rejected when recording a check."""
    _prepare_validating_task(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "validate",
            "check",
            "--task",
            "validation-gate",
            "--criterion",
            "ac-9999",
            "--status",
            "pass",
            "--evidence",
            "pytest",
        ],
    )
    assert result.exit_code != 0
    assert (
        "Unknown acceptance criterion" in result.stdout
        or "Unknown acceptance criterion" in result.stderr
    )


def test_latest_check_wins_semantics(tmp_path: Path) -> None:
    """Test that latest check per criterion determines
    pass eligibility (not history)."""
    _prepare_validating_task(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "validate",
            "check",
            "--task",
            "validation-gate",
            "--criterion",
            "ac-0001",
            "--status",
            "fail",
            "--evidence",
            "first run failed",
        ],
    )
    assert result.exit_code == 0

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "validate",
            "check",
            "--task",
            "validation-gate",
            "--criterion",
            "ac-0001",
            "--status",
            "pass",
            "--evidence",
            "fixed and reran",
        ],
    )
    assert result.exit_code == 0

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "validate",
            "finish",
            "--task",
            "validation-gate",
            "--result",
            "passed",
            "--summary",
            "Ready to pass.",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["result"]["status"] == "done"


def test_waiver_satisfies_criterion(tmp_path: Path) -> None:
    """Test that user can waive a criterion to satisfy mandatory gate."""
    _prepare_validating_task(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "validate",
            "waive",
            "--task",
            "validation-gate",
            "--criterion",
            "ac-0001",
            "--reason",
            "Safe to proceed with waiver.",
        ],
    )
    assert result.exit_code == 0

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "validate",
            "finish",
            "--task",
            "validation-gate",
            "--result",
            "passed",
            "--summary",
            "Criterion waived.",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["result"]["status"] == "done"


def test_validation_status_command_shows_blockers(tmp_path: Path) -> None:
    """Test validate status command renders blockers."""
    _prepare_validating_task(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "validate",
            "status",
            "--task",
            "validation-gate",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    status_result = data["result"].get("result", {})
    assert not status_result.get("can_finish_passed", False)
    blockers = status_result.get("blockers", [])
    assert len(blockers) > 0
    assert any(b.get("kind") == "criterion_missing" for b in blockers)


def test_mandatory_todo_blocks_validation_completion(tmp_path: Path) -> None:
    """Test that open mandatory todos block validation completion."""
    _init(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "validation-gate",
                "--description",
                "Exercise validation gates.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(tmp_path), "plan", "start", "--task", "validation-gate"]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "propose",
                "--task",
                "validation-gate",
                "--criterion",
                "Mandatory behavior is checked.",
                "--text",
                "## Goal\n\nValidate objectively.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "approve",
                "--task",
                "validation-gate",
                "--version",
                "1",
                "--actor",
                "user",
                "--note",
                "Approved.",
                "--allow-empty-todos",
                "--allow-lint-errors",
                "--reason",
                "test",
            ],
        ).exit_code
        == 0
    )

    # Add mandatory todo during plan phase (before implement starts)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "todo",
                "add",
                "--task",
                "validation-gate",
                "--text",
                "Final sign-off",
                "--mandatory",
            ],
        ).exit_code
        == 0
    )

    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "implement", "start", "--task", "validation-gate"],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "implement",
                "finish",
                "--task",
                "validation-gate",
                "--summary",
                "Implemented.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "validate", "start", "--task", "validation-gate"],
        ).exit_code
        == 0
    )

    runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "validate",
            "check",
            "--task",
            "validation-gate",
            "--criterion",
            "ac-0001",
            "--status",
            "pass",
            "--evidence",
            "pytest -q",
        ],
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "validate",
            "finish",
            "--task",
            "validation-gate",
            "--result",
            "passed",
            "--summary",
            "Ready.",
        ],
    )
    assert result.exit_code == 7
    payload = _json(result)
    assert payload["error"]["code"] == "VALIDATION_INCOMPLETE"
    assert len(payload["error"]["details"].get("open_mandatory_todos", [])) > 0


def test_next_action_validation_includes_next_missing_criterion(tmp_path: Path) -> None:
    """Test that next-action reports the next concrete criterion during validation."""
    _prepare_validating_task(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "next-action",
            "--task",
            "validation-gate",
        ],
    )
    assert result.exit_code == 0
    data = _json(result)["result"]
    assert data["action"] == "validate-check"
    assert data["next_item"] == {
        "kind": "criterion",
        "id": "ac-0001",
        "text": "Mandatory behavior is checked.",
        "mandatory": True,
        "latest_status": "not_run",
        "satisfied": False,
    }
    assert data["next_command"] == (
        'taskledger validate check --criterion ac-0001 --status pass --evidence "..."'
    )
    assert data["commands"][0] == {
        "kind": "check",
        "label": "Record validation check",
        "command": (
            "taskledger validate check --criterion ac-0001 "
            '--status pass --evidence "..."'
        ),
        "primary": True,
    }
    assert data["progress"]["validation"] == {
        "total": 1,
        "satisfied": 0,
        "remaining": 1,
        "blocking_ids": ["ac-0001"],
    }
    assert len(data.get("blocking", [])) > 0
    assert any(b.get("kind") == "criterion_missing" for b in data.get("blocking", []))


def test_next_action_validation_with_no_blockers_returns_finish(tmp_path: Path) -> None:
    _prepare_validating_task(tmp_path)
    checked = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "validate",
            "check",
            "--task",
            "validation-gate",
            "--criterion",
            "ac-0001",
            "--status",
            "pass",
            "--evidence",
            "python -m pytest -q",
        ],
    )
    assert checked.exit_code == 0, checked.stdout

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "next-action",
            "--task",
            "validation-gate",
        ],
    )
    assert result.exit_code == 0, result.stdout
    data = _json(result)["result"]
    assert data["action"] == "validate-finish"
    assert data["next_command"] == (
        "taskledger validate finish --result passed --summary SUMMARY"
    )
    assert data["next_item"] == {
        "kind": "task",
        "id": "task-0001",
        "status_stage": "implemented",
    }
    assert data["progress"]["validation"] == {
        "total": 1,
        "satisfied": 1,
        "remaining": 0,
        "blocking_ids": [],
    }


def test_next_action_with_expired_lock_returns_repair_hint(tmp_path: Path) -> None:
    _init(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "stale-lock",
                "--description",
                "Exercise stale lock handling.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["--cwd", str(tmp_path), "plan", "start", "--task", "stale-lock"]
        ).exit_code
        == 0
    )

    lock_path = (
        tmp_path
        / ".taskledger"
        / "ledgers"
        / "main"
        / "tasks"
        / "task-0001"
        / "lock.yaml"
    )
    lock_payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    lock_payload["expires_at"] = "2000-01-01T00:00:00+00:00"
    lock_path.write_text(
        yaml.safe_dump(lock_payload, sort_keys=False), encoding="utf-8"
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "next-action",
            "--task",
            "stale-lock",
        ],
    )
    assert result.exit_code == 0, result.stdout
    data = _json(result)["result"]
    assert data["next_item"] == {
        "kind": "lock",
        "id": lock_payload["lock_id"],
        "task_id": "task-0001",
        "stage": "planning",
        "run_id": lock_payload["run_id"],
        "expired": True,
    }
    assert data["next_command"] == (
        'taskledger repair lock --task task-0001 --reason "..."'
    )
    assert any(b.get("kind") == "lock" for b in data["blocking"])


def _prepare_done_task(
    tmp_path: Path,
    *,
    slug: str = "parent-task",
    title: str = "Parent task",
    include_links: bool = False,
) -> None:
    _init(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                title,
                "--slug",
                slug,
                "--description",
                f"{title} description.",
            ],
        ).exit_code
        == 0
    )
    if include_links:
        assert (
            runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "file",
                    "add",
                    "--task",
                    slug,
                    "--path",
                    "README.md",
                    "--kind",
                    "doc",
                ],
            ).exit_code
            == 0
        )
        assert (
            runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "link",
                    "add",
                    "--task",
                    slug,
                    "--url",
                    "https://example.com/spec",
                    "--label",
                    "spec",
                ],
            ).exit_code
            == 0
        )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "plan", "start", "--task", slug],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "propose",
                "--task",
                slug,
                "--criterion",
                "The task completes successfully.",
                "--text",
                "## Goal\n\nComplete the task.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "approve",
                "--task",
                slug,
                "--version",
                "1",
                "--actor",
                "user",
                "--note",
                "Approved.",
                "--allow-empty-todos",
                "--allow-lint-errors",
                "--reason",
                "test",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "implement", "start", "--task", slug],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "implement",
                "finish",
                "--task",
                slug,
                "--summary",
                "Implemented.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "validate", "start", "--task", slug],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "validate",
                "check",
                "--task",
                slug,
                "--criterion",
                "ac-0001",
                "--status",
                "pass",
                "--evidence",
                "pytest -q",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "validate",
                "finish",
                "--task",
                slug,
                "--result",
                "passed",
                "--summary",
                "Validated.",
            ],
        ).exit_code
        == 0
    )


def test_task_follow_up_creates_linked_child_and_copies_lightweight_links(
    tmp_path: Path,
) -> None:
    _prepare_done_task(tmp_path, include_links=True)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "task",
            "follow-up",
            "parent-task",
            "Rename label",
            "--description",
            "Change button copy.",
            "--copy-files",
            "--copy-links",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = _json(result)["result"]
    assert set(payload) == {
        "kind",
        "task_id",
        "slug",
        "parent_task_id",
        "parent_relation",
        "activated",
        "next_command",
    }
    assert payload["kind"] == "task_follow_up_created"
    assert payload["task_id"] == "task-0002"
    assert payload["parent_task_id"] == "task-0001"
    assert payload["parent_relation"] == "follow_up"
    assert payload["activated"] is False

    child_show = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "task",
                "show",
                "--task",
                "task-0002",
            ],
        )
    )["result"]
    child = child_show["task"]
    assert child["status_stage"] == "draft"
    assert child["parent_task_id"] == "task-0001"
    assert child["parent_relation"] == "follow_up"
    assert child["todos"] == []
    assert child_show["plans"] == []
    assert child_show["runs"] == []
    assert child_show["changes"] == []
    assert {item["path"] for item in child["file_links"]} == {
        "README.md",
        "https://example.com/spec",
    }

    parent_show = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "task",
                "show",
                "--task",
                "parent-task",
            ],
        )
    )["result"]
    assert parent_show["follow_up_tasks"][0]["task_id"] == "task-0002"


def test_task_follow_up_activate_sets_child_active_and_next_command(
    tmp_path: Path,
) -> None:
    _prepare_done_task(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "task",
            "follow-up",
            "parent-task",
            "Rename label",
            "--activate",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = _json(result)["result"]
    assert payload["activated"] is True
    assert payload["next_command"] == "taskledger plan start"

    active = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "task", "active"])
    )["result"]
    assert active["task_id"] == "task-0002"


def test_task_follow_up_rejects_non_done_parent_without_mutating_state(
    tmp_path: Path,
) -> None:
    _init(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "Parent task",
                "--slug",
                "parent-task",
                "--description",
                "Still draft.",
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "task",
            "follow-up",
            "parent-task",
            "Rename label",
        ],
    )
    assert result.exit_code != 0
    payload = _json(result)
    assert "done parent task" in payload["error"]["message"]

    tasks = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "task", "list"])
    )["result"]["tasks"]
    assert len(tasks) == 1


def test_task_close_persists_closure_metadata_and_is_idempotent(tmp_path: Path) -> None:
    _prepare_done_task(tmp_path, slug="closable", title="Closable task")

    first = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "task",
            "close",
            "--task",
            "closable",
            "--note",
            "Archived after validation.",
        ],
    )
    assert first.exit_code == 0, first.stdout
    first_payload = _json(first)["result"]
    assert first_payload["changed"] is True

    show = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "task",
                "show",
                "--task",
                "closable",
            ],
        )
    )["result"]["task"]
    assert show["closed_at"]
    assert show["closed_by"]["actor_type"] == "agent"
    assert show["closure_note"] == "Archived after validation."

    second = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "task",
            "close",
            "--task",
            "closable",
        ],
    )
    assert second.exit_code == 0, second.stdout
    assert _json(second)["result"]["changed"] is False


def test_follow_up_relationships_render_in_show_dossier_and_context(
    tmp_path: Path,
) -> None:
    _prepare_done_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "follow-up",
                "parent-task",
                "Rename label",
            ],
        ).exit_code
        == 0
    )

    child_show = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "show", "--task", "task-0002"],
    )
    assert child_show.exit_code == 0
    assert "follow-up of: task-0001 Parent task" in child_show.stdout

    parent_show = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "task", "show", "--task", "parent-task"],
    )
    assert parent_show.exit_code == 0
    assert "follow-ups: task-0002 Rename label" in parent_show.stdout

    dossier = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "task",
            "dossier",
            "--task",
            "parent-task",
            "--format",
            "markdown",
        ],
    )
    assert dossier.exit_code == 0
    assert "## Follow-up Tasks" in dossier.stdout
    assert "task-0002 Rename label — draft" in dossier.stdout

    context = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "context",
            "--task",
            "task-0002",
            "--for",
            "planning",
            "--format",
            "markdown",
        ],
    )
    assert context.exit_code == 0
    assert "## Parent Task" in context.stdout
    assert "- ID: task-0001" in context.stdout
    assert "- Accepted plan: plan-v1" in context.stdout
    assert "- Latest validation: run-0003 passed" in context.stdout


def test_done_parent_next_action_stays_none_after_follow_up_creation(
    tmp_path: Path,
) -> None:
    _prepare_done_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "follow-up",
                "parent-task",
                "Rename label",
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "next-action",
            "--task",
            "parent-task",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = _json(result)["result"]
    assert payload["action"] == "none"
    assert payload["reason"] == "The task is complete."
