"""BDD CLI commands for taskledger."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from taskledger.api.bdd import (
    bdd_archledger_candidate,
    bdd_example_add,
    bdd_example_link_ac,
    bdd_example_link_archledger,
    bdd_example_link_automation,
    bdd_example_list,
    bdd_example_show,
    bdd_export_json,
    bdd_init,
    bdd_rule_add,
    bdd_rule_list,
    bdd_rule_show,
    bdd_status,
)
from taskledger.cli_common import (
    TaskOption,
    cli_state_from_context,
    emit_error,
    emit_payload,
    launch_error_exit_code,
    resolve_cli_task,
)
from taskledger.errors import LaunchError


def register_bdd_commands(app: typer.Typer) -> None:
    """Register BDD commands on the given Typer app."""
    _register_bdd_root_commands(app)
    _register_bdd_rule_commands(app)
    _register_bdd_example_commands(app)
    _register_bdd_export_commands(app)
    _register_bdd_archledger_commands(app)


def _register_bdd_root_commands(app: typer.Typer) -> None:
    """Register bdd root commands: init, status."""

    @app.command("init")
    def bdd_init_cmd(
        ctx: typer.Context,
        feature: Annotated[str, typer.Option("--feature", "-f", help="Feature title.")],
        description: Annotated[
            str, typer.Option("--description", "-d", help="Feature description.")
        ] = "",
        task: TaskOption = None,
    ) -> None:
        """Initialize BDD for the active task."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_init(state.cwd, task_rec.id, feature, description)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_bdd_init(payload))

    @app.command("status")
    def bdd_status_cmd(
        ctx: typer.Context,
        task: TaskOption = None,
    ) -> None:
        """Show BDD status for the active task."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_status(state.cwd, task_rec.id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_bdd_status(payload))


def _register_bdd_rule_commands(app: typer.Typer) -> None:
    """Register bdd rule sub-commands."""
    rule_app = typer.Typer(add_completion=False, help="Manage BDD rules.")
    app.add_typer(rule_app, name="rule")

    @rule_app.command("add")
    def bdd_rule_add_cmd(
        ctx: typer.Context,
        title: Annotated[str, typer.Argument(help="Rule title.")],
        description: Annotated[
            str, typer.Option("--description", "-d", help="Rule description.")
        ] = "",
        feature_id: Annotated[
            str, typer.Option("--feature-id", help="Parent feature ID.")
        ] = "bdd",
        task: TaskOption = None,
    ) -> None:
        """Add a BDD rule."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_rule_add(
                state.cwd, task_rec.id, title, description, feature_id
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_bdd_rule(payload))

    @rule_app.command("list")
    def bdd_rule_list_cmd(
        ctx: typer.Context,
        task: TaskOption = None,
    ) -> None:
        """List BDD rules."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_rule_list(state.cwd, task_rec.id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_bdd_rule_list(payload))

    @rule_app.command("show")
    def bdd_rule_show_cmd(
        ctx: typer.Context,
        rule_id: Annotated[str, typer.Argument(help="Rule ID (e.g. rule-0001).")],
        task: TaskOption = None,
    ) -> None:
        """Show a BDD rule."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_rule_show(state.cwd, task_rec.id, rule_id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_bdd_rule(payload))


