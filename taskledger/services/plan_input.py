"""Preflight parser and validator for editable plan input files.

This module centralizes the parsing logic that ``plan upsert`` and the other
planning flows consume, and adds a pure preflight validator for
``taskledger plan check``. It does not depend on private ``tasks._cli_error``:
parse failures that cannot continue raise :class:`PlanInputError`, while
individual field problems are collected as :class:`PlanInputIssue` records so
callers can report them with indexed locations.

The stored :class:`~taskledger.domain.models.PlanRecord` format is unchanged.
``description`` is accepted as a compatibility alias for criterion ``text`` but
normalized away; unknown nested fields warn by default and become errors in
strict mode so silent structured-data loss is prevented.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from taskledger.domain.models import AcceptanceCriterion, TaskTodo
from taskledger.errors import LaunchError
from taskledger.storage.project_config import load_worker_pipeline_config
from taskledger.storage.worker_pipeline_config import WorkerPipelineConfig

__all__ = [
    "CRITERION_KEYS",
    "TODO_KEYS",
    "PlanInputError",
    "PlanInputIssue",
    "ParsedPlanInput",
    "check_plan_input",
    "parse_plan_input",
    "PLAN_INPUT_REMEDIATION",
    "plan_input_error",
    "plan_input_schema_text",
]

CRITERION_KEYS = frozenset({"id", "text", "description", "mandatory"})
TODO_KEYS = frozenset(
    {"id", "id_hint", "text", "mandatory", "validation_hint", "worker_step"}
)

Severity = Literal["error", "warning"]

# Codes that describe a known alias rather than a fully unknown key.
_CRITERION_DESCRIPTION_ALIAS = "criterion_description_alias"
_CRITERION_DESCRIPTION_IGNORED = "criterion_description_ignored"
_TODO_FILES = "files"


@dataclass(frozen=True, slots=True)
class PlanInputIssue:
    """A single indexed warning or error found in editable plan input."""

    severity: Severity
    code: str
    location: str
    message: str
    hint: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "severity": self.severity,
            "code": self.code,
            "location": self.location,
            "message": self.message,
        }
        if self.hint is not None:
            result["hint"] = self.hint
        return result


@dataclass(frozen=True, slots=True)
class ParsedPlanInput:
    """Normalized editable plan input plus collected diagnostics."""

    front_matter: dict[str, object]
    body: str
    criteria: tuple[AcceptanceCriterion, ...]
    todos: tuple[TaskTodo, ...]
    goal: str | None
    files: tuple[str, ...]
    test_commands: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    generation_reason: str | None
    todos_waived_reason: str | None
    issues: tuple[PlanInputIssue, ...]

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)

    @property
    def errors(self) -> tuple[PlanInputIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[PlanInputIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    def summary(self) -> dict[str, int]:
        errors = sum(1 for issue in self.issues if issue.severity == "error")
        warnings = sum(1 for issue in self.issues if issue.severity == "warning")
        return {"errors": errors, "warnings": warnings}

    def parsed_counts(self) -> dict[str, int]:
        return {
            "criteria": len(self.criteria),
            "todos": len(self.todos),
            "files": len(self.files),
            "test_commands": len(self.test_commands),
            "expected_outputs": len(self.expected_outputs),
            "body_lines": len(self.body.splitlines()),
        }


class PlanInputError(LaunchError):
    """Raised when editable plan input cannot be parsed at all.

    This is reserved for structural failures (malformed YAML, front matter that
    is not a mapping, non-list ``acceptance_criteria``/``todos``). Individual
    field problems are collected as :class:`PlanInputIssue` records instead.
    """

    code = "PLAN_INPUT_ERROR"
    error_type = "PlanInputError"


def parse_plan_input(
    workspace_root: Path,
    body: str,
    *,
    criteria: tuple[str, ...] = (),
    strict: bool = False,
) -> ParsedPlanInput:
    """Parse editable plan input text into normalized commitments.

    ``strict`` upgrades unknown-field findings from warnings to errors. Field
    alias diagnostics (``description`` as alias for ``text``) are always
    warnings because the value can be normalized safely.
    """
    front_matter, plan_body = _split_front_matter(body)
    issues: list[PlanInputIssue] = []
    parsed_criteria = _criteria_from_input(front_matter, criteria, strict, issues)
    pipeline = load_worker_pipeline_config(workspace_root)
    parsed_todos = _todos_from_input(front_matter, pipeline, strict, issues)
    return ParsedPlanInput(
        front_matter=front_matter,
        body=plan_body,
        criteria=parsed_criteria,
        todos=parsed_todos,
        goal=_optional_string(front_matter, "goal"),
        files=_string_tuple(front_matter, "files", issues),
        test_commands=_string_tuple(front_matter, "test_commands", issues),
        expected_outputs=_string_tuple(front_matter, "expected_outputs", issues),
        generation_reason=_optional_string(front_matter, "generation_reason"),
        todos_waived_reason=(
            _optional_string(front_matter, "todos_waived_reason")
            or _optional_string(front_matter, "todo_waiver_reason")
            or _optional_string(front_matter, "no_todos_reason")
        ),
        issues=tuple(issues),
    )


def check_plan_input(
    workspace_root: Path,
    *,
    body: str,
    task_id: str | None = None,
    criteria: tuple[str, ...] = (),
    strict: bool = False,
) -> dict[str, object]:
    """Pure preflight check of editable plan input.

    This parses the input without creating, revising, proposing, accepting,
    locking, or releasing anything. Worker-pipeline validation reads the
    project config. ``task_id`` is included when known so callers can carry it
    without forcing a task lookup.
    """
    parsed = parse_plan_input(workspace_root, body, criteria=criteria, strict=strict)
    error_count = len(parsed.errors)
    warning_count = len(parsed.warnings)
    passed = error_count == 0 and (not strict or warning_count == 0)
    payload: dict[str, object] = {
        "kind": "plan_input_check",
        "task_id": task_id,
        "passed": passed,
        "strict": strict,
        "summary": {"errors": error_count, "warnings": warning_count},
        "issues": [issue.to_dict() for issue in parsed.issues],
        "parsed": parsed.parsed_counts(),
    }
    return payload


def plan_input_schema_text() -> str:
    """Printable editable plan input schema for ``task ledger schema``."""
    return (
        "Editable plan input schema\n"
        "\n"
        "Front matter keys:\n"
        "  goal: string\n"
        "  files: list[string]\n"
        "  test_commands: list[string]\n"
        "  expected_outputs: list[string]\n"
        "  acceptance_criteria: list[{id?: string, text: string, mandatory?: bool}]\n"
        "  todos: list[{id?: string, id_hint?: string, text: string, "
        "mandatory?: bool, validation_hint?: string, worker_step?: string}]\n"
        "  generation_reason: string\n"
        "  todos_waived_reason | todo_waiver_reason | no_todos_reason: string\n"
        "\n"
        "Criterion aliases:\n"
        "  description is accepted as a compatibility alias for text, but text "
        "is canonical.\n"
        "\n"
        "Valid example:\n"
        "\n"
        "```\n"
        "---\n"
        'goal: "One sentence describing the desired outcome."\n'
        "files:\n"
        '  - "@src/module.py"\n'
        "test_commands:\n"
        '  - "pytest -q tests/test_module.py"\n'
        "acceptance_criteria:\n"
        "  - id: ac-0001\n"
        '    text: "Observable acceptance criterion."\n'
        "    mandatory: true\n"
        "todos:\n"
        "  - id: plan-todo-0001\n"
        '    text: "Edit @src/module.py to implement the behavior."\n'
        "    mandatory: true\n"
        '    validation_hint: "Run pytest -q tests/test_module.py."\n'
        "---\n"
        "```\n"
    )


PLAN_INPUT_REMEDIATION = (
    "taskledger plan template --from-answers --file ./plan.md",
    "taskledger plan check --file ./plan.md",
    "taskledger plan schema",
    "taskledger plan upsert --from-answers --file ./plan.md",
)


def plan_input_error(
    parsed: ParsedPlanInput,
    *,
    command: str = "plan upsert",
) -> LaunchError:
    """Convert parser errors into a LaunchError with structured diagnostics.

    The alias (``description``) and unknown-field findings that the parser
    collects are surfaced through ``taskledger_data`` and a deterministic
    remediation path so an agent can recover without inspecting source.
    The aggregate message includes the first error message so callers can
    surface a concrete reason in the human/JSON output without inspecting
    ``taskledger_data``.
    """
    locations = ", ".join(issue.location for issue in parsed.errors) or "plan input"
    first_message = parsed.errors[0].message if parsed.errors else ""
    message = (
        f"{command} rejected editable plan input: "
        f"{len(parsed.errors)} error(s) at {locations}."
    )
    if first_message:
        message = f"{message} {first_message}"
    error = LaunchError(message)
    error.taskledger_data = {
        "issues": [issue.to_dict() for issue in parsed.issues],
        "supported_schema": {
            "acceptance_criteria": sorted(CRITERION_KEYS),
            "todos": sorted(TODO_KEYS),
        },
    }
    error.taskledger_remediation = list(PLAN_INPUT_REMEDIATION)
    return error


def _split_front_matter(body: str) -> tuple[dict[str, object], str]:
    lines = body.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, body
    for index in range(1, len(lines)):
        if lines[index].strip() != "---":
            continue
        try:
            front_matter = yaml.safe_load("\n".join(lines[1:index])) or {}
        except yaml.YAMLError as exc:
            raise PlanInputError(f"Plan front matter is not valid YAML: {exc}") from exc
        if not isinstance(front_matter, dict):
            raise PlanInputError("Plan front matter must be a YAML mapping.")
        return front_matter, "\n".join(lines[index + 1 :])
    raise PlanInputError("Unterminated plan front matter.")


def _criteria_from_input(
    front_matter: dict[str, object],
    criteria: tuple[str, ...],
    strict: bool,
    issues: list[PlanInputIssue],
) -> tuple[AcceptanceCriterion, ...]:
    raw = front_matter.get("acceptance_criteria", front_matter.get("criteria"))
    items: list[AcceptanceCriterion] = []
    if raw is not None:
        if not isinstance(raw, list):
            raise PlanInputError(
                "Plan acceptance_criteria front matter must be a list."
            )
        for index, item in enumerate(raw, start=1):
            if isinstance(item, str):
                string_text = item.strip()
                if not string_text:
                    continue
                items.append(
                    AcceptanceCriterion(
                        id=_criterion_id_from_index(index),
                        text=string_text,
                    )
                )
                continue
            if not isinstance(item, dict):
                raise PlanInputError(
                    f"Plan acceptance_criteria[{index - 1}] must be "
                    "a string or mapping."
                )
            text, id_override = _resolve_criterion_mapping(item, index, strict, issues)
            if text is None:
                continue
            criterion_id = id_override or _criterion_id(item, index, strict, issues)
            items.append(
                AcceptanceCriterion(
                    id=criterion_id,
                    text=text,
                    mandatory=_mandatory(item, "criterion", index),
                )
            )
    else:
        for index, item in enumerate(criteria, start=1):
            text = item.strip()
            if text:
                items.append(
                    AcceptanceCriterion(
                        id=_criterion_id_from_index(index),
                        text=text,
                    )
                )
    _enforce_unique_criterion_ids(items, strict, issues)
    return tuple(items)


def _resolve_criterion_mapping(
    item: dict[str, object],
    index: int,
    strict: bool,
    issues: list[PlanInputIssue],
) -> tuple[str | None, str | None]:
    """Resolve a criterion mapping to ``(text, id_override)``.

    ``id_override`` is set only for the single-key shorthand form
    ``{ac-0001: \"some text\"}`` where the key is the criterion id.
    """
    text = _clean(item.get("text"))
    description = _clean(item.get("description"))
    is_shorthand = not text and not description and len(item) == 1
    if is_shorthand:
        key, value = next(iter(item.items()))
        shorthand = _clean(value)
        if not shorthand:
            issues.append(
                _field_error(
                    "criterion_missing_text",
                    f"acceptance_criteria[{index - 1}]",
                    "Plan criterion shorthand must include non-empty text.",
                    'Provide `text: "..."` for this criterion.',
                )
            )
            return None, None
        return shorthand, str(key).strip()
    # Normal mapping form: report unknown keys, then resolve text/alias.
    _report_unknown_criterion_keys(item, index, strict, issues)
    if text:
        if description:
            issues.append(
                PlanInputIssue(
                    "warning",
                    _CRITERION_DESCRIPTION_IGNORED,
                    f"acceptance_criteria[{index - 1}].description",
                    "`description` is ignored because `text` is present.",
                    "Remove `description`; `text` is canonical for criteria.",
                )
            )
        return text, None
    if description:
        issues.append(
            PlanInputIssue(
                "warning",
                _CRITERION_DESCRIPTION_ALIAS,
                f"acceptance_criteria[{index - 1}].description",
                "`description` was accepted as an alias for `text`; "
                "use `text` in plan input files.",
                "Rename `description` to `text` in editable plan input.",
            )
        )
        return description, None
    issues.append(
        _field_error(
            "criterion_missing_text",
            f"acceptance_criteria[{index - 1}].text",
            "Plan criterion mappings must include non-empty `text`.",
            'Add `text: "..."` (or the `description` compatibility alias).',
        )
    )
    return None, None


def _report_unknown_criterion_keys(
    item: dict[str, object],
    index: int,
    strict: bool,
    issues: list[PlanInputIssue],
) -> None:
    for key in item.keys():
        if key in CRITERION_KEYS:
            continue
        issues.append(
            _unknown_field_issue(
                strict,
                "unknown_criterion_key",
                f"acceptance_criteria[{index - 1}].{key}",
                key,
                "criterion",
                sorted(CRITERION_KEYS - {"description"}),
            )
        )


def _criterion_id(
    item: dict[str, object],
    index: int,
    strict: bool,
    issues: list[PlanInputIssue],
) -> str:
    raw_id = item.get("id")
    if raw_id is None:
        return _criterion_id_from_index(index)
    if not isinstance(raw_id, str) or not raw_id.strip():
        issues.append(
            _field_error(
                "criterion_id_invalid",
                f"acceptance_criteria[{index - 1}].id",
                "Plan criterion `id` must be a non-empty string.",
                "Use an id like `ac-0001`.",
            )
        )
        return _criterion_id_from_index(index)
    return raw_id.strip()


def _enforce_unique_criterion_ids(
    items: list[AcceptanceCriterion],
    strict: bool,
    issues: list[PlanInputIssue],
) -> None:
    seen: dict[str, int] = {}
    for position, item in enumerate(items):
        first = seen.get(item.id)
        if first is None:
            seen[item.id] = position
            continue
        issues.append(
            _field_error(
                "duplicate_criterion_id",
                f"acceptance_criteria[{position}].id",
                f"Plan criterion id `{item.id}` is not unique "
                f"(first used at acceptance_criteria[{first}]).",
                "Give each criterion a unique id like `ac-0001`.",
            )
        )


def _todos_from_input(
    front_matter: dict[str, object],
    pipeline: WorkerPipelineConfig | None,
    strict: bool,
    issues: list[PlanInputIssue],
) -> tuple[TaskTodo, ...]:
    raw_todos = front_matter.get("todos")
    if raw_todos is None:
        return ()
    if not isinstance(raw_todos, list):
        raise PlanInputError("Plan todos front matter must be a list.")
    items: list[TaskTodo] = []
    for index, item in enumerate(raw_todos, start=1):
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            items.append(
                TaskTodo(
                    id=f"plan-todo-{index:04d}",
                    text=text,
                    mandatory=True,
                    source="plan",
                )
            )
            continue
        if not isinstance(item, dict):
            raise PlanInputError(
                f"Plan todos[{index - 1}] must be a string or mapping."
            )
        _report_unknown_todo_keys(item, index, strict, issues)
        text = _clean(item.get("text"))
        if not text:
            issues.append(
                _field_error(
                    "todo_missing_text",
                    f"todos[{index - 1}].text",
                    "Plan todo mappings must include non-empty `text`.",
                    'Add `text: "..."` to this todo.',
                )
            )
            continue
        worker_step_id = _todo_worker_step_id(item, index, pipeline, strict, issues)
        items.append(
            TaskTodo(
                id=str(
                    item.get("id") or item.get("id_hint") or f"plan-todo-{index:04d}"
                ),
                text=text,
                mandatory=_mandatory(item, "todo", index),
                source="plan",
                validation_hint=_optional_value(item.get("validation_hint")),
                worker_step_id=worker_step_id,
            )
        )
    return tuple(items)


def _report_unknown_todo_keys(
    item: dict[str, object],
    index: int,
    strict: bool,
    issues: list[PlanInputIssue],
) -> None:
    for key in item.keys():
        if key in TODO_KEYS:
            continue
        if key == _TODO_FILES:
            issues.append(
                PlanInputIssue(
                    "error" if strict else "warning",
                    "unsupported_todo_files",
                    f"todos[{index - 1}].files",
                    "Todo-level `files` are not captured by Taskledger. "
                    "Move files to plan-level `files:` or mention them in the "
                    "todo text/body.",
                    "Use plan-level `files:` or inline the "
                    "file reference in todo text.",
                )
            )
            continue
        issues.append(
            _unknown_field_issue(
                strict,
                "unknown_todo_key",
                f"todos[{index - 1}].{key}",
                key,
                "todo",
                sorted(TODO_KEYS),
            )
        )


def _todo_worker_step_id(
    item: dict[str, object],
    index: int,
    pipeline: WorkerPipelineConfig | None,
    strict: bool,
    issues: list[PlanInputIssue],
) -> str | None:
    raw_worker_step = item.get("worker_step")
    if raw_worker_step is None:
        return None
    if not isinstance(raw_worker_step, str) or not raw_worker_step.strip():
        issues.append(
            _field_error(
                "todo_worker_step_invalid",
                f"todos[{index - 1}].worker_step",
                "Plan todo `worker_step` must be a non-empty string.",
                "Remove `worker_step` or set it to a configured worker step id.",
            )
        )
        return None
    worker_step_id = raw_worker_step.strip()
    if pipeline is None or not pipeline.enabled:
        issues.append(
            _field_error(
                "todo_worker_step_requires_pipeline",
                f"todos[{index - 1}].worker_step",
                "Plan todo `worker_step` requires an enabled worker pipeline.",
                "Remove `worker_step` or enable a worker pipeline in taskledger.toml.",
            )
        )
        return worker_step_id
    try:
        pipeline.resolve_step(worker_step_id)
    except LaunchError as exc:
        issues.append(
            _field_error(
                "todo_worker_step_unknown",
                f"todos[{index - 1}].worker_step",
                str(exc),
                "Use one of the configured worker step ids.",
            )
        )
    return worker_step_id


def _string_tuple(
    front_matter: dict[str, object],
    key: str,
    issues: list[PlanInputIssue],
) -> tuple[str, ...]:
    raw = front_matter.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise PlanInputError(f"Plan front matter '{key}' must be a list.")
    items: list[str] = []
    for position, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            raise PlanInputError(
                f"Plan front matter '{key}[{position}]' must be a non-empty string."
            )
        items.append(item.strip())
    return tuple(items)


def _unknown_field_issue(
    strict: bool,
    code: str,
    location: str,
    key: str,
    kind: str,
    supported: list[str],
) -> PlanInputIssue:
    return PlanInputIssue(
        "error" if strict else "warning",
        code,
        location,
        f"Unknown {kind} key `{key}` is not captured by Taskledger.",
        f"Supported {kind} keys: {', '.join(supported)}.",
    )


def _field_error(
    code: str,
    location: str,
    message: str,
    hint: str,
) -> PlanInputIssue:
    # Genuine content problems (missing text, bad ids, duplicate ids, unknown
    # worker steps) are errors regardless of strictness: the value cannot be
    # normalized safely and would silently drop a commitment otherwise.
    return PlanInputIssue("error", code, location, message, hint)


def _criterion_id_from_index(index: int) -> str:
    return f"ac-{index:04d}"


def _mandatory(item: dict[str, object], kind: str, index: int) -> bool:
    return bool(item.get("mandatory", True))


def _clean(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _optional_string(front_matter: dict[str, object], key: str) -> str | None:
    return _optional_value(front_matter.get(key))


def _optional_value(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
