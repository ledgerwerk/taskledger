from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.storage.task_store import resolve_task


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


PLAN_V1 = """---
goal: Keep revision workflow safe.
files:
  - CHANGELOG.md
  - RELEASE.md
  - .github/workflows/ci.yml
test_commands:
  - pytest -q tests/test_plan_revision_workflow.py
expected_outputs:
  - pytest exits 0
acceptance_criteria:
  - id: ac-0001
    text: Keep plan revisions auditable.
    mandatory: true
  - id: ac-0002
    text: Remove out-of-scope release criteria.
    mandatory: true
todos:
  - id: plan-todo-0001
    text: Add safe plan revision interfaces.
    mandatory: true
    validation_hint: pytest -q tests/test_plan_revision_workflow.py
  - id: plan-todo-0002
    text: Update docs for revision workflow.
    mandatory: true
---

# Plan

Keep revisions in lifecycle-managed commands.
"""


def _json(result) -> dict[str, object]:
    return json.loads(result.stdout)


def _init_project(tmp_path: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(tmp_path), "init"]).exit_code == 0


def _setup_plan_review_task(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "task",
                "create",
                "plan-revision",
                "--slug",
                "plan-revision",
                "--description",
                "Exercise plan revision workflow.",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "task", "activate", "plan-revision"],
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(tmp_path), "plan", "start"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(tmp_path),
                "plan",
                "upsert",
                "--text",
                PLAN_V1,
            ],
        ).exit_code
        == 0
    )


def _internal_plan_path(tmp_path: Path) -> Path:
    matches = sorted((tmp_path / ".taskledger").glob("**/plan-v1.md"))
    assert matches
    return matches[0]


def test_plan_upsert_rejects_taskledger_storage_file(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)
    plan_path = _internal_plan_path(tmp_path)

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "upsert",
            "--file",
            str(plan_path),
        ],
    )

    assert result.exit_code == 2, result.stdout
    payload = _json(result)
    assert payload["ok"] is False
    assert "Taskledger storage" in payload["error"]["message"]
    next_commands = payload["error"]["details"]["next_commands"]
    assert next_commands == [
        "taskledger plan revise",
        "taskledger plan export --version latest --file ./plan.md",
        "taskledger plan upsert --file ./plan.md",
    ]


def test_plan_propose_and_regenerate_reject_taskledger_storage_file(
    tmp_path: Path,
) -> None:
    _setup_plan_review_task(tmp_path)
    plan_path = _internal_plan_path(tmp_path)

    assert runner.invoke(app, ["--cwd", str(tmp_path), "plan", "revise"]).exit_code == 0
    propose = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "propose",
            "--file",
            str(plan_path),
        ],
    )
    assert propose.exit_code == 2, propose.stdout
    propose_payload = _json(propose)
    assert "Taskledger storage" in propose_payload["error"]["message"]

    regenerate = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "regenerate",
            "--from-answers",
            "--file",
            str(plan_path),
        ],
    )
    assert regenerate.exit_code == 2, regenerate.stdout
    regenerate_payload = _json(regenerate)
    assert "Taskledger storage" in regenerate_payload["error"]["message"]


def test_plan_export_round_trips_after_revision(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)
    exported = tmp_path / "plan.md"

    export_result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "export",
            "--version",
            "latest",
            "--file",
            str(exported),
        ],
    )
    assert export_result.exit_code == 0, export_result.stdout

    assert runner.invoke(app, ["--cwd", str(tmp_path), "plan", "revise"]).exit_code == 0

    updated_text = exported.read_text(encoding="utf-8").replace(
        "Remove out-of-scope release criteria.",
        "Remove out-of-scope release and CI criteria.",
    )
    exported.write_text(updated_text, encoding="utf-8")

    upsert_result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "--json", "plan", "upsert", "--file", str(exported)],
    )
    assert upsert_result.exit_code == 0, upsert_result.stdout
    upsert_payload = _json(upsert_result)
    assert upsert_payload["result"]["plan_version"] == 2

    show_v1 = _json(
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "plan", "show", "--version", "1"],
        )
    )
    show_v2 = _json(
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "plan", "show", "--version", "2"],
        )
    )
    assert (
        show_v1["result"]["plan"]["criteria"][1]["text"]
        == "Remove out-of-scope release criteria."
    )
    assert (
        show_v2["result"]["plan"]["criteria"][1]["text"]
        == "Remove out-of-scope release and CI criteria."
    )


