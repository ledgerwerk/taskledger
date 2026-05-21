from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from taskledger.errors import LaunchError

WORKER_PIPELINE_CONFIG_KEYS = frozenset({"enabled", "name", "mode", "steps"})
WORKER_STEP_CONFIG_KEYS = frozenset(
    {
        "id",
        "label",
        "lifecycle_stage",
        "base_context",
        "actor_role",
        "kind",
        "description",
        "required_output",
        "must_not",
        "todo_tag",
        "test_command_policy",
    }
)
VALID_WORKER_PIPELINE_MODES = frozenset({"available", "template", "guided"})
VALID_WORKER_STEP_KINDS = frozenset(
    {"plan", "todo", "check", "review", "validate", "custom"}
)
VALID_WORKER_TEST_COMMAND_POLICIES = frozenset({"none", "may_fail", "must_pass"})
VALID_WORKER_BASE_CONTEXTS = frozenset(
    {
        "planner",
        "implementer",
        "validator",
        "reviewer",
        "spec-reviewer",
        "code-reviewer",
        "full",
    }
)
VALID_WORKER_LIFECYCLE_STAGES = frozenset(
    {"planning", "implementation", "validation", "review", "full"}
)
VALID_WORKER_ACTOR_ROLES = frozenset(
    {"planner", "implementer", "validator", "reviewer", "operator"}
)
WORKER_STEP_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(slots=True, frozen=True)
class WorkerStepConfig:
    id: str
    label: str
    lifecycle_stage: str
    base_context: str
    actor_role: str | None = None
    kind: str = "custom"
    description: str | None = None
    required_output: tuple[str, ...] = ()
    must_not: tuple[str, ...] = ()
    todo_tag: str | None = None
    test_command_policy: str = "none"

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "label": self.label,
            "lifecycle_stage": self.lifecycle_stage,
            "base_context": self.base_context,
            "kind": self.kind,
            "required_output": list(self.required_output),
            "must_not": list(self.must_not),
            "test_command_policy": self.test_command_policy,
        }
        if self.actor_role is not None:
            payload["actor_role"] = self.actor_role
        if self.description is not None:
            payload["description"] = self.description
        if self.todo_tag is not None:
            payload["todo_tag"] = self.todo_tag
        return payload


@dataclass(slots=True, frozen=True)
class WorkerPipelineConfig:
    enabled: bool = False
    name: str = "worker-pipeline"
    mode: str = "available"
    steps: tuple[WorkerStepConfig, ...] = ()

    def step_ids(self) -> tuple[str, ...]:
        return tuple(step.id for step in self.steps)

    def resolve_step(self, step_id: str) -> WorkerStepConfig:
        for step in self.steps:
            if step.id == step_id:
                return step
        valid = ", ".join(self.step_ids()) or "(none configured)"
        raise LaunchError(
            f"Unknown worker step '{step_id}'. Configured step ids: {valid}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "name": self.name,
            "mode": self.mode,
            "steps": [step.to_dict() for step in self.steps],
        }


def validate_worker_pipeline(raw: object, path: Path) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise LaunchError(
            f"Project config key 'worker_pipeline' must be a table in {path}"
        )
    unknown_keys = set(raw.keys()) - WORKER_PIPELINE_CONFIG_KEYS
    if unknown_keys:
        joined = ", ".join(sorted(unknown_keys))
        raise LaunchError(f"Unknown worker_pipeline keys in {path}: {joined}")
    enabled = raw.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise LaunchError(f"worker_pipeline.enabled must be a boolean in {path}")
    name = raw.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise LaunchError(f"worker_pipeline.name must be a non-empty string in {path}")
    mode = raw.get("mode")
    if mode is not None:
        if not isinstance(mode, str):
            raise LaunchError(f"worker_pipeline.mode must be a string in {path}")
        if mode not in VALID_WORKER_PIPELINE_MODES:
            allowed = ", ".join(sorted(VALID_WORKER_PIPELINE_MODES))
            raise LaunchError(
                f"worker_pipeline.mode must be one of {allowed} in {path}"
            )
    raw_steps = raw.get("steps")
    if raw_steps is None:
        steps: list[dict[str, object]] = []
    elif isinstance(raw_steps, list):
        steps = []
        for item in raw_steps:
            if not isinstance(item, dict):
                raise LaunchError(
                    f"worker_pipeline.steps must be an array of tables in {path}"
                )
            steps.append(item)
    else:
        raise LaunchError(f"worker_pipeline.steps must be an array of tables in {path}")
    seen_ids: set[str] = set()
    for index, step in enumerate(steps, start=1):
        step_id = validate_worker_step(step, path, index=index)
        if step_id in seen_ids:
            raise LaunchError(
                f"Duplicate worker_pipeline.steps id '{step_id}' in {path}"
            )
        seen_ids.add(step_id)
    if bool(enabled) and not steps:
        raise LaunchError(
            "worker_pipeline.steps must contain at least one step "
            f"when enabled in {path}"
        )


