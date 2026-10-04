from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

import typer

from taskledger.api.search import (
    dependencies_for_module,
    grep_workspace,
    search_workspace,
    symbols_workspace,
)
from taskledger.cli_common import CLIState, emit_error, emit_payload
from taskledger.errors import LaunchError


def search_command(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(..., help="Search query.")],
    repo_refs: Annotated[list[str] | None, typer.Option("--repo")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    _emit_search_results(
        ctx,
        lambda cwd: search_workspace(
            cwd,
            query=query,
            repo_refs=tuple(repo_refs or ()),
            limit=limit,
        ),
        title="SEARCH",
    )


def grep_command(
    ctx: typer.Context,
    pattern: Annotated[str, typer.Argument(..., help="Regex pattern.")],
    repo_refs: Annotated[list[str] | None, typer.Option("--repo")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 100,
) -> None:
    _emit_search_results(
        ctx,
        lambda cwd: grep_workspace(
            cwd,
            pattern=pattern,
            repo_refs=tuple(repo_refs or ()),
            limit=limit,
        ),
        title="GREP",
    )


def symbols_command(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(..., help="Symbol query.")],
    repo_refs: Annotated[list[str] | None, typer.Option("--repo")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    _emit_search_results(
        ctx,
        lambda cwd: symbols_workspace(
            cwd,
            query=query,
            repo_refs=tuple(repo_refs or ()),
            limit=limit,
        ),
        title="SYMBOLS",
    )


def deps_command(
    ctx: typer.Context,
    repo_ref: Annotated[str, typer.Argument(..., help="Repo ref.")],
    module: Annotated[str, typer.Argument(..., help="Module path.")],
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        payload = dependencies_for_module(
            state.cwd,
            repo_ref=repo_ref,
            module=module,
        )
    except LaunchError as exc:
        emit_error(ctx, str(exc))
        raise typer.Exit(code=1) from exc
    emit_payload(ctx, payload)


def _emit_search_results(
    ctx: typer.Context,
    factory: Callable[..., Any],
    *,
    title: str,
) -> None:
    state = ctx.obj
    assert isinstance(state, CLIState)
    try:
        results = factory(state.cwd)
    except LaunchError as exc:
        emit_error(ctx, str(exc))
        raise typer.Exit(code=1) from exc
    human = (
        "\n".join([title, *[item.path for item in results]])
        if results
        else f"{title}\n(empty)"
    )
    emit_payload(ctx, [item.to_dict() for item in results], human=human)


def register_search_commands(app: typer.Typer) -> None:
    app.command("search")(search_command)
    app.command("grep")(grep_command)
    app.command("symbols")(symbols_command)
    app.command("deps")(deps_command)
