from __future__ import annotations

import subprocess
from pathlib import Path
from typing import NamedTuple


class CommandResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


def run_command(argv: tuple[str, ...], *, cwd: Path) -> CommandResult:
    """Run a non-interactive managed evidence command.

    Managed Taskledger commands capture stdout/stderr and intentionally close
    stdin so child processes cannot interact with Click/Typer's isolated test
    input streams or block waiting for terminal input.
    """
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)
