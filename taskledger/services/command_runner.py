from __future__ import annotations

import os
import platform
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

_IS_WINDOWS = platform.system() == "Windows"


class CommandResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class ManagedCommandEnvironment:
    env: dict[str, str]
    source: str
    virtualenv: Path | None


def _virtualenv_scripts_dir(venv_root: Path) -> Path:
    return venv_root / ("Scripts" if _IS_WINDOWS else "bin")


def _virtualenv_python(venv_root: Path) -> Path:
    python_name = "python.exe" if _IS_WINDOWS else "python"
    return _virtualenv_scripts_dir(venv_root) / python_name


def _is_usable_virtualenv(
    venv_root: Path,
    *,
    require_pyvenv_cfg: bool,
) -> bool:
    if require_pyvenv_cfg and not (venv_root / "pyvenv.cfg").is_file():
        return False
    return _virtualenv_python(venv_root).is_file()


def _normalized_path_key(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def _with_virtualenv(
    child_env: dict[str, str],
    venv_root: Path,
    *,
    source: str,
    remove_pythonhome: bool,
    virtualenv_value: str | None = None,
) -> ManagedCommandEnvironment:
    scripts_text = str(_virtualenv_scripts_dir(venv_root))
    path_entries = (
        child_env.get("PATH", "").split(os.pathsep) if "PATH" in child_env else []
    )
    scripts_key = _normalized_path_key(scripts_text)
    remaining = [
        entry for entry in path_entries if _normalized_path_key(entry) != scripts_key
    ]
    child_env["PATH"] = os.pathsep.join([scripts_text, *remaining])
    child_env["VIRTUAL_ENV"] = (
        virtualenv_value if virtualenv_value is not None else str(venv_root)
    )
    if remove_pythonhome:
        child_env.pop("PYTHONHOME", None)
    return ManagedCommandEnvironment(
        env=child_env,
        source=source,
        virtualenv=venv_root,
    )


def build_managed_command_environment(
    *,
    workspace_root: Path,
    command_cwd: Path,
    environ: Mapping[str, str] | None = None,
) -> ManagedCommandEnvironment:
    source_env = os.environ if environ is None else environ
    child_env = dict(source_env)
    active_raw = child_env.get("VIRTUAL_ENV")
    if active_raw:
        active = Path(active_raw).expanduser()
        if _is_usable_virtualenv(active, require_pyvenv_cfg=False):
            return _with_virtualenv(
                child_env,
                active,
                source="inherited-virtualenv",
                remove_pythonhome=False,
                virtualenv_value=active_raw,
            )

    cwd = command_cwd.expanduser().resolve()
    workspace = workspace_root.expanduser().resolve()
    candidates: list[tuple[str, Path]] = [
        ("command-cwd-.venv", cwd / ".venv"),
        ("command-cwd-venv", cwd / "venv"),
    ]
    if workspace != cwd:
        candidates.extend(
            [
                ("workspace-.venv", workspace / ".venv"),
                ("workspace-venv", workspace / "venv"),
            ]
        )
    for source, candidate in candidates:
        if _is_usable_virtualenv(candidate, require_pyvenv_cfg=True):
            return _with_virtualenv(
                child_env,
                candidate,
                source=source,
                remove_pythonhome=True,
            )
    return ManagedCommandEnvironment(
        env=child_env,
        source="inherited",
        virtualenv=None,
    )


def run_command(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    """Run a non-interactive evidence command with optional child environment."""
    kwargs: dict[str, object] = {
        "cwd": cwd,
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "text": True,
    }
    if env is not None:
        kwargs["env"] = dict(env)
    if _IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            **kwargs,  # type: ignore[call-overload]
        )
    except FileNotFoundError:
        return CommandResult(127, "", f"command not found: {argv[0]}" if argv else "")
    except OSError as exc:
        return CommandResult(1, "", str(exc))
    except KeyboardInterrupt:
        raise
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def run_managed_command(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    workspace_root: Path,
) -> CommandResult:
    resolved = build_managed_command_environment(
        workspace_root=workspace_root,
        command_cwd=cwd,
    )
    return run_command(argv, cwd=cwd, env=resolved.env)
