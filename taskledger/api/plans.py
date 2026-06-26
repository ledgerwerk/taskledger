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
    "start_planning",
    "propose_plan",
    "upsert_plan",
    "export_plan",
    "amend_plan",
    "list_plan_versions",
    "show_plan",
    "diff_plan",
    "approve_plan",
    "plan_template",
    "regenerate_plan_from_answers",
    "materialize_plan_todos",
    "reject_plan",
    "revise_plan",
    "run_planning_command",
    "lint_plan",
    "check_plan_input",
    "plan_input_schema_text",
    "PlanReviewOptions",
    "build_plan_review_payload",
    "render_plan_review",
    "plan_guidance",
]


from taskledger.services.workflow_guidance import (
    planning_guidance_payload as _planning_guidance_payload,
)


def plan_guidance(
    workspace_root: Path,
    task_ref: str,
) -> dict[str, object]:
    return _planning_guidance_payload(workspace_root, task_ref)
