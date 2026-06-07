"""BDD API functions for taskledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from taskledger.domain.bdd import (
    BddExampleRecord,
    BddFeatureRecord,
    BddRuleRecord,
)
from taskledger.errors import LaunchError
from taskledger.storage.task_store import (
    load_bdd_examples,
    load_bdd_feature,
    load_bdd_reports,
    load_bdd_rules,
    resolve_bdd_example,
    resolve_bdd_rule,
    save_bdd_example,
    save_bdd_feature,
    save_bdd_rule,
)
from taskledger.timeutils import utc_now_iso


def _next_id(items: list[Any], prefix: str) -> str:
    """Generate the next sequential ID for a collection."""
    max_num = 0
    for item in items:
        item_id = item.id if hasattr(item, "id") else ""
        if item_id.startswith(prefix + "-"):
            try:
                num = int(item_id.split("-", 1)[1])
                max_num = max(max_num, num)
            except ValueError:
                pass
    return f"{prefix}-{max_num + 1:04d}"


def bdd_init(
    workspace_root: Path,
    task_id: str,
    title: str,
    description: str = "",
) -> dict[str, Any]:
    """Initialize BDD for a task by creating a feature record."""
    existing = load_bdd_feature(workspace_root, task_id)
    if existing is not None:
        raise LaunchError(
            f"BDD already initialized for {task_id}. Feature: {existing.title}"
        )

    feature = BddFeatureRecord(
        id="feature-0001",
        task_id=task_id,
        title=title,
        description=description,
    )
    save_bdd_feature(workspace_root, feature)
    return {
        "kind": "bdd_init",
        "task_id": task_id,
        "feature": feature.to_dict(),
    }


def bdd_status(workspace_root: Path, task_id: str) -> dict[str, Any]:
    """Get BDD status for a task."""
    feature = load_bdd_feature(workspace_root, task_id)
    rules = load_bdd_rules(workspace_root, task_id)
    examples = load_bdd_examples(workspace_root, task_id)
    reports = load_bdd_reports(workspace_root, task_id)

    examples_by_status: dict[str, int] = {}
    for ex in examples:
        examples_by_status[ex.status] = examples_by_status.get(ex.status, 0) + 1

    return {
        "kind": "bdd_status",
        "task_id": task_id,
        "feature_title": feature.title if feature else None,
        "rule_count": len(rules),
        "example_count": len(examples),
        "report_count": len(reports),
        "examples_by_status": examples_by_status,
    }


def bdd_rule_add(
    workspace_root: Path,
    task_id: str,
    title: str,
    description: str = "",
    feature_id: str = "bdd",
) -> dict[str, Any]:
    """Add a BDD rule."""
    rules = load_bdd_rules(workspace_root, task_id)
    rule_id = _next_id(rules, "rule")
    rule = BddRuleRecord(
        id=rule_id,
        task_id=task_id,
        title=title,
        description=description,
        feature_id=feature_id,
    )
    save_bdd_rule(workspace_root, rule)
    return {
        "kind": "bdd_rule",
        "task_id": task_id,
        "rule": rule.to_dict(),
    }


def bdd_rule_list(workspace_root: Path, task_id: str) -> dict[str, Any]:
    """List BDD rules."""
    rules = load_bdd_rules(workspace_root, task_id)
    return {
        "kind": "bdd_rule_list",
        "task_id": task_id,
        "rules": [r.to_dict() for r in rules],
    }


def bdd_rule_show(workspace_root: Path, task_id: str, rule_id: str) -> dict[str, Any]:
    """Show a BDD rule."""
    rule = resolve_bdd_rule(workspace_root, task_id, rule_id)
    return {
        "kind": "bdd_rule",
        "task_id": task_id,
        "rule": rule.to_dict(),
    }


def bdd_example_add(
    workspace_root: Path,
    task_id: str,
    title: str,
    rule_id: str | None = None,
    given: tuple[str, ...] = (),
    when: tuple[str, ...] = (),
    then: tuple[str, ...] = (),
    acceptance_criteria: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Add a BDD example."""
    examples = load_bdd_examples(workspace_root, task_id)
    example_id = _next_id(examples, "bdd")

    # Determine initial status
    status = "discovered"
    if given or when or then:
        status = "formulated"
    if acceptance_criteria:
        status = "linked"

    example = BddExampleRecord(
        id=example_id,
        task_id=task_id,
        title=title,
        rule_id=rule_id,
        status=status,
        given=given,
        when=when,
        then=then,
        acceptance_criteria=acceptance_criteria,
    )
    save_bdd_example(workspace_root, example)
    return {
        "kind": "bdd_example",
        "task_id": task_id,
        "example": example.to_dict(),
    }


def bdd_example_list(workspace_root: Path, task_id: str) -> dict[str, Any]:
    """List BDD examples."""
    examples = load_bdd_examples(workspace_root, task_id)
    return {
        "kind": "bdd_example_list",
        "task_id": task_id,
        "examples": [e.to_dict() for e in examples],
    }


def bdd_example_show(
    workspace_root: Path, task_id: str, example_id: str
) -> dict[str, Any]:
    """Show a BDD example."""
    example = resolve_bdd_example(workspace_root, task_id, example_id)
    return {
        "kind": "bdd_example",
        "task_id": task_id,
        "example": example.to_dict(),
    }


