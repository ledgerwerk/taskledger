from __future__ import annotations


def append_worker_role(lines: list[str], payload: dict[str, object]) -> None:
    focus = payload.get("focus")
    focused_todo = "none"
    focused_run = "none"
    if isinstance(focus, dict):
        focused_todo = str(focus.get("todo_id") or "none")
        focused_run = str(focus.get("focus_run_id") or "none")
    lines.extend(
        [
            "## Worker Role",
            "",
            f"- role: {payload.get('context_for')}",
            f"- lifecycle_mode: {payload.get('mode')}",
            f"- scope: {payload.get('scope')}",
            f"- focused_todo: {focused_todo}",
            f"- focused_run: {focused_run}",
            "",
        ]
    )


def append_worker_contract(lines: list[str], payload: dict[str, object]) -> None:
    context_for = str(payload.get("context_for") or "full")
    must_items, must_not_items = worker_contract(context_for)
    policy = _worker_step_test_command_policy(payload.get("worker_step"))
    if policy == "may_fail":
        must_items = [
            *must_items,
            (
                "record failing test commands as evidence when this worker "
                "step expects them"
            ),
        ]
    elif policy == "must_pass":
        must_items = [
            *must_items,
            (
                "treat passing checks as required evidence before considering "
                "this worker step complete"
            ),
        ]
        must_not_items = [
            *must_not_items,
            "treat failing checks as completion evidence for a must_pass worker step",
        ]
    lines.extend(["## Worker Contract", "", "You must:"])
    for item in must_items:
        lines.append(f"- {item}")
    lines.extend(["", "You must not:"])
    for item in must_not_items:
        lines.append(f"- {item}")
    lines.append("")


def append_worker_step(lines: list[str], worker_step: object) -> None:
    if not isinstance(worker_step, dict):
        return
    lines.extend(["## Worker step", ""])
    lines.append(f"- id: {worker_step.get('id')}")
    lines.append(f"- label: {worker_step.get('label')}")
    lines.append(f"- lifecycle_stage: {worker_step.get('lifecycle_stage') or 'none'}")
    lines.append(f"- base_context: {worker_step.get('base_context') or 'none'}")
    lines.append(f"- actor_role: {worker_step.get('actor_role') or 'none'}")
    lines.append(f"- kind: {worker_step.get('kind') or 'none'}")
    lines.append(f"- todo_tag: {worker_step.get('todo_tag') or 'none'}")
    lines.append(
        f"- test_command_policy: {worker_step.get('test_command_policy') or 'none'}"
    )
    description = worker_step.get("description")
    if isinstance(description, str) and description.strip():
        lines.extend(["", "Description:", description.strip()])
    required_output = worker_step.get("required_output")
    if isinstance(required_output, list) and required_output:
        lines.extend(["", "Required output:"])
        for item in required_output:
            lines.append(f"- {item}")
    must_not = worker_step.get("must_not")
    if isinstance(must_not, list) and must_not:
        lines.extend(["", "Must not:"])
        for item in must_not:
            lines.append(f"- {item}")
    lines.append("")


def guardrails_for_context_for(context_for: str) -> list[str]:
    if context_for == "planner":
        return [
            "Produce a reviewable plan.",
            "Ask required questions.",
            "Do not implement.",
        ]
    if context_for == "implementer":
        return [
            "Implement only the accepted plan and focused todo.",
            "Do not validate.",
            "Log changes.",
            "Mark todo done only with evidence.",
        ]
    if context_for == "validator":
        return [
            "Validate against the accepted plan and implementation log.",
            "Record failed validation.",
            "Do not modify implementation.",
        ]
    if context_for == "spec-reviewer":
        return [
            "Judge spec compliance only.",
            "Do not rewrite code.",
            "Avoid broad style advice unless it affects compliance.",
        ]
    if context_for == "code-reviewer":
        return [
            "Judge maintainability, correctness risks, testing, and safety.",
            "Do not change validation state.",
            "Do not approve task completion.",
        ]
    return ["Use this handoff as the source of truth for the next step."]


def worker_contract(context_for: str) -> tuple[list[str], list[str]]:
    if context_for == "implementer":
        return (
            [
                "implement only the focused todo when one is selected",
                "preserve accepted plan constraints",
                "log implementation changes",
                "mark the focused todo done only with evidence",
            ],
            [
                "validate the task",
                "mark unrelated todos done",
                "change the approved plan",
            ],
        )
    if context_for == "validator":
        return (
            [
                "validate against the accepted plan and implementation record",
                "record failed and blocked validation explicitly",
            ],
            [
                "modify implementation code",
                "approve missing evidence implicitly",
            ],
        )
    if context_for == "spec-reviewer":
        return (
            [
                "judge whether the focused run satisfies the plan and "
                "acceptance criteria",
                "cite concrete evidence for pass, fail, or unclear findings",
            ],
            [
                "rewrite code",
                "change validation state",
                "give broad style advice unrelated to compliance",
            ],
        )
    if context_for == "code-reviewer":
        return (
            [
                "judge maintainability, correctness risk, testing, and safety",
                "cite concrete evidence for risky changes",
            ],
            [
                "change validation state",
                "approve task completion",
            ],
        )
    if context_for == "planner":
        return (
            [
                "produce a reviewable plan body",
                "surface assumptions and open questions",
            ],
            ["start implementation"],
        )
    if context_for == "full":
        return (
            ["use this dossier as the durable source of truth"],
            ["assume chat history"],
        )
    return (
        ["use this handoff as the source of truth"],
        ["ignore recorded state"],
    )


def _worker_step_test_command_policy(worker_step: object) -> str | None:
    if not isinstance(worker_step, dict):
        return None
    policy = worker_step.get("test_command_policy")
    if not isinstance(policy, str):
        return None
    normalized = policy.strip()
    return normalized or None


__all__ = [
    "append_worker_contract",
    "append_worker_role",
    "append_worker_step",
    "guardrails_for_context_for",
    "worker_contract",
]
