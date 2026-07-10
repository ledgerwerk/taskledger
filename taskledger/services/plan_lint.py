from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

from taskledger.domain.models import PlanRecord, TaskTodo
from taskledger.errors import LaunchError
from taskledger.storage.task_store import list_plans, resolve_plan, resolve_task

Severity = Literal["error", "warning"]

_GENERIC_TODO_PHRASES = frozenset(
    {
        "fix tests",
        "clean up",
        "update docs",
        "make it work",
        "handle edge cases",
        "add tests",
        "refactor",
    }
)

_PLACEHOLDER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bTBD\b", re.IGNORECASE),
    re.compile(r"\bTODO\b"),
    re.compile(r"\blater\b", re.IGNORECASE),
    re.compile(r"\bappropriate\b", re.IGNORECASE),
    re.compile(r"\bsimilar to above\b", re.IGNORECASE),
    re.compile(r"\betc\.?\b"),
    re.compile(r"\bfix tests\b", re.IGNORECASE),
    re.compile(r"\bclean up\b", re.IGNORECASE),
]

_REQUIRED_APPROVAL_HEADINGS = (
    "Summary",
    "Implementation Changes",
    "Tests",
    "Assumptions",
)


@dataclass(frozen=True, slots=True)
class PlanLintIssue:
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


class PlanLintPayload(TypedDict):
    kind: str
    task_id: str
    plan_id: str
    plan_version: int
    strict: bool
    passed: bool
    summary: dict[str, int]
    issues: list[dict[str, object]]


def lint_plan(
    workspace_root: Path,
    task_ref: str,
    *,
    version: int | None = None,
    strict: bool = False,
) -> PlanLintPayload:
    task = resolve_task(workspace_root, task_ref)
    if version is not None:
        plan = resolve_plan(workspace_root, task.id, version=version)
    else:
        plans = list_plans(workspace_root, task.id)
        if not plans:
            raise LaunchError(
                f"No plans found for task {task.id}.",
            )
        plan = plans[-1]

    issues = _run_lint_rules(plan, strict)

    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")
    passed = error_count == 0

    return PlanLintPayload(
        kind="plan_lint",
        task_id=task.id,
        plan_id=plan.plan_id,
        plan_version=plan.plan_version,
        strict=strict,
        passed=passed,
        summary={"errors": error_count, "warnings": warning_count},
        issues=[issue.to_dict() for issue in issues],
    )


