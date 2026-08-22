from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

from taskledger.domain.models import (
    PlanRecord,
    QuestionRecord,
    TaskLock,
    TaskRecord,
    TaskTodo,
)
from taskledger.storage.locks import lock_is_expired


def _answer_snapshot_hash(questions: list[QuestionRecord]) -> str | None:
    answered = [
        f"{item.id}\0{item.answer or ''}"
        for item in questions
        if item.status == "answered"
    ]
    if not answered:
        return None
    from taskledger.storage.common import content_hash as lc_content_hash

    return f"sha256:{lc_content_hash(chr(10).join(sorted(answered)))}"


def _required_open_question_ids(questions: list[QuestionRecord]) -> list[str]:
    return [
        item.id
        for item in questions
        if item.status == "open" and item.required_for_plan
    ]


def _stale_answer_question_ids(
    questions: list[QuestionRecord],
    plan: PlanRecord,
) -> list[str]:
    answered = [
        item
        for item in questions
        if item.status == "answered" and item.required_for_plan
    ]
    if not answered:
        return []
    current_hash = _answer_snapshot_hash(questions)
    if (
        plan.generation_reason == "after_questions"
        and plan.based_on_answer_hash == current_hash
    ):
        return []
    return [item.id for item in answered]


def _question_next_item(question: QuestionRecord) -> dict[str, object]:
    return {
        "kind": "question",
        "id": question.id,
        "text": question.question,
        "status": question.status,
        "required_for_plan": question.required_for_plan,
        "plan_version": question.plan_version,
    }


def _answered_question_next_item(question: QuestionRecord) -> dict[str, object]:
    return {
        "kind": "answered_question",
        "id": question.id,
        "text": question.question,
        "status": question.status,
        "answer": question.answer,
        "answered_at": question.answered_at,
        "required_for_plan": question.required_for_plan,
        "plan_version": question.plan_version,
    }


def _todo_done_command(todo_id: str) -> str:
    return f'taskledger todo done {todo_id} --evidence "..."'


def _todo_next_item(todo: TaskTodo) -> dict[str, object]:
    return {
        "kind": "todo",
        "id": todo.id,
        "text": todo.text,
        "status": todo.status,
        "mandatory": todo.mandatory,
        "source": todo.source,
        "done": todo.done,
        "validation_hint": todo.validation_hint,
        "done_command_hint": _todo_done_command(todo.id),
    }


def _criterion_next_item(criterion_report: Mapping[str, object]) -> dict[str, object]:
    return {
        "kind": "criterion",
        "id": criterion_report.get("id"),
        "text": criterion_report.get("text"),
        "mandatory": criterion_report.get("mandatory"),
        "latest_status": criterion_report.get("latest_status"),
        "satisfied": criterion_report.get("satisfied"),
    }


def _plan_next_item(plan: PlanRecord) -> dict[str, object]:
    return {
        "kind": "plan",
        "id": f"plan-v{plan.plan_version}",
        "version": plan.plan_version,
        "status": plan.status,
    }


def _task_next_item(task: TaskRecord) -> dict[str, object]:
    return {
        "kind": "task",
        "id": task.id,
        "status_stage": task.status_stage,
    }


def _lock_next_item(task: TaskRecord, lock: TaskLock) -> dict[str, object]:
    return {
        "kind": "lock",
        "id": lock.lock_id,
        "task_id": task.id,
        "stage": lock.stage,
        "run_id": lock.run_id,
        "expired": lock_is_expired(lock),
    }


def _command(
    kind: str,
    label: str,
    command: str,
    *,
    primary: bool = False,
) -> dict[str, object]:
    return {
        "kind": kind,
        "label": label,
        "command": command,
        "primary": primary,
    }


def _todo_command_hints(todo_id: str) -> list[dict[str, object]]:
    return [
        _command(
            "inspect",
            "Show next todo",
            f"taskledger todo show {todo_id}",
            primary=True,
        ),
        _command(
            "complete",
            "Mark todo done after evidence exists",
            _todo_done_command(todo_id),
        ),
    ]


