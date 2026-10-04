from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.services.lock_diagnostics import (
    CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS,
    diagnose_lock,
)
from taskledger.storage.locks import read_lock
from taskledger.storage.task_store import (
    list_runs,
    resolve_task,
    resolve_v2_paths,
    task_lock_path,
)
from tests.support.builders import init_workspace

pytestmark = [pytest.mark.cli, pytest.mark.integration, pytest.mark.slow]


def _enable_event_logging(tmp_path: Path) -> None:
    config_path = tmp_path / "taskledger.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + "\n[event_logging]\nenabled = true\n",
        encoding="utf-8",
    )


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
    init_workspace(tmp_path)


def _setup_plan_review_task(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert (
        runner.invoke(
            app,
            [
                "--root",
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
            ["--root", str(tmp_path), "task", "activate", "plan-revision"],
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["--root", str(tmp_path), "plan", "start"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "--root",
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


# specmason: req=REQ-0039 ac=AC-0452
def test_plan_upsert_rejects_taskledger_storage_file(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)
    plan_path = _internal_plan_path(tmp_path)

    result = runner.invoke(
        app,
        [
            "--root",
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
        "taskledger plan export --version latest --file ./plan.revision.md",
        "taskledger plan check --file ./plan.revision.md",
        "taskledger plan upsert --auto-revise --file ./plan.revision.md",
    ]


# specmason: req=REQ-0039 ac=AC-0450
def test_plan_propose_and_regenerate_reject_taskledger_storage_file(
    tmp_path: Path,
) -> None:
    _setup_plan_review_task(tmp_path)
    plan_path = _internal_plan_path(tmp_path)

    assert (
        runner.invoke(app, ["--root", str(tmp_path), "plan", "revise"]).exit_code == 0
    )
    propose = runner.invoke(
        app,
        [
            "--root",
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
            "--root",
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


# specmason: req=REQ-0039 ac=AC-0449
def test_plan_export_round_trips_after_revision(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)
    review_v1 = runner.invoke(
        app,
        ["--root", str(tmp_path), "plan", "review", "--version", "1"],
    )
    assert review_v1.exit_code == 0, review_v1.stdout
    assert "| Approval readiness | Ready |" in review_v1.stdout
    exported = tmp_path / "plan.revision.md"

    export_result = runner.invoke(
        app,
        [
            "--root",
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

    updated_text = exported.read_text(encoding="utf-8").replace(
        "Remove out-of-scope release criteria.",
        "Remove out-of-scope release and CI criteria.",
    )
    exported.write_text(updated_text, encoding="utf-8")
    check_result = runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "plan",
            "check",
            "--file",
            str(exported),
        ],
    )
    assert check_result.exit_code == 0, check_result.stdout

    upsert_result = runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "--json",
            "plan",
            "upsert",
            "--auto-revise",
            "--file",
            str(exported),
        ],
    )
    assert upsert_result.exit_code == 0, upsert_result.stdout
    upsert_payload = _json(upsert_result)
    assert upsert_payload["result"]["plan_version"] == 2

    show_v1 = _json(
        runner.invoke(
            app,
            ["--root", str(tmp_path), "--json", "plan", "show", "--version", "1"],
        )
    )
    show_v2 = _json(
        runner.invoke(
            app,
            ["--root", str(tmp_path), "--json", "plan", "show", "--version", "2"],
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
    task = resolve_task(tmp_path, "plan-revision")
    revision_run_id = str(upsert_payload["result"]["revision_run_id"])
    revision_run = next(
        run for run in list_runs(tmp_path, task.id) if run.run_id == revision_run_id
    )
    assert revision_run.status == "finished"
    assert read_lock(task_lock_path(resolve_v2_paths(tmp_path), task.id)) is None
    assert task.status_stage == "plan_review"
    assert task.accepted_plan_version is None


# specmason: req=REQ-0039 ac=AC-0447
def test_plan_amend_drops_criteria_and_todos_and_records_event(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)
    _enable_event_logging(tmp_path)

    amend = runner.invoke(
        app,
        [
            "--root",
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
            ["--root", str(tmp_path), "--json", "plan", "show", "--version", "1"],
        )
    )
    show_v2 = _json(
        runner.invoke(
            app,
            ["--root", str(tmp_path), "--json", "plan", "show", "--version", "2"],
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


# specmason: req=REQ-0039 ac=AC-0448
def test_plan_amend_unknown_criterion_fails_without_mutation(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)

    amend = runner.invoke(
        app,
        [
            "--root",
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


# specmason: req=REQ-0039 ac=AC-0451
def test_plan_upsert_auto_revise_from_plan_review(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)
    plan_file = tmp_path / "plan-v2.md"
    plan_file.write_text(PLAN_V1.replace("v1", "v2"), encoding="utf-8")

    upsert = runner.invoke(
        app,
        [
            "--root",
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


# specmason: req=REQ-0039 ac=AC-0453
def test_plan_upsert_without_active_planning_suggests_revision_workflow(
    tmp_path: Path,
) -> None:
    _setup_plan_review_task(tmp_path)
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(PLAN_V1, encoding="utf-8")

    upsert = runner.invoke(
        app,
        [
            "--root",
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
    assert "plan upsert --auto-revise" in payload["error"]["message"]
    assert payload["error"]["details"]["next_commands"] == [
        "taskledger plan check --file ./plan.md",
        "taskledger plan upsert --auto-revise --file ./plan.md",
    ]


# specmason: req=REQ-0039 ac=AC-0446
def test_next_action_plan_review_mentions_revision_commands(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)

    next_action = runner.invoke(app, ["--root", str(tmp_path), "next-action"])
    assert next_action.exit_code == 0, next_action.stdout
    assert "Command: taskledger plan review --version 1" in next_action.stdout
    assert (
        "Accept plan after explicit user approval: "
        'taskledger plan accept --version 1 --note "User approved in harness."'
        in next_action.stdout
    )
    assert "Revise proposed plan: taskledger plan revise" not in next_action.stdout
    assert (
        "Export editable revision draft: "
        "taskledger plan export --version 1 --file ./plan.revision.md"
        in next_action.stdout
    )
    assert (
        "Check revision draft: taskledger plan check --file ./plan.revision.md"
        in next_action.stdout
    )
    assert (
        "Propose revised plan: "
        "taskledger plan upsert --auto-revise --file ./plan.revision.md"
        in next_action.stdout
    )


def test_plan_export_is_idempotent_without_overwriting_edits(tmp_path: Path) -> None:
    _setup_plan_review_task(tmp_path)
    exported = tmp_path / "plan.revision.md"
    args = [
        "--root",
        str(tmp_path),
        "--json",
        "plan",
        "export",
        "--version",
        "latest",
        "--file",
        str(exported),
    ]

    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stdout
    original = exported.read_text(encoding="utf-8")

    repeated = runner.invoke(app, args)
    assert repeated.exit_code == 0, repeated.stdout
    assert _json(repeated)["result"]["unchanged"] is True

    exported.write_text("user edits\n", encoding="utf-8")
    refusal = runner.invoke(app, args)
    assert refusal.exit_code != 0
    assert "Refusing to overwrite" in _json(refusal)["error"]["message"]
    assert exported.read_text(encoding="utf-8") == "user edits\n"

    overwritten = runner.invoke(app, [*args, "--overwrite"])
    assert overwritten.exit_code == 0, overwritten.stdout
    assert exported.read_text(encoding="utf-8") == original


def test_auto_revise_rejects_invalid_candidate_before_starting_run(
    tmp_path: Path,
) -> None:
    _setup_plan_review_task(tmp_path)
    task = resolve_task(tmp_path, "plan-revision")
    runs_before = list_runs(tmp_path, task.id)
    lock_path = task_lock_path(resolve_v2_paths(tmp_path), task.id)
    invalid_plan = tmp_path / "invalid-plan.md"
    invalid_plan.write_text("---\nacceptance_criteria: [\n---\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "--json",
            "plan",
            "upsert",
            "--auto-revise",
            "--file",
            str(invalid_plan),
        ],
    )

    assert result.exit_code != 0
    assert list_runs(tmp_path, task.id) == runs_before
    assert read_lock(lock_path) is None


def test_auto_revise_failure_reports_run_specific_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_plan_review_task(tmp_path)
    plan_file = tmp_path / "edited-plan.md"
    plan_file.write_text(PLAN_V1, encoding="utf-8")

    def fail_proposal(*args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("injected proposal failure")

    monkeypatch.setattr("taskledger.services.planning_flow.propose_plan", fail_proposal)
    result = runner.invoke(
        app,
        [
            "--root",
            str(tmp_path),
            "--json",
            "plan",
            "upsert",
            "--auto-revise",
            "--file",
            str(plan_file),
        ],
    )

    assert result.exit_code != 0, result.stdout
    error = _json(result)["error"]
    assert error["code"] == "PLAN_REVISION_INCOMPLETE"
    revision_run = error["details"]["revision_run"]
    assert revision_run["run_id"].startswith("run-")
    assert revision_run["status"] == "running"
    assert revision_run["has_matching_lock"] is True
    assert error["details"]["next_commands"] == [
        f"taskledger next-action --task {resolve_task(tmp_path, 'plan-revision').id}"
    ]


@pytest.mark.parametrize("entrypoint", ["start", "revise", "upsert", "amend"])
@pytest.mark.parametrize(
    ("harness_variable", "harness_name"),
    [
        ("PI_VERSION", "pi"),
        ("CODEX_VERSION", "codex"),
        ("OPENCODE_VERSION", "opencode"),
    ],
)
def test_planning_run_entry_paths_preserve_harness_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
    harness_variable: str,
    harness_name: str,
) -> None:
    _setup_plan_review_task(tmp_path)
    for variable in (
        "TASKLEDGER_ACTOR_TYPE",
        "TASKLEDGER_ACTOR_NAME",
        "TASKLEDGER_ACTOR_ROLE",
        "TASKLEDGER_HARNESS",
        "TASKLEDGER_OWNER_PID",
        "TASKLEDGER_HARNESS_PID",
        "CODEX_VERSION",
        "OPENCODE_VERSION",
        "PI_VERSION",
        "PI_SESSION_ID",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(harness_variable, "test")
    monkeypatch.setenv("TASKLEDGER_SESSION_ID", "session-123")

    command = ["plan", entrypoint]
    if entrypoint == "upsert":
        draft = tmp_path / "edited-plan.md"
        draft.write_text(PLAN_V1, encoding="utf-8")
        command = [
            "plan",
            "upsert",
            "--auto-revise",
            "--file",
            str(draft),
        ]
    elif entrypoint == "amend":
        command = ["plan", "amend", "--reason", "Verify harness identity."]

    result = runner.invoke(app, ["--root", str(tmp_path), "--json", *command])
    assert result.exit_code == 0, result.stdout

    task = resolve_task(tmp_path, "plan-revision")
    planning_runs = [
        run for run in list_runs(tmp_path, task.id) if run.run_type == "planning"
    ]
    revision_run = max(
        planning_runs, key=lambda run: int(run.run_id.removeprefix("run-"))
    )
    assert revision_run.actor.tool == harness_name
    assert revision_run.actor.session_id == "session-123"
    assert revision_run.actor.pid is None
    assert revision_run.actor.command_pid is not None
    assert revision_run.actor.pid_scope == "unverifiable_harness"
    assert revision_run.harness is not None
    assert revision_run.harness.name == harness_name
    assert revision_run.harness.session_id == "session-123"

    lock_path = task_lock_path(resolve_v2_paths(tmp_path), task.id)
    lock = read_lock(lock_path)
    if entrypoint in {"start", "revise"}:
        assert lock is not None
        assert lock.holder.pid is None
        assert lock.holder.command_pid is not None
        assert lock.holder.pid_scope == "unverifiable_harness"
        assert lock.harness is not None and lock.harness.name == harness_name
        diagnostics = diagnose_lock(
            lock,
            current_host=lock.holder.host or "unknown",
        )
        assert diagnostics.classification != CLASSIFICATION_ACTIVE_DEAD_LOCAL_PROCESS
    else:
        assert lock is None
        assert revision_run.status == "finished"
