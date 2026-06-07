"""Gherkin export service for BDD examples."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from taskledger.domain.bdd import BddExampleRecord
from taskledger.errors import LaunchError
from taskledger.storage.task_store import (
    load_bdd_examples,
    load_bdd_feature,
    load_bdd_rules,
)


def export_gherkin(
    workspace_root: Path,
    task_id: str,
    out: str,
) -> dict[str, Any]:
    """Export BDD examples as a Gherkin .feature file.

    Rules:
    - Refuse export if no formulated/linked/automated/validated examples exist.
    - Warn if examples lack acceptance-criterion links.
    - Write only under workspace root.
    - Include ownership header.
    - Deterministic ordering by rule then example ID.
    """
    # Validate output path
    out_path = Path(out)
    if not out_path.is_absolute():
        out_path = workspace_root / out_path
    try:
        out_path.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        raise LaunchError(
            f"Output path must be within workspace: {out}"
        ) from None

    # Load data
    feature = load_bdd_feature(workspace_root, task_id)
    if feature is None:
        raise LaunchError(f"BDD not initialized for {task_id}. Run 'bdd init' first.")

    examples = load_bdd_examples(workspace_root, task_id)
    exportable_statuses = {"formulated", "linked", "automated", "validated"}
    exportable = [e for e in examples if e.status in exportable_statuses]

    if not exportable:
        raise LaunchError(
            "No formulated BDD examples found. "
            "Add examples with given/when/then steps before exporting."
        )

    rules = load_bdd_rules(workspace_root, task_id)
    rules_by_id = {r.id: r for r in rules}

    # Collect warnings
    warnings: list[str] = []
    for ex in exportable:
        if not ex.acceptance_criteria:
            warnings.append(f"Example {ex.id} has no acceptance-criterion link.")

    # Group examples by rule
    examples_by_rule: dict[str, list[BddExampleRecord]] = {}
    unruled: list[BddExampleRecord] = []
    for ex in exportable:
        if ex.rule_id and ex.rule_id in rules_by_id:
            examples_by_rule.setdefault(ex.rule_id, []).append(ex)
        else:
            unruled.append(ex)

    # Build Gherkin content
    lines: list[str] = []

    # Ownership header
    lines.append(f"# Generated from Taskledger task {task_id}.")
    lines.append(f"# Source: .taskledger/tasks/{task_id}/bdd/examples/")
    lines.append(
        "# Edit Taskledger BDD records as canonical source "
        "unless ownership is explicitly changed."
    )
    lines.append("")

    # Feature tags
    tags = [f"@{task_id}"]
    if feature.tags:
        tags.extend(f"@{t}" for t in feature.tags)
    lines.append(" ".join(tags))

    # Feature line
    lines.append(f"Feature: {feature.title}")
    lines.append("")

    # Export by rule
    rule_order = sorted(examples_by_rule.keys())
    for rule_id in rule_order:
        rule = rules_by_id[rule_id]
        rule_examples = sorted(examples_by_rule[rule_id], key=lambda e: e.id)

        # Rule tags
        rule_tags = [f"@{rule_id}"]
        if rule.tags:
            rule_tags.extend(f"@{t}" for t in rule.tags)
        lines.append(f"  {' '.join(rule_tags)}")
        lines.append(f"  Rule: {rule.title}")
        lines.append("")

        for ex in rule_examples:
            _append_scenario(lines, ex, indent=4)
        lines.append("")

    # Unruled examples
    if unruled:
        unruled_sorted = sorted(unruled, key=lambda e: e.id)
        for ex in unruled_sorted:
            _append_scenario(lines, ex, indent=2)
        lines.append("")

    content = "\n".join(lines)

    # Write file
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")

    return {
        "kind": "bdd_gherkin_export",
        "task_id": task_id,
        "out": str(out_path),
        "feature": feature.title,
        "exported_examples": [e.id for e in exportable],
        "warnings": warnings,
    }


def _append_scenario(
    lines: list[str],
    example: BddExampleRecord,
    indent: int = 2,
) -> None:
    """Append a scenario block to the Gherkin lines."""
    prefix = " " * indent

    # Tags
    scenario_tags = [f"@{example.id}"]
    if example.rule_id:
        scenario_tags.append(f"@{example.rule_id}")
    if example.tags:
        scenario_tags.extend(f"@{t}" for t in example.tags)
    lines.append(f"{prefix}{' '.join(scenario_tags)}")

    # Scenario line
    lines.append(f"{prefix}Scenario: {example.title}")

    # Given steps
    for i, step in enumerate(example.given):
        keyword = "Given" if i == 0 else "And"
        lines.append(f"{prefix}  {keyword} {step}")

    # When steps
    for i, step in enumerate(example.when):
        keyword = "When" if i == 0 else "And"
        lines.append(f"{prefix}  {keyword} {step}")

    # Then steps
    for i, step in enumerate(example.then):
        keyword = "Then" if i == 0 else "And"
        lines.append(f"{prefix}  {keyword} {step}")

    lines.append("")
