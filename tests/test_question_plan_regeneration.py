from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.services.tasks import activate_task, create_task, start_planning
from taskledger.storage.task_store import resolve_run, resolve_task
from tests.support.builders import init_workspace

pytestmark = [pytest.mark.cli, pytest.mark.integration, pytest.mark.slow]


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _runner()


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


def _init_task(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    task = create_task(
        tmp_path,
        title="Regeneration task",
        slug="regen-task",
        description="",
    )
    activate_task(tmp_path, task.id, reason="test setup")
    start_planning(tmp_path, task.id)


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/question-plan-"
        "regeneration.feature"
    ),
    scenario=(
        "@bdd-question-plan-regeneration-required-question-blocks-approval-"
        "until-answered-and-regenerated"
    ),
)
def test_required_question_blocks_approval_until_answered_and_regenerated(
    tmp_path: Path,
) -> None:
    _init_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "add",
                "--text",
                "Which database?",
                "--required-for-plan",
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
                "propose",
                "--criterion",
                "Database choice is honored.",
                "--text",
                "Initial plan.",
            ],
        ).exit_code
        == 0
    )
    blocked = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--version",
            "1",
            "--actor",
            "user",
        ],
    )
    assert blocked.exit_code != 0
    assert "open planning questions" in _json(blocked)["error"]["message"]

    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "answer",
                "q-0001",
                "--text",
                "PostgreSQL.",
                "--from-user-chat",
            ],
        ).exit_code
        == 0
    )
    status = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "question", "status"])
    )
    assert status["result"]["plan_regeneration_needed"] is True

    plan_text = """---
acceptance_criteria:
  - text: Database choice is honored.
todos:
  - text: Implement PostgreSQL-only behavior.
---

# Plan

Use PostgreSQL only.
"""
    regenerated = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "regenerate",
                "--from-answers",
                "--text",
                plan_text,
            ],
        )
    )
    assert regenerated["result"]["plan_version"] == 2

    show = _json(
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "plan", "show", "--version", "2"],
        )
    )
    plan = show["result"]["plan"]
    assert plan["generation_reason"] == "after_questions"
    assert plan["based_on_question_ids"] == ["q-0001"]

    status = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "question", "status"])
    )
    assert status["result"]["plan_regeneration_needed"] is False


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/question-plan-"
        "regeneration.feature"
    ),
    scenario=(
        "@bdd-question-plan-regeneration-plan-regeneration-finishes-orphaned-"
        "latest-planning-run"
    ),
)
def test_plan_regeneration_finishes_orphaned_latest_planning_run(
    tmp_path: Path,
) -> None:
    _init_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "add",
                "--text",
                "Which lifecycle state?",
                "--required-for-plan",
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
                "question",
                "answer",
                "q-0001",
                "--text",
                "Approved with no active lock.",
                "--from-user-chat",
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
                "lock",
                "break",
                "--reason",
                "Simulate missing planning lock.",
            ],
        ).exit_code
        == 0
    )
    task = resolve_task(tmp_path, "regen-task")
    assert task.latest_planning_run is not None
    assert resolve_run(tmp_path, task.id, task.latest_planning_run).status == "running"

    plan_text = """---
acceptance_criteria:
  - text: Orphaned planning run is recovered.
todos:
  - text: Start implementation after approval.
---

# Plan

Recover the orphaned planning run.
"""
    regenerated = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "regenerate",
            "--from-answers",
            "--text",
            plan_text,
        ],
    )

    assert regenerated.exit_code == 0, regenerated.stdout
    task = resolve_task(tmp_path, "regen-task")
    run = resolve_run(tmp_path, task.id, task.latest_planning_run)
    assert run.status == "finished"
    status = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "question", "status"])
    )
    assert status["result"]["plan_regeneration_needed"] is False


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/question-plan-"
        "regeneration.feature"
    ),
    scenario=(
        "@bdd-question-plan-regeneration-answered-question-blocks-approval-of-"
        "stale-plan"
    ),
)
def test_answered_question_blocks_approval_of_stale_plan(tmp_path: Path) -> None:
    _init_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "add",
                "--text",
                "Which database?",
                "--required-for-plan",
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
                "propose",
                "--criterion",
                "Database choice is honored.",
                "--text",
                "Initial plan.",
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
                "question",
                "answer",
                "q-0001",
                "--text",
                "SQLite.",
                "--from-user-chat",
            ],
        ).exit_code
        == 0
    )

    blocked = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "approve",
            "--version",
            "1",
            "--actor",
            "user",
        ],
    )

    assert blocked.exit_code == 3
    payload = json.loads(blocked.stdout)
    assert payload["error"]["code"] == "APPROVAL_REQUIRED"
    assert "Regenerate the plan from answers" in payload["error"]["message"]


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/"
        "question-plan-regeneration.feature"
    ),
    scenario="@bdd-question-plan-regeneration-changed-answer-restales-plan",
)
def test_changed_answer_requires_regeneration_again(tmp_path: Path) -> None:
    _init_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "add",
                "--text",
                "Which database?",
                "--required-for-plan",
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
                "question",
                "answer",
                "q-0001",
                "--text",
                "SQLite.",
                "--from-user-chat",
            ],
        ).exit_code
        == 0
    )
    plan_text = """---
acceptance_criteria:
  - text: Database choice is honored.
---

# Plan

Use SQLite.
"""
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "regenerate",
                "--from-answers",
                "--text",
                plan_text,
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
                "question",
                "answer",
                "q-0001",
                "--text",
                "PostgreSQL.",
                "--from-user-chat",
            ],
        ).exit_code
        == 0
    )

    status = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "question", "status"])
    )

    assert status["result"]["answered_since_latest_plan"] == ["q-0001"]
    assert status["result"]["plan_regeneration_needed"] is True


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/"
        "question-plan-regeneration.feature"
    ),
    scenario="@bdd-question-plan-regeneration-answer-many-records-user-answers",
)
def test_answer_many_records_user_chat_answers_and_requires_regeneration(
    tmp_path: Path,
) -> None:
    _init_task(tmp_path)
    for text in ("Which database?", "Which cache?"):
        assert (
            runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "question",
                    "add",
                    "--text",
                    text,
                    "--required-for-plan",
                ],
            ).exit_code
            == 0
        )

    result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "question",
                "answer-many",
                "--text",
                "answers:\n  q-0001: PostgreSQL.\n  q-0002: Redis.\n",
                "--from-user-chat",
            ],
        )
    )

    assert result["result"]["answered_question_ids"] == ["q-0001", "q-0002"]
    assert result["result"]["required_open"] == 0
    assert result["result"]["plan_regeneration_needed"] is True
    assert result["result"]["next_action"] == (
        "taskledger plan upsert --from-answers --file plan.md"
    )
    assert result["result"]["template_command"] == (
        "taskledger plan template --from-answers --file plan.md"
    )
    assert result["result"]["required_plan_fields"] == [
        "goal",
        "acceptance_criteria",
        "todos",
    ]
    assert result["result"]["recommended_plan_fields"] == [
        "files",
        "test_commands",
        "expected_outputs",
    ]


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/question-plan-"
        "regeneration.feature"
    ),
    scenario=(
        "@bdd-question-plan-regeneration-answer-many-rejects-duplicate-plain-text-ids"
    ),
)
def test_answer_many_rejects_duplicate_plain_text_ids(tmp_path: Path) -> None:
    _init_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "add",
                "--text",
                "Which database?",
                "--required-for-plan",
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
            "question",
            "answer-many",
            "--text",
            "q-0001: PostgreSQL.\nq-0001: SQLite.\n",
            "--from-user-chat",
        ],
    )

    assert result.exit_code != 0
    assert "Duplicate key" in _json(result)["error"]["message"]


