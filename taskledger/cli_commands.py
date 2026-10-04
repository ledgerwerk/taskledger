from __future__ import annotations

from typing import Annotated

import typer

from taskledger.cli_common import CLIState, emit_payload
from taskledger.command_inventory import COMMAND_METADATA


def commands_command(
    ctx: typer.Context,
    audience: Annotated[
        str | None,
        typer.Option(
            "--audience",
            help="Filter by audience type.",
        ),
    ] = None,
    effect: Annotated[
        str | None,
        typer.Option(
            "--effect",
            help="Filter by command effect (safe-read-only, ledger-mutation).",
        ),
    ] = None,
    surface: Annotated[
        str | None,
        typer.Option(
            "--surface",
            help="Filter by surface tier (primary, support, advanced, etc.).",
        ),
    ] = None,
    phase: Annotated[
        str | None,
        typer.Option(
            "--phase",
            help="Filter by lifecycle phase.",
        ),
    ] = None,
    tier: Annotated[
        str | None,
        typer.Option(
            "--tier",
            help="Filter by tier (critical, normal, rare).",
        ),
    ] = None,
    include_deprecated: Annotated[
        bool,
        typer.Option(
            "--include-deprecated",
            help="Include deprecated commands (hidden by default).",
        ),
    ] = False,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)

    audience_normalized = audience.replace("-", "_") if audience else None
    effect_normalized = effect.replace("-", "_") if effect else None

    filtered_commands: list[dict[str, object]] = []
    for cmd, spec in sorted(COMMAND_METADATA.items()):
        if not include_deprecated and spec.deprecated:
            continue
        if audience_normalized and spec.audience != audience_normalized:
            continue
        if effect_normalized and spec.effect != effect_normalized:
            continue
        if surface and spec.surface != surface:
            continue
        if phase and spec.phase != phase:
            continue
        if tier and spec.tier != tier:
            continue
        filtered_commands.append(
            {
                "command": cmd,
                "audience": spec.audience,
                "effect": spec.effect,
                "surface": spec.surface,
                "phase": spec.phase,
                "tier": spec.tier,
                "targeting": spec.targeting,
                "deprecated": spec.deprecated,
                "replaced_by": spec.replaced_by,
                "deprecated_since": spec.deprecated_since,
                "remove_in": spec.remove_in,
                "ledger_effect": spec.ledger_effect,
                "workspace_effect": spec.workspace_effect,
                "external_effect": spec.external_effect,
                "agent_safe": spec.agent_safe,
            }
        )

    payload = {
        "kind": "taskledger_command_inventory",
        "commands": filtered_commands,
    }

    if state.json_output:
        emit_payload(ctx, payload)
    else:
        if not filtered_commands:
            typer.echo("No commands matching the specified filters.")
            return

        _cmd_lens = [len(str(cmd["command"])) for cmd in filtered_commands]
        _aud_lens = [len(str(cmd["audience"])) for cmd in filtered_commands]
        _eff_lens = [len(str(cmd["effect"])) for cmd in filtered_commands]
        _sur_lens = [len(str(cmd["surface"])) for cmd in filtered_commands]
        _pha_lens = [len(str(cmd["phase"])) for cmd in filtered_commands]
        _tier_lens = [len(str(cmd["tier"])) for cmd in filtered_commands]
        _target_lens = [len(str(cmd["targeting"])) for cmd in filtered_commands]
        max_cmd = max(_cmd_lens + [len("Command")]) if filtered_commands else 10
        max_aud = max(_aud_lens + [len("Audience")]) if filtered_commands else 10
        max_eff = max(_eff_lens + [len("Effect")]) if filtered_commands else 10
        max_sur = max(_sur_lens + [len("Surface")]) if filtered_commands else 10
        max_pha = max(_pha_lens + [len("Phase")]) if filtered_commands else 10
        max_tier = max(_tier_lens + [len("Tier")]) if filtered_commands else 10
        max_target = max(_target_lens + [len("Targeting")]) if filtered_commands else 10

        header = (
            f"{'Command':<{max_cmd}}  "
            f"{'Audience':<{max_aud}}  "
            f"{'Effect':<{max_eff}}  "
            f"{'Surface':<{max_sur}}  "
            f"{'Phase':<{max_pha}}  "
            f"{'Tier':<{max_tier}}  "
            f"{'Targeting':<{max_target}}"
        )
        typer.echo(header)
        sep_len = (
            max_cmd + max_aud + max_eff + max_sur + max_pha + max_tier + max_target + 12
        )
        typer.echo("-" * sep_len)

        for cmd_info in filtered_commands:
            typer.echo(
                f"{cmd_info['command']:<{max_cmd}}  "
                f"{cmd_info['audience']:<{max_aud}}  "
                f"{cmd_info['effect']:<{max_eff}}  "
                f"{cmd_info['surface']:<{max_sur}}  "
                f"{cmd_info['phase']:<{max_pha}}  "
                f"{cmd_info['tier']:<{max_tier}}  "
                f"{cmd_info['targeting']:<{max_target}}"
            )


def register_command_inventory_command(app: typer.Typer) -> None:
    app.command("commands")(commands_command)
