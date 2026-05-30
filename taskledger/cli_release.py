from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer

from taskledger.api.releases import (
    build_changelog_context,
    list_release_records,
    show_release,
    tag_release,
)
from taskledger.cli_common import (
    cli_state_from_context,
    emit_error,
    emit_payload,
    human_kv,
    launch_error_exit_code,
    render_json,
    write_text_output,
)
from taskledger.errors import LaunchError
from taskledger.services.releases import (
    _normalize_included_statuses,
)


def register_release_commands(app: typer.Typer) -> None:
    @app.command("tag")
    def tag_command(
        ctx: typer.Context,
        version: Annotated[str, typer.Argument(..., help="Release version.")],
        at_task: Annotated[str, typer.Option("--at-task", help="Boundary task ref.")],
        note: Annotated[str | None, typer.Option("--note")] = None,
        changelog_file: Annotated[Path | None, typer.Option("--changelog-file")] = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = tag_release(
                state.cwd,
                version=version,
                at_task=at_task,
                note=note,
                changelog_file=(
                    str(changelog_file) if changelog_file is not None else None
                ),
            )
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        release = cast(dict[str, object], payload["release"])
        emit_payload(
            ctx,
            payload,
            human=(f"tagged release {version} at {release['boundary_task_id']}"),
        )

    @app.command("list")
    def list_command(ctx: typer.Context) -> None:
        state = cli_state_from_context(ctx)
        payload = {"kind": "release_list", "releases": list_release_records(state.cwd)}
        human_lines = ["RELEASES"]
        releases = cast(list[dict[str, object]], payload["releases"])
        if not releases:
            human_lines.append("(empty)")
        else:
            for release in releases:
                note = release.get("note")
                suffix = f"  {note}" if isinstance(note, str) and note else ""
                human_lines.append(
                    f"{release['version']}  {release['boundary_task_id']}  "
                    f"{release['created_at']}{suffix}"
                )
        emit_payload(ctx, payload, human="\n".join(human_lines))

    @app.command("show")
    def show_command(
        ctx: typer.Context,
        version: Annotated[str, typer.Argument(..., help="Release version.")],
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            payload = show_release(state.cwd, version)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
        release = cast(dict[str, object], payload["release"])
        emit_payload(
            ctx,
            payload,
            human=human_kv(
                f"RELEASE {release['version']}",
                [
                    ("boundary_task_id", release.get("boundary_task_id")),
                    ("created_at", release.get("created_at")),
                    ("previous_version", release.get("previous_version")),
                    ("task_count", release.get("task_count")),
                    ("note", release.get("note")),
                    ("changelog_file", release.get("changelog_file")),
                ],
            ),
        )

    @app.command("changelog")
    def changelog_command(
        ctx: typer.Context,
        version: Annotated[str, typer.Argument(..., help="Target release version.")],
        since_version: Annotated[str | None, typer.Option("--since")] = None,
        since_task: Annotated[str | None, typer.Option("--since-task")] = None,
        from_task: Annotated[str | None, typer.Option("--from-task")] = None,
        until_task: Annotated[str | None, typer.Option("--until-task")] = None,
        format_name: Annotated[str, typer.Option("--format")] = "markdown",
        output: Annotated[Path | None, typer.Option("--output")] = None,
        include_status: Annotated[
            list[str] | None, typer.Option("--include-status")
        ] = None,
        fail_on_omitted: Annotated[bool, typer.Option("--fail-on-omitted")] = False,
        target_changelog: Annotated[
            str | None, typer.Option("--target-changelog")
        ] = None,
        release_date: Annotated[str | None, typer.Option("--release-date")] = None,
    ) -> None:
        state = cli_state_from_context(ctx)
        try:
            normalized_statuses = _normalize_included_statuses(
                tuple(include_status) if include_status is not None else None
            )
            if state.json_output:
                payload = cast(
                    dict[str, object],
                    build_changelog_context(
                        state.cwd,
                        version=version,
                        since_version=since_version,
                        since_task=since_task,
                        from_task=from_task,
                        until_task=until_task,
                        format_name="json",
                        include_statuses=normalized_statuses,
                        fail_on_omitted=fail_on_omitted,
                        target_changelog=target_changelog,
                        release_date=release_date,
                    ),
                )
                if output is not None:
                    rendered_output = build_changelog_context(
                        state.cwd,
                        version=version,
                        since_version=since_version,
                        since_task=since_task,
                        from_task=from_task,
                        until_task=until_task,
                        format_name=format_name,
                        include_statuses=normalized_statuses,
                        fail_on_omitted=fail_on_omitted,
                        target_changelog=target_changelog,
                        release_date=release_date,
                    )
                    output_text = (
                        rendered_output
                        if isinstance(rendered_output, str)
                        else render_json(rendered_output)
                    )
                    write_text_output(output, output_text)
                emit_payload(ctx, payload, result_type="release_changelog_context")
                return

            rendered = build_changelog_context(
                state.cwd,
                version=version,
                since_version=since_version,
                since_task=since_task,
                from_task=from_task,
                until_task=until_task,
                format_name=format_name,
                include_statuses=normalized_statuses,
                fail_on_omitted=fail_on_omitted,
                target_changelog=target_changelog,
                release_date=release_date,
            )
            output_text = (
                rendered if isinstance(rendered, str) else render_json(rendered)
            )
            if output is not None:
                target = write_text_output(output, output_text)
                typer.echo(f"wrote release changelog context to {target}")
                return
            typer.echo(output_text, nl=False)
        except LaunchError as exc:
            emit_error(ctx, exc)
            raise typer.Exit(code=launch_error_exit_code(exc)) from exc
