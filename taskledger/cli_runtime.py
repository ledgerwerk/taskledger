"""CLI command for runtime provenance reporting."""

from __future__ import annotations

import typer

from taskledger.cli_common import CLIState, emit_payload
from taskledger.services.runtime_info import collect_runtime_info

runtime_app = typer.Typer(
    add_completion=False, help="Show Taskledger runtime provenance."
)


@runtime_app.callback(invoke_without_command=True)
def runtime_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    state = ctx.obj
    assert isinstance(state, CLIState)
    info = collect_runtime_info()
    payload = info.to_dict()
    emit_payload(ctx, payload, human=info.human_summary())


__all__ = ["runtime_app"]