def validate_worker_step(data: dict[str, object], path: Path, *, index: int) -> str:
    validate_worker_step_unknown_keys(data, path, index=index)
    step_id = validate_worker_step_id(data, path, index=index)
    validate_worker_step_optional_text_fields(data, path, index=index)
    validate_worker_step_required_choice(
        data,
        field_name="lifecycle_stage",
        valid_values=VALID_WORKER_LIFECYCLE_STAGES,
        path=path,
        index=index,
    )
    validate_worker_step_required_choice(
        data,
        field_name="base_context",
        valid_values=VALID_WORKER_BASE_CONTEXTS,
        path=path,
        index=index,
    )
    validate_worker_step_optional_choice(
        data,
        field_name="actor_role",
        valid_values=VALID_WORKER_ACTOR_ROLES,
        path=path,
        index=index,
    )
    validate_worker_step_optional_choice(
        data,
        field_name="kind",
        valid_values=VALID_WORKER_STEP_KINDS,
        path=path,
        index=index,
    )
    validate_worker_step_optional_choice(
        data,
        field_name="test_command_policy",
        valid_values=VALID_WORKER_TEST_COMMAND_POLICIES,
        path=path,
        index=index,
    )
    validate_worker_step_string_list(data, "required_output", path, index=index)
    validate_worker_step_string_list(data, "must_not", path, index=index)
    return step_id


def validate_worker_step_unknown_keys(
    data: dict[str, object],
    path: Path,
    *,
    index: int,
) -> None:
    unknown_keys = set(data.keys()) - WORKER_STEP_CONFIG_KEYS
    if unknown_keys:
        joined = ", ".join(sorted(unknown_keys))
        raise LaunchError(
            f"Unknown worker_pipeline.steps[{index}] keys in {path}: {joined}"
        )


def validate_worker_step_id(
    data: dict[str, object],
    path: Path,
    *,
    index: int,
) -> str:
    step_id = data.get("id")
    if not isinstance(step_id, str) or not step_id.strip():
        raise LaunchError(f"worker_pipeline.steps[{index}].id is required in {path}")
    if WORKER_STEP_ID_RE.fullmatch(step_id) is None:
        raise LaunchError(
            f"worker_pipeline.steps[{index}].id must match "
            f"{WORKER_STEP_ID_RE.pattern!r} in {path}"
        )
    return step_id


