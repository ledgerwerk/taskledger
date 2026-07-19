from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from taskledger.cli import app


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _runner()


def _append_pipeline_config(path: Path, *, mode: str = "template") -> None:
    config = f"""
[worker_pipeline]
enabled = true
name = "api-contract-first"
mode = "{mode}"

[[worker_pipeline.steps]]
id = "planner"
lifecycle_stage = "planning"
base_context = "planner"

[[worker_pipeline.steps]]
id = "api-designer"
label = "API Designer"
lifecycle_stage = "implementation"
base_context = "implementer"
kind = "todo"

[[worker_pipeline.steps]]
id = "coder"
lifecycle_stage = "implementation"
base_context = "implementer"
kind = "todo"

[[worker_pipeline.steps]]
id = "domain-reviewer"
lifecycle_stage = "review"
base_context = "spec-reviewer"
kind = "review"
"""
    current = path.read_text(encoding="utf-8")
    path.write_text(f"{current.rstrip()}\n\n{config.strip()}\n", encoding="utf-8")


def _setup_planning_task(workspace: Path) -> None:
    assert runner.invoke(app, ["--cwd", str(workspace), "init"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "--cwd",
                str(workspace),
                "task",
                "create",
                "Worker template task",
                "--slug",
                "worker-template",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["--cwd", str(workspace), "task", "activate", "worker-template"],
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["--cwd", str(workspace), "plan", "start"]).exit_code == 0


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/worker_pipeline_plan_template/worker-"
        "pipeline-plan-template.feature"
    ),
    scenario=(
        "@bdd-worker-pipeline-plan-template-plan-template-unchanged-without-"
        "worker-pipeline"
    ),
)
def test_plan_template_unchanged_without_worker_pipeline(tmp_path: Path) -> None:
    _setup_planning_task(tmp_path)

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "plan", "template", "--task", "worker-template"],
    )

    assert result.exit_code == 0, result.stdout
    assert "## Optional worker pipeline todo hints" not in result.stdout
    assert "worker_step:" not in result.stdout


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/worker_pipeline_plan_template/worker-"
        "pipeline-plan-template.feature"
    ),
    scenario=(
        "@bdd-worker-pipeline-plan-template-plan-template-requires-opt-in-"
        "flag-for-worker-pipeline-hints"
    ),
)
def test_plan_template_requires_opt_in_flag_for_worker_pipeline_hints(
    tmp_path: Path,
) -> None:
    _setup_planning_task(tmp_path)
    _append_pipeline_config(
        tmp_path / ".ledger" / "taskledger" / "config.toml", mode="template"
    )

    result = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "plan", "template", "--task", "worker-template"],
    )

    assert result.exit_code == 0, result.stdout
    assert "## Optional worker pipeline todo hints" not in result.stdout
    assert "api-designer" not in result.stdout


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/worker_pipeline_plan_template/worker-"
        "pipeline-plan-template.feature"
    ),
    scenario=(
        "@bdd-worker-pipeline-plan-template-worker-plan-template-uses-"
        "configured-steps-not-hardcoded-names"
    ),
)
def test_worker_plan_template_uses_configured_steps_not_hardcoded_names(
    tmp_path: Path,
) -> None:
    _setup_planning_task(tmp_path)
    _append_pipeline_config(
        tmp_path / ".ledger" / "taskledger" / "config.toml", mode="template"
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "template",
            "--task",
            "worker-template",
            "--with-worker-pipeline",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "## Optional worker pipeline todo hints" in result.stdout
    assert 'worker_step: "api-designer"' in result.stdout
    assert 'worker_step: "coder"' in result.stdout
    assert "skeletor" not in result.stdout


@pytest.mark.specweave(
    feature=(
        "specs/behavior/features/worker_pipeline_plan_template/worker-"
        "pipeline-plan-template.feature"
    ),
    scenario=(
        "@bdd-worker-pipeline-plan-template-plan-template-worker-hints-"
        "require-template-or-guided-mode"
    ),
)
def test_plan_template_worker_hints_require_template_or_guided_mode(
    tmp_path: Path,
) -> None:
    _setup_planning_task(tmp_path)
    _append_pipeline_config(
        tmp_path / ".ledger" / "taskledger" / "config.toml", mode="available"
    )

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(tmp_path),
            "plan",
            "template",
            "--task",
            "worker-template",
            "--with-worker-pipeline",
        ],
    )

    assert result.exit_code != 0
    output = f"{result.stdout}{getattr(result, 'stderr', '')}"
    assert "mode = 'template' or 'guided'" in output