def test_plan_amend_drops_criteria_and_todos_and_records_event(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)

    amend = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "amend",
            "--drop-criterion",
            "ac-0002",
            "--drop-todo",
            "plan-todo-0002",
            "--remove-file",
            "RELEASE.md",
            "--reason",
            "User reduced scope.",
        ],
    )
    assert amend.exit_code == 0, amend.stdout
    amend_payload = _json(amend)
    assert amend_payload["result"]["operation"] == "amended"
    assert amend_payload["result"]["from_plan_version"] == 1
    assert amend_payload["result"]["plan_version"] == 2

    show_v1 = _json(
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "plan", "show", "--version", "1"],
        )
    )
    show_v2 = _json(
        runner.invoke(
            app,
            ["--cwd", str(tmp_path), "--json", "plan", "show", "--version", "2"],
        )
    )
    assert len(show_v1["result"]["plan"]["criteria"]) == 2
    assert len(show_v2["result"]["plan"]["criteria"]) == 1
    assert len(show_v1["result"]["plan"]["todos"]) == 2
    assert len(show_v2["result"]["plan"]["todos"]) == 1
    assert "RELEASE.md" in show_v1["result"]["plan"]["files"]
    assert "RELEASE.md" not in show_v2["result"]["plan"]["files"]

    event_files = sorted((tmp_path / ".taskledger").glob("**/events/*.ndjson"))
    assert event_files
    events = []
    for path in event_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    assert any(item.get("event") == "plan.amended" for item in events)


def test_plan_amend_unknown_criterion_fails_without_mutation(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)

    amend = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "amend",
            "--drop-criterion",
            "ac-9999",
            "--reason",
            "No-op",
        ],
    )
    assert amend.exit_code == 2
    payload = _json(amend)
    assert payload["error"]["message"] == "Unknown criterion id(s): ac-9999"

    task = resolve_task(tmp_path, "plan-revision")
    assert task.latest_plan_version == 1


def test_plan_upsert_auto_revise_from_plan_review(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)
    plan_file = tmp_path / "plan-v2.md"
    plan_file.write_text(PLAN_V1.replace("v1", "v2"), encoding="utf-8")

    upsert = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "upsert",
            "--auto-revise",
            "--file",
            str(plan_file),
        ],
    )

    assert upsert.exit_code == 0, upsert.stdout
    payload = _json(upsert)
    assert payload["result"]["plan_version"] == 2
    assert payload["result"]["auto_revise_started"] is True
    assert payload["result"]["revision_run_id"].startswith("run-")


def test_plan_upsert_without_active_planning_suggests_revision_workflow(
    tmp_path: Path,
) -> None:
    _setup_plan_review_task(tmp_path)
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(PLAN_V1, encoding="utf-8")

    upsert = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "--json",
            "plan",
            "upsert",
            "--file",
            str(plan_file),
        ],
    )

    assert upsert.exit_code == 3, upsert.stdout
    payload = _json(upsert)
    assert "Plan proposals require active planning." in payload["error"]["message"]
    assert "taskledger plan revise" in payload["error"]["message"]
    assert payload["error"]["details"]["next_commands"] == [
        "taskledger plan revise",
        "taskledger plan export --version latest --file ./plan.md",
        "taskledger plan upsert --file ./plan.md",
    ]


def test_next_action_plan_review_mentions_revision_commands(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)

    next_action = runner.invoke(app, ["--cwd", str(tmp_path), "next-action"])
    assert next_action.exit_code == 0, next_action.stdout
    assert "Command: taskledger plan review --version 1" in next_action.stdout
    assert (
        "Accept plan after explicit user approval: "
        'taskledger plan accept --version 1 --note "User approved in harness."'
        in next_action.stdout
    )
    assert "Revise proposed plan: taskledger plan revise" in next_action.stdout
    assert (
        "Export editable plan: taskledger plan export --version 1 --file ./plan.md"
        in next_action.stdout
    )
