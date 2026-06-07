"""BDD report import service for Cucumber JSON and JUnit XML."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from taskledger.domain.bdd import BddAutomationRef, BddExampleRecord, BddReportRecord
from taskledger.domain.sidecars import ValidationCheck
from taskledger.errors import LaunchError
from taskledger.storage.task_store import (
    load_bdd_examples,
    save_bdd_example,
    save_bdd_report,
)
from taskledger.timeutils import utc_now_iso


def import_bdd_report(
    workspace_root: Path,
    task_id: str,
    source_path: str,
    format: str,
    command: str = "",
) -> dict[str, Any]:
    """Import a BDD report from Cucumber JSON or JUnit XML.

    Args:
        workspace_root: Project workspace root.
        task_id: Task ID.
        source_path: Path to the report file.
        format: Report format: cucumber-json, junit-xml.
        command: The test command that produced the report.

    Returns:
        Import result payload.
    """
    report_file = Path(source_path)
    if not report_file.is_absolute():
        report_file = workspace_root / report_file
    if not report_file.exists():
        raise LaunchError(f"Report file not found: {source_path}")

    # Load task examples for matching
    examples = load_bdd_examples(workspace_root, task_id)
    examples_by_title = {e.title: e for e in examples}
    examples_by_scenario = {}
    for e in examples:
        if e.automation.scenario:
            examples_by_scenario[e.automation.scenario] = e

    # Parse report based on format
    if format == "cucumber-json":
        scenarios = _parse_cucumber_json(report_file)
    elif format == "junit-xml":
        scenarios = _parse_junit_xml(report_file)
    else:
        raise LaunchError(f"Unsupported report format: {format}")

    # Match scenarios to examples
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    validation_checks: list[ValidationCheck] = []
    updated_examples: list[BddExampleRecord] = []

    for scenario in scenarios:
        scenario_name = scenario.get("name", "")
        status = scenario.get("status", "unknown")
        error_message = scenario.get("error_message", "")

        # Try to match by automation.scenario or title
        example = examples_by_scenario.get(scenario_name) or examples_by_title.get(
            scenario_name
        )

        if example is None:
            unmatched.append(scenario)
            continue

        # Update example automation status
        new_automation = BddAutomationRef(
            status="automated",
            feature_file=example.automation.feature_file,
            scenario=scenario_name,
            command=command,
            report_path=source_path,
        )

        # Determine new example status
        new_status = example.status
        if status == "passed" and example.status in ("linked", "automated"):
            new_status = "validated"

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
            acceptance_criteria=example.acceptance_criteria,
            question_refs=example.question_refs,
            todo_refs=example.todo_refs,
            file_refs=example.file_refs,
            archledger_refs=example.archledger_refs,
            automation=new_automation,
            file_version=example.file_version,
            schema_version=example.schema_version,
            object_type=example.object_type,
            created_at=example.created_at,
            updated_at=utc_now_iso(),
        )
        save_bdd_example(workspace_root, updated)
        updated_examples.append(updated)

        # Create validation checks for linked criteria
        check_status = "pass" if status == "passed" else "fail"
        for criterion_id in example.acceptance_criteria:
            check = ValidationCheck(
                id=None,
                name=f"BDD: {scenario_name}",
                criterion_id=criterion_id,
                status=check_status,
                details=(
                    f"Cucumber scenario {'passed' if status == 'passed' else 'failed'}."
                    + (f" Error: {error_message}" if error_message else "")
                ),
                evidence=(
                    f"report: {source_path}",
                    f"scenario: {scenario_name}",
                    f"command: {command}" if command else "",
                ),
            )
            validation_checks.append(check)

        matched.append(
            {
                "example_id": example.id,
                "scenario": scenario_name,
                "status": status,
                "criterion_ids": list(example.acceptance_criteria),
            }
        )

    # Save report record
    example_results = []
    for m in matched:
        example_results.append(
            {
                "example_id": m["example_id"],
                "scenario": m["scenario"],
                "status": m["status"],
            }
        )
    for u in unmatched:
        example_results.append(
            {
                "scenario": u.get("name", ""),
                "status": u.get("status", "unknown"),
                "matched": False,
            }
        )

    reports_existing = _count_reports(workspace_root, task_id)
    report_id = f"bdd-report-{reports_existing + 1:04d}"

    report = BddReportRecord(
        id=report_id,
        task_id=task_id,
        source_path=source_path,
        format=format,
        command=command,
        imported_at=utc_now_iso(),
        result=_overall_result(matched),
        example_results=tuple(example_results),
        validation_check_refs=tuple(c.id for c in validation_checks if c.id),
    )
    save_bdd_report(workspace_root, report)

    return {
        "kind": "bdd_report_import",
        "task_id": task_id,
        "report_id": report_id,
        "format": format,
        "matched_examples": [m["example_id"] for m in matched],
        "unmatched_scenarios": [u.get("name", "") for u in unmatched],
        "validation_checks": [
            {
                "check_id": c.id,
                "criterion_id": c.criterion_id,
                "status": c.status,
                "example_id": _find_example_for_check(c, matched),
            }
            for c in validation_checks
        ],
        "result": report.result,
        "warnings": [f"Unmatched scenario: {u.get('name', '?')}" for u in unmatched],
    }


def _parse_cucumber_json(path: Path) -> list[dict[str, Any]]:
    """Parse a Cucumber JSON report file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LaunchError(f"Invalid Cucumber JSON: {exc}") from exc

    if not isinstance(data, list):
        raise LaunchError("Invalid Cucumber JSON: expected array of feature objects.")

    scenarios: list[dict[str, Any]] = []
    for feature in data:
        if not isinstance(feature, dict):
            continue
        elements = feature.get("elements", [])
        if not isinstance(elements, list):
            continue
        for element in elements:
            if not isinstance(element, dict):
                continue
            # Only process scenarios, not backgrounds
            if element.get("type") != "scenario":
                continue

            name = element.get("name", "")
            steps = element.get("steps", [])

            # Determine status from steps
            status = "passed"
            error_message = ""
            for step in steps:
                if not isinstance(step, dict):
                    continue
                result = step.get("result", {})
                if isinstance(result, dict):
                    step_status = result.get("status", "passed")
                    if step_status == "failed":
                        status = "failed"
                        error_message = result.get("error_message", "")
                        break
                    elif step_status == "skipped":
                        # A skipped step means a prior step failed
                        pass

            scenarios.append(
                {
                    "name": name,
                    "status": status,
                    "error_message": error_message,
                    "feature_name": feature.get("name", ""),
                }
            )

    return scenarios


