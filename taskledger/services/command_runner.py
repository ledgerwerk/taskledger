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
    input streams or block waiting for terminal input. Do not create a
    Windows-only process group here: these commands are synchronous evidence
    probes, and process-group isolation can turn child console-control handling
    into parent KeyboardInterrupt behavior under Click/Typer test isolation.
    """
    kwargs: dict[str, object] = {
        "cwd": cwd,
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "check": False,
    }
    try:
        completed = subprocess.run(list(argv), **kwargs)  # type: ignore[arg-type]
    except FileNotFoundError:
        return CommandResult(127, "", f"command not found: {argv[0]}" if argv else "")
    except OSError as exc:
        return CommandResult(1, "", str(exc))
    except KeyboardInterrupt:
        return CommandResult(130, "", "interrupted")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)