def _register_bdd_example_commands(app: typer.Typer) -> None:
    """Register bdd example sub-commands."""
    example_app = typer.Typer(add_completion=False, help="Manage BDD examples.")
    app.add_typer(example_app, name="example")

    @example_app.command("add")
    def bdd_example_add_cmd(
        ctx: typer.Context,
        title: Annotated[str, typer.Option("--title", "-t", help="Example title.")],
        rule: Annotated[
            str | None, typer.Option("--rule", "-r", help="Parent rule ID.")
        ] = None,
        given: Annotated[
            list[str] | None, typer.Option("--given", "-g", help="Given step.")
        ] = None,
        when: Annotated[
            list[str] | None, typer.Option("--when", "-w", help="When step.")
        ] = None,
        then: Annotated[
            list[str] | None, typer.Option("--then", help="Then step.")
        ] = None,
        acceptance_criterion: Annotated[
            list[str] | None,
            typer.Option(
                "--acceptance-criterion", "-ac", help="Acceptance criterion ID."
            ),
        ] = None,
        task: TaskOption = None,
    ) -> None:
        """Add a BDD example/scenario."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_example_add(
                state.cwd,
                task_rec.id,
                title=title,
                rule_id=rule,
                given=tuple(given or ()),
                when=tuple(when or ()),
                then=tuple(then or ()),
                acceptance_criteria=tuple(acceptance_criterion or ()),
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_bdd_example(payload))

    @example_app.command("list")
    def bdd_example_list_cmd(
        ctx: typer.Context,
        task: TaskOption = None,
    ) -> None:
        """List BDD examples."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_example_list(state.cwd, task_rec.id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_bdd_example_list(payload))

    @example_app.command("show")
    def bdd_example_show_cmd(
        ctx: typer.Context,
        example_id: Annotated[str, typer.Argument(help="Example ID (e.g. bdd-0001).")],
        task: TaskOption = None,
    ) -> None:
        """Show a BDD example."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_example_show(state.cwd, task_rec.id, example_id)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_bdd_example(payload))

    @example_app.command("link-ac")
    def bdd_example_link_ac_cmd(
        ctx: typer.Context,
        example_id: Annotated[str, typer.Argument(help="Example ID (e.g. bdd-0001).")],
        criterion_id: Annotated[
            str, typer.Argument(help="Acceptance criterion ID (e.g. ac-0001).")
        ],
        task: TaskOption = None,
    ) -> None:
        """Link a BDD example to an acceptance criterion."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_example_link_ac(
                state.cwd, task_rec.id, example_id, criterion_id
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_bdd_example(payload))

    @example_app.command("link-archledger")
    def bdd_example_link_archledger_cmd(
        ctx: typer.Context,
        example_id: Annotated[str, typer.Argument(help="Example ID (e.g. bdd-0001).")],
        archledger_ref: Annotated[str, typer.Argument(help="Archledger record ID.")],
        task: TaskOption = None,
    ) -> None:
        """Link a BDD example to an Archledger record."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_example_link_archledger(
                state.cwd, task_rec.id, example_id, archledger_ref
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_bdd_example(payload))

    @example_app.command("link-automation")
    def bdd_example_link_automation_cmd(
        ctx: typer.Context,
        example_id: Annotated[str, typer.Argument(help="Example ID (e.g. bdd-0001).")],
        feature_file: Annotated[
            str,
            typer.Option(
                "--feature-file",
                "-f",
                help="Path to the external behavior spec (.feature file).",
            ),
        ],
        scenario: Annotated[
            str,
            typer.Option(
                "--scenario",
                help="Scenario tag or title in the feature file.",
            ),
        ] = "",
        pytest: Annotated[
            str,
            typer.Option(
                "--pytest",
                help="Plain pytest file or nodeid, e.g. tests/test_x.py::test_y.",
            ),
        ] = "",
        acceptance_criterion: Annotated[
            list[str] | None,
            typer.Option(
                "--acceptance-criterion",
                "-ac",
                help="Acceptance criterion ID to link while recording automation.",
            ),
        ] = None,
        allow_missing: Annotated[
            bool,
            typer.Option(
                "--allow-missing",
                help="Allow a missing external behavior spec path.",
            ),
        ] = False,
        task: TaskOption = None,
    ) -> None:
        """Link an external behavior spec and plain pytest metadata to a BDD example."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_example_link_automation(
                state.cwd,
                task_rec.id,
                example_id,
                feature_file,
                scenario,
                pytest_ref=pytest,
                acceptance_criteria=tuple(acceptance_criterion or ()),
                allow_missing=allow_missing,
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_bdd_example(payload))