def _parse_junit_xml(path: Path) -> list[dict[str, Any]]:
    """Parse a JUnit XML report file."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise LaunchError(f"Invalid JUnit XML: {exc}") from exc

    root = tree.getroot()

    scenarios: list[dict[str, Any]] = []

    # Handle both <testsuites> and <testsuite> as root
    if root.tag == "testsuites":
        test_suites = root.findall("testsuite")
    elif root.tag == "testsuite":
        test_suites = [root]
    else:
        raise LaunchError(f"Invalid JUnit XML: unexpected root element <{root.tag}>")

    for suite in test_suites:
        suite_name = suite.get("name", "")
        for testcase in suite.findall("testcase"):
            name = testcase.get("name", "")
            classname = testcase.get("classname", "")

            failure = testcase.find("failure")
            error = testcase.find("error")
            skipped = testcase.find("skipped")

            if failure is not None:
                status = "failed"
                error_message = failure.get("message", "")
            elif error is not None:
                status = "failed"
                error_message = error.get("message", "")
            elif skipped is not None:
                status = "skipped"
                error_message = ""
            else:
                status = "passed"
                error_message = ""

            scenarios.append(
                {
                    "name": name,
                    "status": status,
                    "error_message": error_message,
                    "feature_name": suite_name,
                    "classname": classname,
                }
            )

    return scenarios


def _overall_result(matched: list[dict[str, Any]]) -> str:
    """Determine overall result from matched scenarios."""
    if not matched:
        return "unknown"
    if all(m.get("status") == "passed" for m in matched):
        return "passed"
    return "failed"


def _find_example_for_check(
    check: ValidationCheck,
    matched: list[dict[str, Any]],
) -> str | None:
    """Find the example ID for a validation check."""
    for m in matched:
        if check.criterion_id in m.get("criterion_ids", []):
            return m.get("example_id")
    return None


def _count_reports(workspace_root: Path, task_id: str) -> int:
    """Count existing BDD reports for a task."""
    from taskledger.storage.task_store import load_bdd_reports

    return len(load_bdd_reports(workspace_root, task_id))