def _run_lint_rules(plan: PlanRecord, strict: bool) -> list[PlanLintIssue]:
    issues: list[PlanLintIssue] = []

    # 1. missing_goal
    goal = _goal_text(plan)
    if not goal:
        issues.append(
            PlanLintIssue(
                severity="error",
                code="missing_goal",
                location="plan.goal",
                message="Plan must define a concrete goal.",
                hint="Add `goal: ...` to plan front matter or a `## Goal` section.",
            )
        )

    # 2. missing_acceptance_criteria
    if not plan.criteria:
        issues.append(
            PlanLintIssue(
                severity="error",
                code="missing_acceptance_criteria",
                location="plan.criteria",
                message="Plan must have at least one acceptance criterion.",
                hint="Add `acceptance_criteria:` to plan front matter.",
            )
        )

    # 3. missing_todos
    waiver = (plan.todos_waived_reason or "").strip()
    if not plan.todos and not waiver:
        issues.append(
            PlanLintIssue(
                severity="error",
                code="missing_todos",
                location="plan.todos",
                message="Plan must have at least one todo or a todos_waived_reason.",
                hint="Add `todos:` to plan front matter or set `todos_waived_reason`.",
            )
        )
    # 3b. missing_plan_body
    body_waiver = (getattr(plan, "body_waived_reason", None) or "").strip()
    if not plan.body.strip() and not body_waiver:
        issues.append(
            PlanLintIssue(
                severity="error",
                code="missing_plan_body",
                location="plan.body",
                message="Plan must have a non-empty body after front matter.",
                hint="Add implementation notes after the closing `---` separator.",
            )
        )

    # 3c. missing_approval_heading
    missing_approval_headings = [
        heading
        for heading in _REQUIRED_APPROVAL_HEADINGS
        if _body_section(plan.body, heading) is None
    ]
    if missing_approval_headings:
        severity: Severity = "error" if strict else "warning"
        issues.append(
            PlanLintIssue(
                severity=severity,
                code="missing_approval_heading",
                location="plan.body",
                message=(
                    "Plan body should include approval-ready headings: "
                    + ", ".join(_REQUIRED_APPROVAL_HEADINGS)
                    + "."
                ),
                hint=(
                    "Use `taskledger plan template --file ./plan.md` and keep the "
                    "approval-ready body structure."
                ),
            )
        )
    # 4. todo_not_concrete
    for index, todo in enumerate(plan.todos):
        if not _todo_is_concrete(todo):
            issues.append(
                PlanLintIssue(
                    severity="error",
                    code="todo_not_concrete",
                    location=f"plan.todos[{index}]",
                    message=f'Todo is too vague: "{todo.text}".',
                    hint="Name a file, function, command, or specific action.",
                )
            )

    # 5. placeholder checks
    issues.extend(_placeholder_issues("plan.goal", goal, strict))
    issues.extend(_placeholder_issues("plan.body", plan.body, strict))
    for index, criterion in enumerate(plan.criteria):
        issues.extend(
            _placeholder_issues(f"plan.criteria[{index}]", criterion.text, strict)
        )
    for index, todo in enumerate(plan.todos):
        issues.extend(_placeholder_issues(f"plan.todos[{index}]", todo.text, strict))
        if todo.validation_hint:
            issues.extend(
                _placeholder_issues(
                    f"plan.todos[{index}].validation_hint", todo.validation_hint, strict
                )
            )

    # Extended rules (warnings, errors in strict mode)
    # 6. missing_files
    if not _has_file_reference(plan):
        sev: Severity = "error" if strict else "warning"
        issues.append(
            PlanLintIssue(
                severity=sev,
                code="missing_files",
                location="plan.files",
                message="Plan should name files expected to change or inspect.",
                hint="Add `files:` to plan front matter.",
            )
        )

    # 7. missing_test_commands
    if not _has_test_command(plan):
        sev = "error" if strict else "warning"
        issues.append(
            PlanLintIssue(
                severity=sev,
                code="missing_test_commands",
                location="plan.test_commands",
                message="Plan should include commands for verification.",
                hint="Add `test_commands:` to plan front matter.",
            )
        )

    # 8. missing_expected_outputs
    if not _has_expected_output(plan):
        sev = "error" if strict else "warning"
        issues.append(
            PlanLintIssue(
                severity=sev,
                code="missing_expected_outputs",
                location="plan.expected_outputs",
                message="Plan should describe expected outputs for verification.",
                hint="Add `expected_outputs:` to plan front matter.",
            )
        )

    # 9. missing_todo_validation_hint
    if (
        plan.todos
        and not _has_test_command(plan)
        and not _todos_have_validation_hints(plan)
    ):
        sev = "error" if strict else "warning"
        issues.append(
            PlanLintIssue(
                severity=sev,
                code="missing_todo_validation_hint",
                location="plan.todos",
                message=(
                    "Plan todos should include validation_hint or the plan should "
                    "define test_commands."
                ),
                hint=(
                    "Add validation_hint to each todo or add plan-level test_commands."
                ),
            )
        )

    return issues


def _goal_text(plan: PlanRecord) -> str | None:
    if plan.goal and plan.goal.strip():
        return plan.goal.strip()
    heading = _body_section(plan.body, "Goal")
    if heading and heading.strip():
        return heading.strip()
    for line in plan.body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("goal:"):
            rest = stripped[len("goal:") :].strip()
            if rest:
                return rest
    return None


