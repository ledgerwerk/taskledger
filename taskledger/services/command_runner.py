from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import NamedTuple

_IS_WINDOWS = platform.system() == "Windows"


class CommandResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


def run_command(argv: tuple[str, ...], *, cwd: Path) -> CommandResult:
    """Run a non-interactive managed evidence command.

    Managed Taskledger commands capture stdout/stderr and intentionally close
    stdin so child processes cannot interact with Click/Typer's isolated test
    input streams or block waiting for terminal input. Parent process
    interrupts are not converted into child command results; callers should
    handle KeyboardInterrupt at the CLI boundary.
    """
    kwargs: dict[str, object] = {
        "cwd": cwd,
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
        "check": False,
    }
    if _IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    try:
        completed = subprocess.run(list(argv), **kwargs)  # type: ignore[call-overload]
    except FileNotFoundError:
        return CommandResult(127, "", f"command not found: {argv[0]}" if argv else "")
    except OSError as exc:
        return CommandResult(1, "", str(exc))
    except KeyboardInterrupt:
        raise
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)