def test_answer_many_accepts_repeated_text_options(tmp_path: Path) -> None:
    _init_task(tmp_path)
    for text in ("Q1?", "Q2?", "Q3?", "Q4?"):
        assert (
            runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "question",
                    "add",
                    "--text",
                    text,
                    "--required-for-plan",
                ],
            ).exit_code
            == 0
        )

    result = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "question",
                "answer-many",
                "--text",
                "q-0001: A1",
                "--text",
                "q-0002: A2",
                "--text",
                "q-0003: A3",
                "--text",
                "q-0004: A4",
                "--from-user-chat",
            ],
        )
    )

    assert result["result"]["answered_question_ids"] == [
        "q-0001",
        "q-0002",
        "q-0003",
        "q-0004",
    ]
    assert result["result"]["required_open"] == 0
    assert result["result"]["plan_regeneration_needed"] is True


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/question-plan-"
        "regeneration.feature"
    ),
    scenario=(
        "@bdd-question-plan-regeneration-required-question-needs-explicit-"
        "user-source-for-agent"
    ),
)
def test_required_question_needs_explicit_user_source_for_agent(tmp_path: Path) -> None:
    _init_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "add",
                "--text",
                "Which database?",
                "--required-for-plan",
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
            "question",
            "answer",
            "q-0001",
            "--text",
            "Inferred answer.",
        ],
    )

    assert result.exit_code != 0
    assert (
        "Required planning question requires explicit user source"
        in _json(result)["error"]["message"]
    )


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/question-plan-"
        "regeneration.feature"
    ),
    scenario=(
        "@bdd-question-plan-regeneration-question-answer-accepts-question-option-alias"
    ),
)
def test_question_answer_accepts_question_option_alias(tmp_path: Path) -> None:
    _init_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "add",
                "--text",
                "Which database?",
                "--required-for-plan",
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "question",
            "answer",
            "--question",
            "q-0001",
            "--text",
            "PostgreSQL.",
            "--from-user-chat",
        ],
    )

    assert result.exit_code == 0, result.stdout


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/question-plan-"
        "regeneration.feature"
    ),
    scenario=(
        "@bdd-question-plan-regeneration-question-answer-rejects-both-"
        "positional-and-option-id"
    ),
)
def test_question_answer_rejects_both_positional_and_option_id(tmp_path: Path) -> None:
    _init_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "add",
                "--text",
                "Which database?",
            ],
        ).exit_code
        == 0
    )
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "question",
            "answer",
            "q-0001",
            "--question",
            "q-0001",
            "--text",
            "PostgreSQL.",
        ],
    )

    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "Provide exactly one question id" in combined


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/question-plan-"
        "regeneration.feature"
    ),
    scenario=(
        "@bdd-question-plan-regeneration-question-status-human-lists-required-open-ids"
    ),
)
def test_question_status_human_lists_required_open_ids(tmp_path: Path) -> None:
    _init_task(tmp_path)
    for text in ("Q1?", "Q2?"):
        assert (
            runner.invoke(
                app,
                [
                    "--cwd",
                    str(tmp_path),
                    "question",
                    "add",
                    "--text",
                    text,
                    "--required-for-plan",
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
                "question",
                "answer",
                "q-0001",
                "--text",
                "A1",
                "--from-user-chat",
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "question",
            "status",
        ],
    )

    assert result.exit_code == 0
    assert "Open required questions: q-0002" in result.stdout
    assert "Answered required questions: q-0001" in result.stdout
    assert "Do not infer answers." in result.stdout


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/question-plan-"
        "regeneration.feature"
    ),
    scenario=(
        "@bdd-question-plan-regeneration-plan-upsert-from-answers-releases-"
        "planning-lock-and-allows-accept"
    ),
)
def test_plan_upsert_from_answers_releases_planning_lock_and_allows_accept(
    tmp_path: Path,
) -> None:
    _init_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "add",
                "--text",
                "Which database?",
                "--required-for-plan",
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
                "question",
                "answer-many",
                "--text",
                "q-0001: PostgreSQL.",
                "--from-user-chat",
            ],
        ).exit_code
        == 0
    )
    plan_text = """---
acceptance_criteria:
  - text: Database choice is honored.
todos:
  - text: Implement PostgreSQL behavior.
---

# Plan

Use PostgreSQL.
"""

    upserted = _json(
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "--json",
                "plan",
                "upsert",
                "--from-answers",
                "--text",
                plan_text,
            ],
        )
    )

    assert upserted["result"]["operation"] == "regenerated"
    assert upserted["result"]["plan_version"] == 1
    next_action = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "next-action"])
    )
    assert next_action["result"]["action"] == "plan-approve"

    accepted = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "accept",
            "--version",
            "1",
            "--note",
            "Ready.",
            "--allow-lint-errors",
        ],
    )

    assert accepted.exit_code == 0
    assert _json(accepted)["result"]["status_stage"] == "approved"


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/"
        "question-plan-regeneration.feature"
    ),
    scenario="@bdd-question-plan-regeneration-next-action-prefers-open-question",
)
def test_next_action_prefers_question_answer_while_planning_questions_are_open(
    tmp_path: Path,
) -> None:
    _init_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "add",
                "--text",
                "Which database?",
                "--required-for-plan",
            ],
        ).exit_code
        == 0
    )

    payload = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "next-action"])
    )

    result = payload["result"]
    assert result["action"] == "question-answer"
    assert result["next_command"] == 'taskledger question answer q-0001 --text "..."'
    assert result["blocking"][0]["kind"] == "open_questions"
    assert result["next_item"] == {
        "kind": "question",
        "id": "q-0001",
        "text": "Which database?",
        "status": "open",
        "required_for_plan": True,
        "plan_version": None,
    }
    assert result["commands"][0] == {
        "kind": "answer",
        "label": "Answer required question",
        "command": 'taskledger question answer q-0001 --text "..."',
        "primary": True,
    }
    assert result["progress"]["questions"] == {
        "required_open": 1,
        "required_open_ids": ["q-0001"],
    }
    assert set(result) >= {
        "kind",
        "task_id",
        "status_stage",
        "active_stage",
        "action",
        "reason",
        "blocking",
        "next_command",
        "next_item",
        "commands",
        "progress",
    }


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/question_plan_regeneration/"
        "question-plan-regeneration.feature"
    ),
    scenario="@bdd-question-plan-regeneration-next-action-prefers-regeneration",
)
def test_next_action_prefers_regenerate_over_approve_for_stale_answers(
    tmp_path: Path,
) -> None:
    _init_task(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "question",
                "add",
                "--text",
                "Which database?",
                "--required-for-plan",
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
                "propose",
                "--criterion",
                "Database choice is honored.",
                "--text",
                "Initial plan.",
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
                "question",
                "answer",
                "q-0001",
                "--text",
                "SQLite.",
                "--from-user-chat",
            ],
        ).exit_code
        == 0
    )

    payload = _json(
        runner.invoke(app, ["--cwd", str(tmp_path), "--json", "next-action"])
    )

    result = payload["result"]
    assert result["action"] == "plan-regenerate"
    assert result["next_command"] == (
        "taskledger plan upsert --from-answers --file plan.md"
    )
    assert result["template_command"] == (
        "taskledger plan template --from-answers --file plan.md"
    )
    assert result["required_plan_fields"] == [
        "goal",
        "acceptance_criteria",
        "todos",
    ]
    assert result["recommended_plan_fields"] == [
        "files",
        "test_commands",
        "expected_outputs",
    ]
    assert result["blocking"][0]["kind"] == "stale_answers"
    assert result["next_item"] == {
        "kind": "answered_question",
        "id": "q-0001",
        "text": "Which database?",
        "status": "answered",
        "answer": "SQLite.",
        "answered_at": result["next_item"]["answered_at"],
        "required_for_plan": True,
        "plan_version": None,
    }
    assert result["commands"][0] == {
        "kind": "template",
        "label": "Write editable plan template",
        "command": (
            "taskledger plan template --from-answers --include-guidance --file plan.md"
        ),
        "primary": False,
    }
    assert result["commands"][1] == {
        "kind": "check",
        "label": "Validate plan input",
        "command": "taskledger plan check --file plan.md",
        "primary": False,
    }
    assert result["commands"][2] == {
        "kind": "regenerate",
        "label": "Regenerate plan from answers",
        "command": "taskledger plan upsert --from-answers --file plan.md",
        "primary": True,
    }
    assert result["progress"]["questions"] == {
        "required_open": 0,
        "required_open_ids": [],
        "answered_since_latest_plan": ["q-0001"],
    }
