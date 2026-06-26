"""Tests for taskledger.services.plan_input (preflight plan validation)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from taskledger.services.plan_input import (
    CRITERION_KEYS,
    TODO_KEYS,
    PlanInputError,
    check_plan_input,
    parse_plan_input,
    plan_input_error,
)

pytestmark = [pytest.mark.unit]


RUNHTML_FIXTURE = """\
---
goal: "Implement the review."
acceptance_criteria:
  - id: ac-0001
    description: "Observable behavior is fixed."
    mandatory: true
todos:
  - id: todo-0001
    text: "Edit @pkg/module.py to implement the behavior."
    mandatory: true
    files:
      - "@pkg/module.py"
---

## Goal

Implement the review.
"""


SIMPLE_PLAN = (
    "---\nacceptance_criteria:\n"
    "  - id: ac-0001\n"
    '    text: "x"\n'
    "    mandatory: true\ntodos: []\n---\nbody\n"
)


def _tmp_root() -> Path:
    return Path(tempfile.mkdtemp())


# ---------------------------------------------------------------------------
# Description alias
# ---------------------------------------------------------------------------


class TestDescriptionAlias:
    def test_description_alias_accepted_with_warning(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria:\n  - id: ac-0001\n"
            '    description: "visible behavior"\n    mandatory: true\n'
            "todos: []\n---\nbody\n",
        )
        assert len(p.criteria) == 1
        assert p.criteria[0].text == "visible behavior"
        assert p.criteria[0].id == "ac-0001"
        assert len(p.warnings) == 1
        assert p.warnings[0].code == "criterion_description_alias"
        assert not p.has_errors

    def test_text_wins_when_both_present(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria:\n  - id: ac-0001\n"
            '    text: "canonical text"\n'
            '    description: "ignored alias"\n'
            "    mandatory: true\ntodos: []\n---\nbody\n",
        )
        assert p.criteria[0].text == "canonical text"
        assert len(p.warnings) == 1
        assert p.warnings[0].code == "criterion_description_ignored"
        assert not p.has_errors

    def test_string_criteria_fallback(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\ntodos: []\n---\nbody\n",
            criteria=("cli criterion",),
        )
        assert len(p.criteria) == 1
        assert p.criteria[0].text == "cli criterion"
        assert p.criteria[0].id == "ac-0001"

    def test_single_key_shorthand(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            '---\nacceptance_criteria:\n  - ac-0001: "shorthand text"\n'
            "todos: []\n---\nbody\n",
        )
        assert p.criteria[0].id == "ac-0001"
        assert p.criteria[0].text == "shorthand text"
        assert len(p.issues) == 0


# ---------------------------------------------------------------------------
# Unknown fields
# ---------------------------------------------------------------------------


class TestUnknownFields:
    def test_unknown_criterion_key_warns_in_normal_mode(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria:\n  - id: ac-0001\n"
            '    text: "x"\n    bogus: true\ntodos: []\n---\nbody\n',
            strict=False,
        )
        assert not p.has_errors
        assert any(i.code == "unknown_criterion_key" for i in p.warnings)

    def test_unknown_criterion_key_errors_in_strict_mode(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria:\n  - id: ac-0001\n"
            '    text: "x"\n    bogus: true\ntodos: []\n---\nbody\n',
            strict=True,
        )
        assert p.has_errors
        assert any(i.code == "unknown_criterion_key" for i in p.errors)

    def test_unknown_todo_key_warns_in_normal_mode(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria: []\ntodos:\n  - id: t1\n"
            '    text: "y"\n    color: red\n---\nbody\n',
            strict=False,
        )
        assert not p.has_errors
        assert any(i.code == "unknown_todo_key" for i in p.warnings)

    def test_unknown_todo_key_errors_in_strict_mode(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria: []\ntodos:\n  - id: t1\n"
            '    text: "y"\n    color: red\n---\nbody\n',
            strict=True,
        )
        assert p.has_errors
        assert any(i.code == "unknown_todo_key" for i in p.errors)


# ---------------------------------------------------------------------------
# todos[].files
# ---------------------------------------------------------------------------


class TestTodoFiles:
    def test_todo_files_warns_in_normal_mode(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria: []\ntodos:\n  - id: t1\n"
            '    text: "y"\n    files:\n      - "@src/foo.py"\n---\nbody\n',
            strict=False,
        )
        assert not p.has_errors
        assert len(p.warnings) == 1
        assert p.warnings[0].code == "unsupported_todo_files"
        assert "todos[0].files" in p.warnings[0].location

    def test_todo_files_errors_in_strict_mode(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria: []\ntodos:\n  - id: t1\n"
            '    text: "y"\n    files:\n      - "@src/foo.py"\n---\nbody\n',
            strict=True,
        )
        assert p.has_errors
        assert p.errors[0].code == "unsupported_todo_files"


# ---------------------------------------------------------------------------
# Missing content errors
# ---------------------------------------------------------------------------


class TestMissingContent:
    def test_criterion_missing_text_is_error(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria:\n  - id: ac-0001\n"
            "    mandatory: true\ntodos: []\n---\nbody\n",
        )
        assert p.has_errors
        assert any(i.code == "criterion_missing_text" for i in p.errors)

    def test_todo_missing_text_is_error(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria: []\ntodos:\n  - id: t1\n"
            "    mandatory: true\n---\nbody\n",
        )
        assert p.has_errors
        assert any(i.code == "todo_missing_text" for i in p.errors)

    def test_non_list_criteria_raises_plan_input_error(self) -> None:
        root = _tmp_root()
        with pytest.raises(PlanInputError, match="must be a list"):
            parse_plan_input(
                root, '---\nacceptance_criteria: "not a list"\ntodos: []\n---\nbody\n'
            )

    def test_non_list_todos_raises_plan_input_error(self) -> None:
        root = _tmp_root()
        with pytest.raises(PlanInputError, match="must be a list"):
            parse_plan_input(
                root,
                '---\nacceptance_criteria: []\ntodos: "not a list"\n---\nbody\n',
            )

    def test_malformed_yaml_raises_plan_input_error(self) -> None:
        root = _tmp_root()
        with pytest.raises(PlanInputError, match="not valid YAML"):
            parse_plan_input(root, "---\n  bad: : :\nkey\n---\nbody\n")

    def test_unterminated_front_matter_raises(self) -> None:
        root = _tmp_root()
        with pytest.raises(PlanInputError, match="Unterminated"):
            parse_plan_input(root, "---\ngoal: test\n")


# ---------------------------------------------------------------------------
# run.html regression fixture
# ---------------------------------------------------------------------------


class TestRunHtmlRegression:
    def test_check_passes_with_description_and_todo_files(self) -> None:
        root = _tmp_root()
        result = check_plan_input(root, body=RUNHTML_FIXTURE, strict=False)
        assert result["passed"] is True
        assert result["kind"] == "plan_input_check"
        summary = result["summary"]
        assert summary["errors"] == 0
        assert summary["warnings"] == 2
        codes = {i["code"] for i in result["issues"]}
        assert "criterion_description_alias" in codes
        assert "unsupported_todo_files" in codes
        assert result["parsed"]["criteria"] == 1
        assert result["parsed"]["todos"] == 1

    def test_check_strict_fails_with_todo_files(self) -> None:
        root = _tmp_root()
        result = check_plan_input(root, body=RUNHTML_FIXTURE, strict=True)
        assert result["passed"] is False
        assert result["summary"]["errors"] == 1

    def test_description_only_plan_upsert_succeeds(self) -> None:
        """Plan with only description alias (no todos[].files) parses clean."""
        root = _tmp_root()
        p = parse_plan_input(
            root,
            '---\ngoal: "test"\nacceptance_criteria:\n  - id: ac-0001\n'
            '    description: "observable behavior"\n    mandatory: true\n'
            'todos:\n  - id: t1\n    text: "edit src"\n'
            "    mandatory: true\n---\nbody\n",
            strict=True,
        )
        assert not p.has_errors
        assert p.criteria[0].text == "observable behavior"
        assert p.goal == "test"


# ---------------------------------------------------------------------------
# plan_input_error
# ---------------------------------------------------------------------------


class TestPlanInputError:
    def test_error_has_remediation_and_data(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria:\n  - id: ac-0001\n"
            '    text: "x"\n    bogus: true\ntodos: []\n---\nbody\n',
            strict=True,
        )
        assert p.has_errors
        err = plan_input_error(p)
        assert err.taskledger_remediation
        assert any("plan check" in r for r in err.taskledger_remediation)
        assert any("plan schema" in r for r in err.taskledger_remediation)
        assert "issues" in err.taskledger_data
        assert "supported_schema" in err.taskledger_data
        assert "acceptance_criteria" in err.taskledger_data["supported_schema"]
        assert "todos" in err.taskledger_data["supported_schema"]

    def test_error_message_has_indexed_location(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria: []\ntodos:\n  - id: t1\n"
            '    text: "y"\n    files: ["@src/foo.py"]\n---\nbody\n',
            strict=True,
        )
        err = plan_input_error(p, command="plan upsert")
        assert "todos[0].files" in err.message
        assert "1 error(s)" in err.message


# ---------------------------------------------------------------------------
# check_plan_input
# ---------------------------------------------------------------------------


class TestCheckPlanInput:
    def test_task_id_optional(self) -> None:
        root = _tmp_root()
        result = check_plan_input(root, body=SIMPLE_PLAN)
        assert result["task_id"] is None

    def test_task_id_included_when_provided(self) -> None:
        root = _tmp_root()
        result = check_plan_input(
            root,
            body=SIMPLE_PLAN,
            task_id="task-9999",
        )
        assert result["task_id"] == "task-9999"

    def test_json_envelope_shape(self) -> None:
        root = _tmp_root()
        result = check_plan_input(root, body=SIMPLE_PLAN)
        assert result["kind"] == "plan_input_check"
        assert "passed" in result
        assert "strict" in result
        assert "summary" in result
        assert "issues" in result
        assert "parsed" in result


# ---------------------------------------------------------------------------
# Keysets
# ---------------------------------------------------------------------------


class TestKeysets:
    def test_criterion_keys_include_description(self) -> None:
        assert "description" in CRITERION_KEYS
        assert "text" in CRITERION_KEYS
        assert "id" in CRITERION_KEYS
        assert "mandatory" in CRITERION_KEYS

    def test_todo_keys_include_supported(self) -> None:
        assert "id" in TODO_KEYS
        assert "text" in TODO_KEYS
        assert "mandatory" in TODO_KEYS
        assert "validation_hint" in TODO_KEYS
        assert "worker_step" in TODO_KEYS
        assert "id_hint" in TODO_KEYS


# ---------------------------------------------------------------------------
# Worker pipeline
# ---------------------------------------------------------------------------


class TestWorkerPipeline:
    def test_worker_step_without_pipeline_is_error(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            "---\nacceptance_criteria: []\ntodos:\n  - id: t1\n"
            '    text: "y"\n    worker_step: spec-reviewer\n---\nbody\n',
        )
        assert p.has_errors
        assert any(i.code == "todo_worker_step_requires_pipeline" for i in p.errors)
        # worker_step_id is still set (for informational purposes)
        assert p.todos[0].worker_step_id == "spec-reviewer"


# ---------------------------------------------------------------------------
# Criterion id uniqueness
# ---------------------------------------------------------------------------


class TestCriterionIdUniqueness:
    def test_duplicate_criterion_id_is_error(self) -> None:
        root = _tmp_root()
        p = parse_plan_input(
            root,
            '---\nacceptance_criteria:\n  - id: ac-0001\n    text: "a"\n'
            '  - id: ac-0001\n    text: "b"\ntodos: []\n---\nbody\n',
        )
        assert p.has_errors
        assert any(i.code == "duplicate_criterion_id" for i in p.errors)
