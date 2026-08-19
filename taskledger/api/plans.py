from pathlib import Path

from taskledger.services.plan_input import (
    check_plan_input,
    plan_input_schema_text,
)
from taskledger.services.plan_lint import lint_plan
from taskledger.services.plan_review import (
    PlanReviewOptions,
    build_plan_review_payload,
    render_plan_review,
)
from taskledger.services.tasks import (
    amend_plan,
    approve_plan,
    diff_plan,
    export_plan,
    list_plan_versions,
    materialize_plan_todos,
    plan_template,
    propose_plan,
    regenerate_plan_from_answers,
    reject_plan,
    revise_plan,
    run_planning_command,
    show_plan,
    start_planning,
    upsert_plan,
)

__all__ = [
    "PlanReviewOptions",
    "amend_plan",
    "approve_plan",
    "build_plan_review_payload",
    "check_plan_input",
    "diff_plan",
    "export_plan",
    "lint_plan",
    "list_plan_versions",
    "materialize_plan_todos",
    "plan_guidance",
    "plan_input_schema_text",
    "plan_template",
    "propose_plan",
    "regenerate_plan_from_answers",
    "reject_plan",
    "render_plan_review",
    "revise_plan",
    "run_planning_command",
    "show_plan",
    "start_planning",
    "upsert_plan",
]


from taskledger.services.workflow_guidance import (
    planning_guidance_payload as _planning_guidance_payload,
)


def plan_guidance(
    workspace_root: Path,
    task_ref: str,
) -> dict[str, object]:
    return _planning_guidance_payload(workspace_root, task_ref)