def bdd_example_link_ac(
    workspace_root: Path,
    task_id: str,
    example_id: str,
    criterion_id: str,
) -> dict[str, Any]:
    """Link a BDD example to an acceptance criterion."""
    example = resolve_bdd_example(workspace_root, task_id, example_id)
    current_ac = list(example.acceptance_criteria)
    if criterion_id not in current_ac:
        current_ac.append(criterion_id)

    # Determine new status
    new_status = example.status
    if current_ac and example.status in ("discovered", "formulated"):
        new_status = "linked"

    updated = BddExampleRecord(
        id=example.id,
        task_id=example.task_id,
        title=example.title,
        rule_id=example.rule_id,
        status=new_status,
        given=example.given,
        when=example.when,
        then=example.then,
        tags=example.tags,
        acceptance_criteria=tuple(current_ac),
        question_refs=example.question_refs,
        todo_refs=example.todo_refs,
        file_refs=example.file_refs,
        archledger_refs=example.archledger_refs,
        automation=example.automation,
        file_version=example.file_version,
        schema_version=example.schema_version,
        object_type=example.object_type,
        created_at=example.created_at,
        updated_at=utc_now_iso(),
    )
    save_bdd_example(workspace_root, updated)
    return {
        "kind": "bdd_example",
        "task_id": task_id,
        "example": updated.to_dict(),
    }


def bdd_example_link_archledger(
    workspace_root: Path,
    task_id: str,
    example_id: str,
    archledger_ref: str,
) -> dict[str, Any]:
    """Link a BDD example to an Archledger record."""
    example = resolve_bdd_example(workspace_root, task_id, example_id)
    current_refs = list(example.archledger_refs)
    if archledger_ref not in current_refs:
        current_refs.append(archledger_ref)

    updated = BddExampleRecord(
        id=example.id,
        task_id=example.task_id,
        title=example.title,
        rule_id=example.rule_id,
        status=example.status,
        given=example.given,
        when=example.when,
        then=example.then,
        tags=example.tags,
        acceptance_criteria=example.acceptance_criteria,
        question_refs=example.question_refs,
        todo_refs=example.todo_refs,
        file_refs=example.file_refs,
        archledger_refs=tuple(current_refs),
        automation=example.automation,
        file_version=example.file_version,
        schema_version=example.schema_version,
        object_type=example.object_type,
        created_at=example.created_at,
        updated_at=utc_now_iso(),
    )
    save_bdd_example(workspace_root, updated)
    return {
        "kind": "bdd_example",
        "task_id": task_id,
        "example": updated.to_dict(),
    }


def bdd_gherkin_export(
    workspace_root: Path,
    task_id: str,
    out: str,
) -> dict[str, Any]:
    """Export BDD examples as Gherkin .feature file."""
    from taskledger.services.bdd_gherkin import export_gherkin

    return export_gherkin(workspace_root, task_id, out)


def bdd_archledger_candidate(
    workspace_root: Path,
    task_id: str,
    example_id: str,
    out: str = "",
) -> dict[str, Any]:
    """Generate an Archledger behavior record candidate from a BDD example."""
    example = resolve_bdd_example(workspace_root, task_id, example_id)

    # Determine suggested type
    suggested_type = "quality_scenario"
    if any(
        keyword in example.title.lower()
        for keyword in ("lifecycle", "gate", "approval", "lock", "contract")
    ):
        suggested_type = "runtime_scenario"

    # Build candidate content
    lines = [
        f"# Archledger Candidate: {example.title}",
        "",
        f"suggested_record_type: {suggested_type}",
        "task_refs:",
        f"  - {task_id}",
        "bdd_refs:",
        f"  - {example.id}",
    ]
    if example.acceptance_criteria:
        lines.append("acceptance_criteria:")
        for ac in example.acceptance_criteria:
            lines.append(f"  - {ac}")

    # Find feature file if automation linked
    if example.automation.feature_file:
        lines.append(f"feature_file: {example.automation.feature_file}")

    lines.append("")
    lines.append("## Body")
    lines.append("")
    if example.given:
        lines.append("**Given:**")
        for step in example.given:
            lines.append(f"- {step}")
    if example.when:
        lines.append("")
        lines.append("**When:**")
        for step in example.when:
            lines.append(f"- {step}")
    if example.then:
        lines.append("")
        lines.append("**Then:**")
        for step in example.then:
            lines.append(f"- {step}")

    content = "\n".join(lines)

    # Write to file if out is specified
    if out:
        out_path = Path(out)
        if not out_path.is_absolute():
            out_path = workspace_root / out_path
        # Security: refuse paths outside workspace
        try:
            out_path.resolve().relative_to(workspace_root.resolve())
        except ValueError:
            raise LaunchError(
                f"Output path must be within workspace: {out}"
            ) from None
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content + "\n", encoding="utf-8")

    candidate = {
        "suggested_type": suggested_type,
        "title": example.title,
        "task_refs": [task_id],
        "acceptance_criteria": list(example.acceptance_criteria),
        "feature_file": example.automation.feature_file,
        "content": content,
    }

    return {
        "kind": "bdd_archledger_candidate",
        "task_id": task_id,
        "example_id": example_id,
        "out": out,
        "candidate": candidate,
    }