def _register_bdd_export_commands(app: typer.Typer) -> None:
    """Register bdd export commands."""

    @app.command("gherkin-export")
    def bdd_gherkin_export_cmd(
        ctx: typer.Context,
        out: Annotated[
            str, typer.Option("--out", "-o", help="Output .feature file path.")
        ],
        task: TaskOption = None,
    ) -> None:
        """Export a derived .feature file from Taskledger BDD sidecars."""
        from taskledger.api.bdd import bdd_gherkin_export

        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_gherkin_export(state.cwd, task_rec.id, out)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_gherkin_export(payload))

    @app.command("export-json")
    def bdd_export_json_cmd(
        ctx: typer.Context,
        out: Annotated[str, typer.Option("--out", "-o", help="Output JSON file path.")],
        task: TaskOption = None,
    ) -> None:
        """Export derived JSON exchange data from Taskledger BDD sidecars."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_export_json(state.cwd, task_rec.id, out)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_export_json(payload))


def _register_bdd_archledger_commands(app: typer.Typer) -> None:
    """Register bdd archledger bridge commands."""

    @app.command("archledger-candidate")
    def bdd_archledger_candidate_cmd(
        ctx: typer.Context,
        example_id: Annotated[str, typer.Argument(help="Example ID (e.g. bdd-0001).")],
        out: Annotated[str, typer.Option("--out", "-o", help="Output file path.")] = "",
        task: TaskOption = None,
    ) -> None:
        """Generate an Archledger behavior record candidate from a BDD example."""
        state = cli_state_from_context(ctx)
        try:
            task_rec = resolve_cli_task(state.cwd, task)
            payload = bdd_archledger_candidate(state.cwd, task_rec.id, example_id, out)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        emit_payload(ctx, payload, human=_render_archledger_candidate(payload))


# ── renderers ────────────────────────────────────────────────────


def _render_bdd_init(payload: dict[str, Any]) -> str:
    feature = payload.get("feature", {})
    return (
        f"BDD initialized for {payload.get('task_id', '?')}\n"
        f"Feature: {feature.get('title', '?')} ({feature.get('id', '?')})"
    )


def _render_bdd_status(payload: dict[str, Any]) -> str:
    lines = [
        f"BDD status for {payload.get('task_id', '?')}",
        f"  Feature: {payload.get('feature_title', 'none')}",
        f"  Rules: {payload.get('rule_count', 0)}",
        f"  Examples: {payload.get('example_count', 0)}",
        f"  Reports: {payload.get('report_count', 0)}",
    ]
    by_status = payload.get("examples_by_status", {})
    if by_status:
        lines.append("  Examples by status:")
        for status, count in sorted(by_status.items()):
            lines.append(f"    {status}: {count}")
    return "\n".join(lines)


def _render_bdd_rule(payload: dict[str, Any]) -> str:
    rule = payload.get("rule", {})
    return (
        f"{rule.get('id', '?')} — {rule.get('title', '?')}\n"
        f"  Feature: {rule.get('feature_id', 'bdd')}\n"
        f"  Source: {rule.get('source', 'user')}"
    )


def _render_bdd_rule_list(payload: dict[str, Any]) -> str:
    rules = payload.get("rules", [])
    if not rules:
        return "No BDD rules found."
    lines = [f"BDD rules ({len(rules)}):"]
    for rule in rules:
        lines.append(f"  {rule.get('id', '?')} — {rule.get('title', '?')}")
    return "\n".join(lines)


def _render_bdd_example(payload: dict[str, Any]) -> str:
    example = payload.get("example", {})
    lines = [
        f"{example.get('id', '?')} — {example.get('title', '?')}",
        f"  Rule: {example.get('rule_id', 'none')}",
        f"  Status: {example.get('status', '?')}",
    ]
    ac = example.get("acceptance_criteria", [])
    if ac:
        lines.append(f"  Acceptance criteria: {', '.join(ac)}")
    automation = example.get("automation", {})
    if automation.get("status") != "pending":
        lines.append(f"  Automation: {automation.get('status', '?')}")
    if automation.get("feature_file"):
        lines.append(f"  Behavior spec: {automation.get('feature_file')}")
    if automation.get("scenario"):
        lines.append(f"  Scenario ref: {automation.get('scenario')}")
    pytest_ref = automation.get("pytest_nodeid") or automation.get("pytest_path")
    if pytest_ref:
        lines.append(f"  Pytest: {pytest_ref}")
    for warning in payload.get("warnings", []):
        lines.append(f"  Warning: {warning}")
    return "\n".join(lines)


def _render_bdd_example_list(payload: dict[str, Any]) -> str:
    examples = payload.get("examples", [])
    if not examples:
        return "No BDD examples found."
    lines = [f"BDD examples ({len(examples)}):"]
    for ex in examples:
        ac = ex.get("acceptance_criteria", [])
        ac_str = f" [AC: {', '.join(ac)}]" if ac else ""
        lines.append(
            f"  {ex.get('id', '?')}"
            f" [{ex.get('status', '?')}]"
            f" — {ex.get('title', '?')}{ac_str}"
        )
    return "\n".join(lines)


def _render_gherkin_export(payload: dict[str, Any]) -> str:
    lines = [
        f"Derived Gherkin exported to {payload.get('out', '?')}",
        f"Feature: {payload.get('feature', '?')}",
        f"Exported examples: {len(payload.get('exported_examples', []))}",
    ]
    for warning in payload.get("warnings", []):
        lines.append(f"Warning: {warning}")
    return "\n".join(lines)


def _render_export_json(payload: dict[str, Any]) -> str:
    export = payload.get("export", {})
    return (
        f"BDD export JSON written to {payload.get('out', '?')}\n"
        f"Rules: {len(export.get('rules', []))}\n"
        f"Examples: {len(export.get('examples', []))}\n"
        f"External behavior specs: {len(export.get('external_behavior_specs', []))}"
    )


def _render_archledger_candidate(payload: dict[str, Any]) -> str:
    candidate = payload.get("candidate", {})
    return (
        f"Archledger candidate for {payload.get('example_id', '?')}\n"
        f"  Suggested type: {candidate.get('suggested_type', '?')}\n"
        f"  Title: {candidate.get('title', '?')}"
    )
