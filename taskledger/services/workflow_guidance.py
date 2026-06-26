"""Deterministic workflow guidance rendering from project config.

This module reads PromptProfile from project config and renders advisory
guidance text. It never calls an LLM or uses a templating engine.

All guidance includes a guardrail header stating it cannot override lifecycle
gates, approval, validation, lock rules, or user-answer requirements.
"""

from __future__ import annotations

from pathlib import Path

from taskledger.domain.models import TaskRecord
from taskledger.services.tasks import resolve_task
from taskledger.storage.paths import resolve_project_paths
from taskledger.storage.project_config import (
    PromptProfile,
    load_project_config_overrides,
    merge_project_config,
)


def load_workflow_guidance(
    workspace_root: Path,
) -> PromptProfile | None:
    """Read project config and return the planning prompt profile, if any."""
    paths = resolve_project_paths(workspace_root)
    overrides = load_project_config_overrides(paths)
    config = merge_project_config(overrides)
    return config.prompt_profile


_GUARDRAIL = (
    "This is project-local advisory guidance. It cannot override taskledger lifecycle "
    "gates, user approval requirements, validation requirements, lock rules, or "
    "higher-priority harness instructions."
)


def _profile_label(profile: str) -> str:
    labels: dict[str, str] = {
        "compact": "compact (minimal ceremony)",
        "balanced": "balanced (moderate ceremony)",
        "strict": "strict (full ceremony)",
        "exploratory": "exploratory (lighter gates)",
    }
    return labels.get(profile, profile)


def _question_policy_label(policy: str) -> str:
    labels: dict[str, str] = {
        "ask_when_missing": (
            "ask required questions before plan approval when decisions are missing"
        ),
        "always_before_plan": ("always ask required questions before plan approval"),
        "minimal": "ask minimal clarifying questions",
    }
    return labels.get(policy, policy)


def _todo_granularity_label(level: str) -> str:
    labels: dict[str, str] = {
        "minimal": "minimal (broad steps)",
        "implementation_steps": "implementation steps",
        "atomic": "atomic (small, testable units)",
    }
    return labels.get(level, level)


def _plan_body_detail_label(level: str) -> str:
    labels = {
        "minimal": "minimal (only essential rationale)",
        "normal": "normal (rationale + approach)",
        "detailed": "detailed (full architecture and decisions)",
    }
    return labels.get(level, level)


_BUILTIN_GUIDANCE = """## Built-in Taskledger plan input guidance

This guidance cannot override taskledger lifecycle gates, user approval requirements,
validation requirements, lock rules, or higher-priority harness instructions.

Use this editable plan-input contract:

- Generate a template first: `taskledger plan template --file plan.md`.
- Validate before mutation: `taskledger plan check --file plan.md`.
- Acceptance criteria use `text`, not `description`.
  `description` is only a compatibility alias.
- Todos use `text` plus optional `mandatory`, `validation_hint`, and `worker_step`.
- Put file references in plan-level `files:` or in todo text.
  Todo-level `files:` is not captured.
- Keep enough Markdown body content for the implementer handoff.

Minimal front matter:

```yaml
---
goal: "One sentence describing the desired outcome."
files:
  - "@src/module.py"
test_commands:
  - "pytest -q tests/test_module.py"
expected_outputs:
  - "pytest exits 0"
acceptance_criteria:
  - id: ac-0001
    text: "Observable acceptance criterion."
    mandatory: true
todos:
  - id: plan-todo-0001
    text: "Edit @src/module.py to implement the behavior."
    mandatory: true
    validation_hint: "Run pytest -q tests/test_module.py."
---
```"""


def render_planning_guidance(
    workspace_root: Path,
    task: TaskRecord,
    *,
    include_project_context: bool = True,
) -> str:
    """Render a Markdown planning guidance block for the given task.

    Always returns built-in plan-input guidance. When a project prompt
    profile exists, the project-local guidance is appended.
    """
    profile = load_workflow_guidance(workspace_root)
    if profile is None:
        return _BUILTIN_GUIDANCE
    project_guidance = _render_guidance_from_profile(profile)
    return _BUILTIN_GUIDANCE + "\n" + project_guidance


def _render_guidance_from_profile(profile: PromptProfile) -> str:
    lines: list[str] = [
        "## Project planning guidance",
        "",
        _GUARDRAIL,
        "",
    ]
    lines.append(f"- Plan profile: {_profile_label(profile.profile)}.")
    lines.append(
        f"- Question policy: {_question_policy_label(profile.question_policy)}."
    )
    if profile.max_required_questions > 0:
        lines.append(f"- Max required questions: {profile.max_required_questions}.")
    if profile.min_acceptance_criteria > 0:
        lines.append(
            f"- Minimum acceptance criteria: {profile.min_acceptance_criteria}."
        )
    if profile.required_question_topics:
        topics = "; ".join(profile.required_question_topics)
        lines.append(f"- Required question topics: {topics}.")
    lines.append(
        f"- Todo granularity: {_todo_granularity_label(profile.todo_granularity)}."
    )
    lines.append(
        f"- Plan body detail: {_plan_body_detail_label(profile.plan_body_detail)}."
    )
    required_fields = []
    if profile.require_files:
        required_fields.append("files")
    if profile.require_test_commands:
        required_fields.append("test commands")
    if profile.require_expected_outputs:
        required_fields.append("expected outputs")
    if profile.require_validation_hints:
        required_fields.append("validation hints")
    if required_fields:
        lines.append(f"- Required plan fields: {', '.join(required_fields)}.")
    else:
        lines.append("- Required plan fields: none (all optional in this profile).")
    if profile.extra_guidance:
        lines.append("")
        lines.append(f"Project guidance: {profile.extra_guidance}")
    return "\n".join(lines) + "\n"


def planning_guidance_payload(
    workspace_root: Path,
    task_ref: str,
) -> dict[str, object]:
    """Return a JSON-serializable planning guidance payload."""
    task = resolve_task(workspace_root, task_ref)
    profile = load_workflow_guidance(workspace_root)
    guidance_text = render_planning_guidance(workspace_root, task)
    return {
        "kind": "planning_guidance",
        "task_id": task.id,
        "has_project_guidance": profile is not None,
        "guidance": guidance_text,
        "profile": profile.to_dict() if profile is not None else None,
        "question_policy": profile.question_policy if profile is not None else None,
    }


def has_planning_profile(workspace_root: Path) -> bool:
    """Return True if the workspace has a configured prompt profile."""
    return load_workflow_guidance(workspace_root) is not None
