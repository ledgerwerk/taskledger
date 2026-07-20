"""Tests for workflow_guidance service."""

from __future__ import annotations

from pathlib import Path

from taskledger.services.workflow_guidance import (
    _BUILTIN_GUIDANCE,
    _plan_body_detail_label,
    _profile_label,
    _question_policy_label,
    _render_guidance_from_profile,
    _todo_granularity_label,
    has_planning_profile,
)
from taskledger.storage.project_config import PromptProfile


def test_profile_label_known() -> None:
    assert _profile_label("strict") == "strict (full ceremony)"
    assert _profile_label("compact") == "compact (minimal ceremony)"


def test_profile_label_unknown_fallback() -> None:
    assert _profile_label("unknown") == "unknown"


def test_question_policy_label_known() -> None:
    assert "ask required questions" in _question_policy_label("ask_when_missing")


def test_todo_granularity_label_known() -> None:
    assert _todo_granularity_label("atomic") == "atomic (small, testable units)"


def test_plan_body_detail_label_known() -> None:
    assert _plan_body_detail_label("detailed") == (
        "detailed (full architecture and decisions)"
    )


# specmason: req=REQ-0077 ac=AC-0825
def test_render_guidance_default_profile() -> None:
    p = PromptProfile()
    result = _render_guidance_from_profile(p)
    assert "## Project planning guidance" in result
    assert "project-local advisory guidance" in result
    assert "cannot override taskledger lifecycle gates" in result
    assert "balanced (moderate ceremony)" in result
    assert (
        "Required plan fields: files, test commands, expected outputs, "
        "validation hints." in result
    )


# specmason: req=REQ-0077 ac=AC-0829
def test_render_guidance_strict_profile() -> None:
    p = PromptProfile(
        profile="strict",
        question_policy="always_before_plan",
        max_required_questions=3,
        min_acceptance_criteria=2,
        todo_granularity="atomic",
        plan_body_detail="detailed",
        required_question_topics=("scope", "approach"),
        extra_guidance="Always include a migration plan.",
    )
    result = _render_guidance_from_profile(p)
    assert "strict (full ceremony)" in result
    assert "always ask required questions" in result
    assert "Max required questions: 3" in result
    assert "Minimum acceptance criteria: 2" in result
    assert "Required question topics: scope; approach" in result
    assert "atomic (small, testable units)" in result
    assert "detailed (full architecture and decisions)" in result
    assert (
        "Required plan fields: files, test commands, expected outputs, "
        "validation hints." in result
    )
    assert "Always include a migration plan" in result


# specmason: req=REQ-0077 ac=AC-0830
def test_render_guidance_when_required_fields_disabled() -> None:
    p = PromptProfile(
        require_files=False,
        require_test_commands=False,
        require_expected_outputs=False,
        require_validation_hints=False,
    )
    result = _render_guidance_from_profile(p)
    assert "Required plan fields: none (all optional in this profile)." in result


# specmason: req=REQ-0077 ac=AC-0827
def test_render_guidance_no_extra_guidance() -> None:
    p = PromptProfile(extra_guidance=None)
    result = _render_guidance_from_profile(p)
    assert "Project guidance:" not in result


# specmason: req=REQ-0077 ac=AC-0828
def test_render_guidance_no_topics() -> None:
    p = PromptProfile(required_question_topics=())
    result = _render_guidance_from_profile(p)
    assert "Required question topics:" not in result


# specmason: req=REQ-0077 ac=AC-0826
def test_render_guidance_guardrail_always_present() -> None:
    for profile_value in ("compact", "balanced", "strict", "exploratory"):
        p = PromptProfile(profile=profile_value)
        result = _render_guidance_from_profile(p)
        assert "cannot override taskledger lifecycle" in result


def test_has_planning_profile_no_config(tmp_path: Path) -> None:
    assert has_planning_profile(tmp_path) is False


def test_builtin_planning_guidance_includes_approval_ready_body_structure() -> None:
    result = _BUILTIN_GUIDANCE
    assert "Approval-ready Markdown body structure" in result
    assert "## Summary" in result
    assert "## Implementation Changes" in result
    assert "## Tests" in result
    assert "## Assumptions" in result
    assert "## Out of Scope" in result