def _body_section(body: str, heading: str) -> str | None:
    pattern = re.compile(r"^(#{1,3})\s+" + re.escape(heading) + r"\s*$", re.IGNORECASE)
    lines = body.splitlines()
    start: int | None = None
    depth = 0
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if m:
            start = i + 1
            depth = len(m.group(1))
            continue
        if start is not None:
            m2 = re.match(r"^(#{1," + str(depth) + r"})\s+\S", line)
            if m2:
                section_lines = lines[start:i]
                return "\n".join(section_lines).strip() or None
    if start is not None:
        section_lines = lines[start:]
        return "\n".join(section_lines).strip() or None
    return None


def _has_placeholder(text: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    for pat in _PLACEHOLDER_PATTERNS:
        m = pat.search(text)
        if m:
            found.append(m.group(0))
    return found


def _placeholder_issues(
    label: str, text: str | None, strict: bool
) -> list[PlanLintIssue]:
    if not text:
        return []
    phrases = _has_placeholder(text)
    if not phrases:
        return []
    sev: Severity = "error" if strict else "warning"
    return [
        PlanLintIssue(
            severity=sev,
            code="placeholder",
            location=label,
            message=f'Placeholder phrase found: "{phrases[0]}".',
            hint="Replace placeholder with specific content.",
        )
    ]


def _todo_is_concrete(todo: TaskTodo) -> bool:
    text = todo.text.strip()
    if not text:
        return False

    # Generic phrase match
    if text.lower().strip() in _GENERIC_TODO_PHRASES:
        return False

    # Contains a file path, module path, function, class, command, or test
    concrete_indicators = [
        re.compile(r"[.\w/\\-]+\.\w{1,8}"),  # file paths like foo.py, bar.rs
        re.compile(r"`[^`]+`"),  # backticked commands/symbols
        re.compile(r"\w+\.\w+\("),  # function calls like foo.bar()
        re.compile(r"\btests?/\w"),  # test directory references
        re.compile(r"\bpytest\b"),
        re.compile(r"\bruff\b"),
        re.compile(r"\bmypy\b"),
        re.compile(r"\bclass\s+\w"),
        re.compile(r"\bdef\s+\w"),
    ]
    for pat in concrete_indicators:
        if pat.search(text):
            return True

    # Has a validation hint
    if todo.validation_hint and todo.validation_hint.strip():
        return True

    # Has clear action and target (heuristic: verb + object with specificity)
    # Check for path separators or dotted names
    if "/" in text or "\\" in text or "." in text:
        return True

    # Fewer than 3 meaningful words
    words = [w for w in text.split() if len(w) > 1]
    if len(words) < 3:
        return False

    # Too short
    stripped = text.replace(" ", "")
    if len(stripped) < 12:
        return False

    return False


def _has_file_reference(plan: PlanRecord) -> bool:
    if plan.files:
        return True
    # Check body for file-like paths
    for line in plan.body.splitlines():
        if re.search(r"[.\w/\\-]+\.\w{1,8}", line):
            return True
    return False


def _has_test_command(plan: PlanRecord) -> bool:
    if plan.test_commands:
        return True
    # Check body for code blocks with test commands
    test_tools = {"pytest", "ruff", "mypy", "python -m", "tox", "pre-commit"}
    for line in plan.body.splitlines():
        stripped = line.strip()
        for tool in test_tools:
            if tool in stripped:
                return True
    return False


def _has_expected_output(plan: PlanRecord) -> bool:
    if plan.expected_outputs:
        return True
    section = _body_section(plan.body, "Expected output")
    if section:
        return True
    section = _body_section(plan.body, "Expected outputs")
    if section:
        return True
    # Check if any todos have validation hints
    for todo in plan.todos:
        if todo.validation_hint and todo.validation_hint.strip():
            return True
    return False


def _todos_have_validation_hints(plan: PlanRecord) -> bool:
    return any(
        todo.validation_hint and todo.validation_hint.strip() for todo in plan.todos
    )
