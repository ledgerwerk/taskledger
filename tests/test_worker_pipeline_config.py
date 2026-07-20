from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.project_config import (
    WorkerPipelineConfig,
    _validate_project_config_overrides,
    merge_project_config,
)


def _step(
    step_id: str,
    *,
    lifecycle_stage: str,
    base_context: str,
    **extra: object,
) -> dict[str, object]:
    return {
        "id": step_id,
        "lifecycle_stage": lifecycle_stage,
        "base_context": base_context,
        **extra,
    }


def _pipeline(*steps: dict[str, object], **extra: object) -> dict[str, object]:
    return {
        "enabled": True,
        "name": "worker-pipeline-test",
        "mode": "available",
        "steps": list(steps),
        **extra,
    }


# specmason: req=REQ-0072 ac=AC-0808
def test_no_worker_pipeline_section_preserves_default_config() -> None:
    config = merge_project_config({})

    assert config.worker_pipeline is None


# specmason: req=REQ-0072 ac=AC-0806
# specmason: req=REQ-0072 ac=AC-0807
def test_disabled_worker_pipeline_section_returns_disabled_config() -> None:
    config = merge_project_config(
        {
            "worker_pipeline": {
                "name": "optional-pipeline",
                "steps": [
                    _step(
                        "planner",
                        lifecycle_stage="planning",
                        base_context="planner",
                    )
                ],
            }
        }
    )

    assert config.worker_pipeline == WorkerPipelineConfig(
        enabled=False,
        name="optional-pipeline",
        mode="available",
        steps=config.worker_pipeline.steps if config.worker_pipeline else (),
    )
    assert config.worker_pipeline is not None
    assert config.worker_pipeline.steps[0].label == "Planner"
    assert config.worker_pipeline.steps[0].actor_role == "planner"


# specmason: req=REQ-0072 ac=AC-0811
def test_worker_pipeline_parse_three_step_config() -> None:
    config = merge_project_config(
        {
            "worker_pipeline": _pipeline(
                _step("planner", lifecycle_stage="planning", base_context="planner"),
                _step(
                    "implementer",
                    lifecycle_stage="implementation",
                    base_context="implementer",
                    kind="todo",
                ),
                _step(
                    "validator",
                    lifecycle_stage="validation",
                    base_context="validator",
                    kind="validate",
                ),
                mode="guided",
                name="simple-three-context",
            )
        }
    )

    assert config.worker_pipeline is not None
    assert config.worker_pipeline.enabled is True
    assert config.worker_pipeline.name == "simple-three-context"
    assert config.worker_pipeline.mode == "guided"
    assert config.worker_pipeline.step_ids() == ("planner", "implementer", "validator")
    assert config.worker_pipeline.steps[1].kind == "todo"
    assert config.worker_pipeline.steps[2].actor_role == "validator"


# specmason: req=REQ-0072 ac=AC-0810
def test_worker_pipeline_parse_four_step_config_without_skeletor() -> None:
    config = merge_project_config(
        {
            "worker_pipeline": _pipeline(
                _step("planner", lifecycle_stage="planning", base_context="planner"),
                _step(
                    "tester",
                    lifecycle_stage="implementation",
                    base_context="implementer",
                    kind="check",
                    test_command_policy="may_fail",
                ),
                _step(
                    "coder",
                    lifecycle_stage="implementation",
                    base_context="implementer",
                    kind="todo",
                    test_command_policy="must_pass",
                ),
                _step(
                    "reviewer",
                    lifecycle_stage="review",
                    base_context="code-reviewer",
                    kind="review",
                ),
                name="tdd-four-context",
            )
        }
    )

    assert config.worker_pipeline is not None
    assert config.worker_pipeline.step_ids() == (
        "planner",
        "tester",
        "coder",
        "reviewer",
    )
    assert config.worker_pipeline.steps[1].test_command_policy == "may_fail"
    assert config.worker_pipeline.steps[3].actor_role == "reviewer"


