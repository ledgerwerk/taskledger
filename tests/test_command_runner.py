from __future__ import annotations

import os
import sys

import pytest

from taskledger.services.command_runner import (
    _virtualenv_scripts_dir,
    build_managed_command_environment,
    run_command,
    run_managed_command,
)


# specmason: req=REQ-0012 ac=AC-0117
def test_run_command_preserves_nonzero_python_exit_code(tmp_path):
    result = run_command(
        (sys.executable, "-c", "raise SystemExit(3)"),
        cwd=tmp_path,
    )

    assert result.returncode == 3
    assert result.stdout == ""
    assert result.stderr == ""


# specmason: req=REQ-0012 ac=AC-0118
def test_run_command_preserves_zero_python_exit_code(tmp_path):
    result = run_command(
        (sys.executable, "-c", "pass"),
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


# specmason: req=REQ-0012 ac=AC-0118
def test_run_command_propagates_parent_keyboard_interrupt(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(KeyboardInterrupt):
        run_command((sys.executable, "-c", "pass"), cwd=tmp_path)


def _make_virtualenv(root, *, with_config=True, executable=True):
    scripts_dir = _virtualenv_scripts_dir(root)
    scripts_dir.mkdir(parents=True)
    if with_config:
        (root / "pyvenv.cfg").write_text("home = test\n")
    if executable:
        python = scripts_dir / ("python.exe" if os.name == "nt" else "python")
        python.write_text("#!/bin/sh\nprintf 'WORKSPACE_PYTHON\\n'\n")
        python.chmod(0o755)
    return scripts_dir


def test_managed_environment_prefers_inherited_virtualenv(tmp_path):
    active = tmp_path / "active"
    active_scripts = _make_virtualenv(active, with_config=False)
    local = tmp_path / ".venv"
    _make_virtualenv(local)
    base = {"PATH": f"{local / 'bin'}:/usr/bin", "PYTHONHOME": "/global"}
    resolved = build_managed_command_environment(
        workspace_root=tmp_path,
        command_cwd=tmp_path,
        environ={**base, "VIRTUAL_ENV": str(active)},
    )

    assert resolved.source == "inherited-virtualenv"
    assert resolved.virtualenv == active
    assert resolved.env["VIRTUAL_ENV"] == str(active)
    assert resolved.env["PATH"].split(os.pathsep)[0] == str(active_scripts)
    assert resolved.env["PYTHONHOME"] == "/global"


def test_managed_environment_prefers_command_cwd_over_workspace(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    _make_virtualenv(tmp_path / ".venv")
    nested_scripts = _make_virtualenv(nested / ".venv")

    resolved = build_managed_command_environment(
        workspace_root=tmp_path,
        command_cwd=nested,
        environ={"PATH": "/global", "PYTHONPATH": "project"},
    )

    assert resolved.source == "command-cwd-.venv"
    assert resolved.env["PATH"].split(os.pathsep)[0] == str(nested_scripts)
    assert resolved.env["VIRTUAL_ENV"] == str(nested / ".venv")
    assert "PYTHONHOME" not in resolved.env
    assert resolved.env["PYTHONPATH"] == "project"


def test_managed_environment_uses_venv_fallback(tmp_path):
    scripts_dir = _make_virtualenv(tmp_path / "venv")

    resolved = build_managed_command_environment(
        workspace_root=tmp_path,
        command_cwd=tmp_path,
        environ={"PATH": "/global"},
    )

    assert resolved.source == "command-cwd-venv"
    assert resolved.env["PATH"].split(os.pathsep)[0] == str(scripts_dir)


@pytest.mark.parametrize("with_config, executable", [(False, True), (True, False)])
def test_invalid_local_virtualenv_is_ignored(tmp_path, with_config, executable):
    _make_virtualenv(tmp_path / ".venv", with_config=with_config, executable=executable)
    base = {"PATH": "/global", "PYTHONPATH": "project"}

    resolved = build_managed_command_environment(
        workspace_root=tmp_path,
        command_cwd=tmp_path,
        environ=base,
    )

    assert resolved.source == "inherited"
    assert resolved.virtualenv is None
    assert resolved.env == base


def test_managed_environment_deduplicates_scripts_path_and_does_not_mutate_input(
    tmp_path,
):
    scripts_dir = _make_virtualenv(tmp_path / ".venv")
    base = {
        "PATH": os.pathsep.join(["/global", str(scripts_dir), "/other"]),
        "PYTHONHOME": "/global/python",
    }
    original = dict(base)

    resolved = build_managed_command_environment(
        workspace_root=tmp_path,
        command_cwd=tmp_path,
        environ=base,
    )

    entries = resolved.env["PATH"].split(os.pathsep)
    assert entries[0] == str(scripts_dir)
    assert entries.count(str(scripts_dir)) == 1
    assert "PYTHONHOME" not in resolved.env
    assert base == original


def test_managed_environment_falls_back_to_inherited_environment(tmp_path):
    base = {"PATH": "/global", "PYTHONPATH": "project", "VIRTUAL_ENV": "missing"}

    resolved = build_managed_command_environment(
        workspace_root=tmp_path,
        command_cwd=tmp_path,
        environ=base,
    )

    assert resolved.source == "inherited"
    assert resolved.env == base


@pytest.mark.skipif(os.name == "nt", reason="uses POSIX executable scripts")
def test_managed_runner_prefers_workspace_python_over_global_python(
    tmp_path,
    monkeypatch,
):
    global_bin = tmp_path / "global-bin"
    global_bin.mkdir()
    global_python = global_bin / "python"
    global_python.write_text("#!/bin/sh\nprintf 'NIX_PYTHON\\n'\n")
    global_python.chmod(0o755)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _make_virtualenv(workspace / ".venv")

    monkeypatch.setenv("PATH", str(global_bin))
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    result = run_managed_command(
        ("python", "-m", "pytest"),
        cwd=workspace,
        workspace_root=workspace,
    )

    assert result.returncode == 0
    assert result.stdout == "WORKSPACE_PYTHON\n"


@pytest.mark.skipif(os.name == "nt", reason="uses POSIX executable scripts")
def test_low_level_runner_does_not_activate_workspace_virtualenv(tmp_path):
    global_bin = tmp_path / "global-bin"
    global_bin.mkdir()
    global_python = global_bin / "python"
    global_python.write_text("#!/bin/sh\nprintf 'NIX_PYTHON\\n'\n")
    global_python.chmod(0o755)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _make_virtualenv(workspace / ".venv")

    result = run_command(
        ("python",),
        cwd=workspace,
        env={"PATH": str(global_bin)},
    )

    assert result.returncode == 0
    assert result.stdout == "NIX_PYTHON\n"