def validate_worker_step_optional_text_fields(
    data: dict[str, object],
    path: Path,
    *,
    index: int,
) -> None:
    for field_name in ("label", "description", "todo_tag"):
        value = data.get(field_name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise LaunchError(
                f"worker_pipeline.steps[{index}].{field_name} "
                f"must be a non-empty string in {path}"
            )


def validate_worker_step_required_choice(
    data: dict[str, object],
    *,
    field_name: str,
    valid_values: frozenset[str],
    path: Path,
    index: int,
) -> None:
    value = data.get(field_name)
    if not isinstance(value, str):
        raise LaunchError(
            f"worker_pipeline.steps[{index}].{field_name} is required in {path}"
        )
    if value not in valid_values:
        allowed = ", ".join(sorted(valid_values))
        raise LaunchError(
            f"worker_pipeline.steps[{index}].{field_name} must be one of "
            f"{allowed} in {path}"
        )


def validate_worker_step_optional_choice(
    data: dict[str, object],
    *,
    field_name: str,
    valid_values: frozenset[str],
    path: Path,
    index: int,
) -> None:
    value = data.get(field_name)
    if value is None:
        return
    if not isinstance(value, str):
        raise LaunchError(
            f"worker_pipeline.steps[{index}].{field_name} must be a string in {path}"
        )
    if value not in valid_values:
        allowed = ", ".join(sorted(valid_values))
        raise LaunchError(
            f"worker_pipeline.steps[{index}].{field_name} must be one of "
            f"{allowed} in {path}"
        )


def validate_worker_step_string_list(
    data: dict[str, object],
    field_name: str,
    path: Path,
    *,
    index: int,
) -> None:
    value = data.get(field_name)
    if value is None:
        return
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise LaunchError(
            f"worker_pipeline.steps[{index}].{field_name} "
            f"must be a list of non-empty strings in {path}"
        )


def parse_worker_pipeline(
    raw: object,
    base: WorkerPipelineConfig | None,
) -> WorkerPipelineConfig | None:
    if raw is None:
        return base
    if not isinstance(raw, dict):
        return base
    raw_steps = raw.get("steps")
    step_items = raw_steps if isinstance(raw_steps, list) else []
    steps = tuple(
        parse_worker_step(item) for item in step_items if isinstance(item, dict)
    )
    return WorkerPipelineConfig(
        enabled=bool(raw.get("enabled", False)),
        name=str(raw.get("name", "worker-pipeline")),
        mode=str(raw.get("mode", "available")),
        steps=steps,
    )


def parse_worker_step(raw: dict[str, object]) -> WorkerStepConfig:
    step_id = str(raw["id"])
    base_context = str(raw["base_context"])
    actor_role = (
        str(raw["actor_role"])
        if isinstance(raw.get("actor_role"), str)
        else default_worker_actor_role(base_context)
    )
    label = (
        str(raw["label"])
        if isinstance(raw.get("label"), str)
        else default_worker_step_label(step_id)
    )
    required_output = worker_string_tuple(raw.get("required_output"))
    must_not = worker_string_tuple(raw.get("must_not"))
    return WorkerStepConfig(
        id=step_id,
        label=label,
        lifecycle_stage=str(raw["lifecycle_stage"]),
        base_context=base_context,
        actor_role=actor_role,
        kind=str(raw.get("kind", "custom")),
        description=(
            str(raw["description"]) if isinstance(raw.get("description"), str) else None
        ),
        required_output=required_output,
        must_not=must_not,
        todo_tag=str(raw["todo_tag"]) if isinstance(raw.get("todo_tag"), str) else None,
        test_command_policy=str(raw.get("test_command_policy", "none")),
    )


def default_worker_actor_role(base_context: str) -> str:
    if base_context == "planner":
        return "planner"
    if base_context == "validator":
        return "validator"
    if base_context == "full":
        return "operator"
    if base_context in {"reviewer", "spec-reviewer", "code-reviewer"}:
        return "reviewer"
    return "implementer"


def default_worker_step_label(step_id: str) -> str:
    return step_id.replace("-", " ").replace("_", " ").title()


def worker_string_tuple(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str))


__all__ = [
    "WORKER_PIPELINE_CONFIG_KEYS",
    "WORKER_STEP_CONFIG_KEYS",
    "VALID_WORKER_PIPELINE_MODES",
    "VALID_WORKER_STEP_KINDS",
    "VALID_WORKER_TEST_COMMAND_POLICIES",
    "VALID_WORKER_BASE_CONTEXTS",
    "VALID_WORKER_LIFECYCLE_STAGES",
    "VALID_WORKER_ACTOR_ROLES",
    "WORKER_STEP_ID_RE",
    "WorkerPipelineConfig",
    "WorkerStepConfig",
    "default_worker_actor_role",
    "default_worker_step_label",
    "parse_worker_pipeline",
    "parse_worker_step",
    "validate_worker_pipeline",
    "validate_worker_step",
    "validate_worker_step_id",
    "validate_worker_step_optional_choice",
    "validate_worker_step_optional_text_fields",
    "validate_worker_step_required_choice",
    "validate_worker_step_string_list",
    "validate_worker_step_unknown_keys",
    "worker_string_tuple",
]