# specmason: req=REQ-0072 ac=AC-0809
def test_worker_pipeline_parse_custom_worker_name() -> None:
    config = merge_project_config(
        {
            "worker_pipeline": _pipeline(
                _step("planner", lifecycle_stage="planning", base_context="planner"),
                _step(
                    "api-designer",
                    lifecycle_stage="implementation",
                    base_context="implementer",
                    description="Design public interfaces first.",
                    todo_tag="api-design",
                ),
                _step(
                    "coder",
                    lifecycle_stage="implementation",
                    base_context="implementer",
                ),
                _step(
                    "domain-reviewer",
                    lifecycle_stage="review",
                    base_context="spec-reviewer",
                    kind="review",
                ),
                name="api-contract-first",
                mode="template",
            )
        }
    )

    assert config.worker_pipeline is not None
    api_designer = config.worker_pipeline.resolve_step("api-designer")
    assert api_designer.label == "Api Designer"
    assert api_designer.todo_tag == "api-design"
    domain_reviewer = config.worker_pipeline.resolve_step("domain-reviewer")
    assert domain_reviewer.actor_role == "reviewer"


# specmason: req=REQ-0072 ac=AC-0811
def test_worker_pipeline_enabled_requires_steps() -> None:
    with pytest.raises(LaunchError, match="at least one step"):
        _validate_project_config_overrides(
            {"worker_pipeline": {"enabled": True}},
            Path("taskledger.toml"),
        )


# specmason: req=REQ-0072 ac=AC-0811
def test_worker_pipeline_duplicate_step_ids_fail() -> None:
    with pytest.raises(
        LaunchError,
        match="Duplicate worker_pipeline.steps id 'tester'",
    ):
        _validate_project_config_overrides(
            {
                "worker_pipeline": _pipeline(
                    _step(
                        "tester",
                        lifecycle_stage="implementation",
                        base_context="implementer",
                    ),
                    _step(
                        "tester",
                        lifecycle_stage="review",
                        base_context="code-reviewer",
                    ),
                )
            },
            Path("taskledger.toml"),
        )


# specmason: req=REQ-0072 ac=AC-0811
def test_worker_pipeline_invalid_step_id_fails() -> None:
    with pytest.raises(LaunchError, match="must match"):
        _validate_project_config_overrides(
            {
                "worker_pipeline": _pipeline(
                    _step("BadStep", lifecycle_stage="planning", base_context="planner")
                )
            },
            Path("taskledger.toml"),
        )


# specmason: req=REQ-0072 ac=AC-0811
def test_worker_pipeline_invalid_base_context_fails() -> None:
    with pytest.raises(LaunchError, match="base_context"):
        _validate_project_config_overrides(
            {
                "worker_pipeline": _pipeline(
                    _step(
                        "tester",
                        lifecycle_stage="implementation",
                        base_context="test-writer",
                    )
                )
            },
            Path("taskledger.toml"),
        )


# specmason: req=REQ-0072 ac=AC-0811
def test_worker_pipeline_invalid_lifecycle_stage_fails() -> None:
    with pytest.raises(LaunchError, match="lifecycle_stage"):
        _validate_project_config_overrides(
            {
                "worker_pipeline": _pipeline(
                    _step(
                        "tester",
                        lifecycle_stage="implementing",
                        base_context="implementer",
                    )
                )
            },
            Path("taskledger.toml"),
        )


# specmason: req=REQ-0072 ac=AC-0809
def test_worker_pipeline_unknown_keys_fail() -> None:
    with pytest.raises(LaunchError, match="Unknown worker_pipeline keys"):
        _validate_project_config_overrides(
            {"worker_pipeline": {"enabled": True, "surprise": "nope"}},
            Path("taskledger.toml"),
        )

    with pytest.raises(LaunchError, match="Unknown worker_pipeline.steps\\[1\\] keys"):
        _validate_project_config_overrides(
            {
                "worker_pipeline": _pipeline(
                    _step(
                        "tester",
                        lifecycle_stage="implementation",
                        base_context="implementer",
                        surprise="nope",
                    )
                )
            },
            Path("taskledger.toml"),
        )