def _first_question_by_ids(
    questions: Sequence[QuestionRecord],
    ids: Sequence[str],
) -> QuestionRecord | None:
    wanted = set(ids)
    for question in questions:
        if question.id in wanted:
            return question
    return None


def _criterion_report_by_id(
    gate_report: Mapping[str, object],
    criterion_id: str,
) -> dict[str, object] | None:
    criteria = cast(list[dict[str, object]], gate_report.get("criteria", []))
    for criterion in criteria:
        if criterion.get("id") == criterion_id:
            return criterion
    return None


def _compact_next_action_blockers(
    blockers: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    compact: list[dict[str, object]] = []
    for blocker in blockers:
        item: dict[str, object] = {
            "kind": str(blocker.get("kind", "blocker")),
            "message": str(blocker.get("message", "Next-action blocker")),
        }
        ref = blocker.get("ref")
        if isinstance(ref, str) and ref:
            item["ref"] = ref
        command_hint = blocker.get("command_hint")
        if isinstance(command_hint, str):
            command_hint = command_hint.strip()
            if command_hint:
                item["command_hint"] = command_hint
        compact.append(item)
    return compact


def _validation_progress(gate_report: Mapping[str, object]) -> dict[str, object]:
    criteria = cast(list[dict[str, object]], gate_report.get("criteria", []))
    satisfied = sum(1 for criterion in criteria if criterion.get("satisfied") is True)
    blocking_ids: list[str] = []
    for blocker in cast(list[dict[str, object]], gate_report.get("blockers", [])):
        ref = blocker.get("ref")
        if isinstance(ref, str) and ref and ref not in blocking_ids:
            blocking_ids.append(ref)
    return {
        "total": len(criteria),
        "satisfied": satisfied,
        "remaining": max(len(blocking_ids), len(criteria) - satisfied),
        "blocking_ids": blocking_ids,
    }


def _next_validation_item(
    workspace_root: Path,
    task: TaskRecord,
    gate_report: Mapping[str, object],
    blockers: Sequence[Mapping[str, object]],
    *,
    latest_plan_or_none: Callable[[Path, str], PlanRecord | None],
    first_open_todo_from_report: Callable[
        [Path, TaskRecord, Sequence[str]],
        TaskTodo | None,
    ],
) -> dict[str, object] | None:
    priority = (
        "criterion_fail",
        "criterion_missing",
        "criterion_unsatisfied",
        "todo_open",
        "no_finished_implementation",
        "dependency_blocker",
        "no_accepted_plan",
        "plan_not_accepted",
    )
    for kind in priority:
        for blocker in blockers:
            if blocker.get("kind") != kind:
                continue
            ref = blocker.get("ref")
            if kind.startswith("criterion_") and isinstance(ref, str):
                criterion = _criterion_report_by_id(gate_report, ref)
                if criterion is not None:
                    return _criterion_next_item(criterion)
            if kind == "todo_open" and isinstance(ref, str):
                todo = first_open_todo_from_report(workspace_root, task, (ref,))
                if todo is not None:
                    return _todo_next_item(todo)
            if kind == "dependency_blocker" and isinstance(ref, str):
                return {"kind": "dependency", "id": ref}
            if kind == "no_finished_implementation":
                return _task_next_item(task)
            if kind in {"no_accepted_plan", "plan_not_accepted"}:
                plan = latest_plan_or_none(workspace_root, task.id)
                if plan is not None:
                    return _plan_next_item(plan)
                return _task_next_item(task)

    for criterion in cast(list[dict[str, object]], gate_report.get("criteria", [])):
        criterion_blockers = criterion.get("blockers")
        if isinstance(criterion_blockers, list) and criterion_blockers:
            return _criterion_next_item(criterion)
    return None


def _next_action_command(action: str) -> str | None:
    return {
        "plan": "taskledger plan start",
        "plan-propose": "taskledger plan upsert --file plan.md",
        "question-answer": "taskledger question answer-many --file answers.yaml",
        "plan-regenerate": "taskledger plan upsert --from-answers --file plan.md",
        "plan-approve": "taskledger plan review --version VERSION",
        "implement": "taskledger implement start",
        "implement-restart": "taskledger implement restart --summary SUMMARY",
        "implement-resume": "taskledger implement resume --reason REASON",
        "expired-lock-resume": (
            "taskledger implement resume --repair-expired-lock --reason REASON"
        ),
        "todo-work": "taskledger implement checklist",
        "implement-finish": "taskledger implement finish --summary SUMMARY",
        "validate": "taskledger validate start",
        "validate-check": (
            "taskledger validate check --criterion CRITERION "
            '--status pass --evidence "..."'
        ),
        "validate-finish": (
            "taskledger validate finish --result passed --summary SUMMARY"
        ),
        "repair-lock": "taskledger lock show",
        "repair-run-state": "taskledger doctor",
        "review-work": "taskledger handoff show HANDOFF_ID --format markdown",
    }.get(action)


def _implement_resume_command(task_id: str | None = None) -> str:
    command = "taskledger implement resume"
    if task_id is not None:
        command += f" --task {task_id}"
    return (
        command + ' --reason "Reacquire implementation lock for existing running run."'
    )


def _primary_command_for_next_item(
    action: str,
    next_item: dict[str, object] | None,
) -> str | None:
    if not next_item:
        return _next_action_command(action)

    kind = next_item.get("kind")
    item_id = next_item.get("id")

    if kind == "question" and isinstance(item_id, str):
        return f'taskledger question answer {item_id} --text "..."'
    if kind == "todo" and isinstance(item_id, str):
        return f"taskledger todo show {item_id}"
    if kind == "criterion" and isinstance(item_id, str):
        return (
            f"taskledger validate check --criterion {item_id} "
            '--status pass --evidence "..."'
        )
    if kind == "plan":
        version = next_item.get("version")
        if isinstance(version, int):
            return f"taskledger plan review --version {version}"
    if kind == "task" and isinstance(item_id, str):
        if action in ("implement-resume", "expired-lock-resume"):
            return _implement_resume_command(item_id)
        if action == "repair-active-stage":
            return f"taskledger task show --task {item_id}"
    if kind == "handoff" and isinstance(item_id, str):
        return f"taskledger handoff show {item_id} --format markdown"
    if kind == "lock":
        task_id = next_item.get("task_id")
        if isinstance(task_id, str):
            if action == "expired-lock-resume":
                return (
                    f"taskledger implement resume"
                    f" --repair-expired-lock --task {task_id}"
                    f' --reason "..."'
                )
            return f'taskledger repair lock --task {task_id} --reason "..."'

    return _next_action_command(action)


def _commands_for_next_item(
    action: str,
    next_item: dict[str, object] | None,
) -> list[dict[str, object]]:
    if next_item is None:
        primary = _primary_command_for_next_item(action, next_item)
        if primary is None:
            return []
        label = {
            "plan": "Start planning",
            "plan-propose": "Propose plan",
            "plan-regenerate": "Regenerate plan from answers",
            "plan-approve": "Review proposed plan",
            "implement": "Start implementation",
            "implement-restart": "Restart implementation",
            "todo-work": "Show implementation checklist",
            "implement-finish": "Finish implementation",
            "validate": "Start validation",
            "validate-check": "Record validation check",
            "validate-finish": "Finish validation",
            "repair-lock": "Show current lock",
        }.get(action, "Show next action")
        command_kind = {
            "plan": "start",
            "plan-propose": "regenerate",
            "plan-regenerate": "regenerate",
            "plan-approve": "inspect",
            "implement": "start",
            "implement-restart": "restart",
            "todo-work": "context",
            "implement-finish": "finish",
            "validate": "start",
            "validate-check": "check",
            "validate-finish": "finish",
            "repair-lock": "inspect",
        }.get(action, "context")
        return [_command(command_kind, label, primary, primary=True)]

    item_kind = next_item.get("kind")
    item_id = next_item.get("id")
    if item_kind == "question" and isinstance(item_id, str):
        return [
            _command(
                "answer",
                "Answer required question",
                f'taskledger question answer {item_id} --text "..."',
                primary=True,
            ),
            _command("context", "Show question status", "taskledger question status"),
        ]
    if item_kind == "answered_question":
        return [
            _command(
                "regenerate",
                "Regenerate plan from answers",
                "taskledger plan upsert --from-answers --file plan.md",
                primary=True,
            ),
            _command(
                "context",
                "Show answered questions",
                "taskledger question answers",
            ),
        ]
    if item_kind == "handoff" and isinstance(item_id, str):
        return [
            _command(
                "inspect",
                "Show review handoff",
                f"taskledger handoff show {item_id} --format markdown",
                primary=True,
            ),
            _command(
                "record",
                "Record review evidence",
                f"taskledger review record --handoff {item_id} --result pass|fail|blocked ...",  # noqa: E501
            ),
        ]
    if item_kind == "todo" and isinstance(item_id, str):
        return [
            *_todo_command_hints(item_id),
            _command(
                "context",
                "Show implementation checklist",
                "taskledger implement checklist",
            ),
        ]
    if item_kind == "criterion" and isinstance(item_id, str):
        return [
            _command(
                "check",
                "Record validation check",
                (
                    f"taskledger validate check --criterion {item_id} "
                    '--status pass --evidence "..."'
                ),
                primary=True,
            ),
            _command("context", "Show validation status", "taskledger validate status"),
        ]
    if item_kind == "plan":
        version = next_item.get("version")
        if isinstance(version, int):
            commands = [
                _command(
                    "inspect",
                    "Review proposed plan",
                    f"taskledger plan review --version {version}",
                    primary=True,
                )
            ]
            if action == "plan-approve":
                commands.append(
                    _command(
                        "accept",
                        "Accept plan after explicit user approval",
                        (
                            f"taskledger plan accept --version {version} --note "
                            '"User approved in harness."'
                        ),
                    )
                )
                commands.append(
                    _command(
                        "revise",
                        "Revise proposed plan",
                        "taskledger plan revise",
                    )
                )
                commands.append(
                    _command(
                        "export",
                        "Export editable plan",
                        (
                            "taskledger plan export "
                            f"--version {version} --file ./plan.md"
                        ),
                    )
                )
            return commands
    if item_kind == "task" and isinstance(item_id, str):
        if action in ("implement-resume", "expired-lock-resume"):
            return [
                _command(
                    "resume",
                    "Resume implementation",
                    _implement_resume_command(item_id),
                    primary=True,
                ),
                _command(
                    "context",
                    "Show implementation checklist",
                    "taskledger implement checklist",
                ),
            ]
        if action == "repair-active-stage":
            return [
                _command(
                    "inspect",
                    "Inspect task state",
                    f"taskledger task show --task {item_id}",
                    primary=True,
                ),
                _command("inspect", "Run doctor", "taskledger doctor"),
            ]
    if item_kind == "lock":
        task_id = next_item.get("task_id")
        if isinstance(task_id, str):
            return [
                _command(
                    "repair",
                    "Repair stale lock",
                    f'taskledger repair lock --task {task_id} --reason "..."',
                    primary=True,
                ),
                _command("inspect", "Show current lock", "taskledger lock show"),
            ]

    primary = _primary_command_for_next_item(action, next_item)
    if primary is None:
        return []
    label = {
        "implement": "Start implementation",
        "implement-restart": "Restart implementation",
        "implement-resume": "Resume implementation",
        "implement-finish": "Finish implementation",
        "expired-lock-resume": "Resume with expired lock",
        "repair-active-stage": "Inspect task state",
        "validate": "Start validation",
        "validate-finish": "Finish validation",
    }.get(action, "Show next action")
    kind_name = {
        "implement": "start",
        "implement-restart": "restart",
        "implement-resume": "resume",
        "implement-finish": "finish",
        "expired-lock-resume": "resume",
        "repair-active-stage": "inspect",
        "validate": "start",
        "validate-finish": "finish",
    }.get(action, "context")
    commands = [_command(kind_name, label, primary, primary=True)]
    if action == "implement-finish":
        commands.append(
            _command(
                "context",
                "Show implementation checklist",
                "taskledger implement checklist",
            )
        )
    if action == "validate-finish":
        commands.append(
            _command(
                "context",
                "Show validation status",
                "taskledger validate status",
            )
        )
    return commands
