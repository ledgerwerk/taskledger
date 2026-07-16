from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from taskledger.cli import app
from taskledger.errors import LaunchError
from taskledger.services.doctor import inspect_v2_project
from taskledger.storage.ledger_config import load_ledger_identity
from taskledger.storage.meta import StorageMeta
from taskledger.storage.paths import resolve_project_paths
from taskledger.storage.project_config import (
    AgentLoggingConfig,
    EventLoggingConfig,
    ProjectConfig,
    PromptProfile,
    load_project_config_overrides,
    merge_project_config,
    render_default_taskledger_toml,
)


def _make_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


runner = _make_runner()


def _write_storage_root(path: Path) -> None:
    for directory in (
        path,
        path / "intros",
        path / "tasks",
        path / "events",
        path / "indexes",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    for index_name in ("active_locks.json", "dependencies.json", "introductions.json"):
        (path / "indexes" / index_name).write_text("[]\n", encoding="utf-8")
    meta = StorageMeta(created_with_taskledger="test")
    (path / "storage.yaml").write_text(
        yaml.safe_dump(meta.to_dict(), sort_keys=False), encoding="utf-8"
    )


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-init-writes-root-taskledger-toml-and-default-storage
def test_init_writes_canonical_sibling_storage(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["--root", str(tmp_path), "init", "--create-sibling-store"]
    )
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / ".ledger" / "ledger.toml").exists()
    assert (tmp_path / ".ledger" / "task" / "config.toml").exists()
    assert (
        tmp_path.parent / "ledger" / "task" / "taskledger" / "storage.yaml"
    ).exists()
    assert not (tmp_path / ".ledger" / "task" / "taskledger").exists()


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-init-writes-project-name-from-workspace-basename
def test_init_writes_project_name_from_workspace_basename(tmp_path: Path) -> None:
    workspace = tmp_path / "odoo17-addon"
    workspace.mkdir()
    result = runner.invoke(
        app, ["--root", str(workspace), "init", "--create-sibling-store"]
    )
    assert result.exit_code == 0, result.stdout
    manifest_text = (workspace / ".ledger" / "ledger.toml").read_text(encoding="utf-8")
    assert 'name = "odoo17-addon"' in manifest_text
    json_result = runner.invoke(app, ["--root", str(workspace), "--json", "init"])
    assert json_result.exit_code == 0, json_result.stdout
    payload = json.loads(json_result.stdout)
    assert payload["result"]["project_name"] == "odoo17-addon"


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-init-project-name-option-overrides-basename
def test_init_project_name_option_overrides_basename(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "init",
            "--create-sibling-store",
            "--project-name",
            "Odoo 17 Addons",
        ],
    )
    assert result.exit_code == 0, result.stdout
    manifest_text = (workspace / ".ledger" / "ledger.toml").read_text(encoding="utf-8")
    assert 'name = "Odoo 17 Addons"' in manifest_text


@pytest.mark.specweave(
    feature=("specs/behavior/features/project_root_config/project-root-config.feature"),
    scenario=(
        "@bdd-project-root-config-init-with-external-taskledger-dir-uses-"
        "directory-directly"
    ),
)
def test_init_with_external_taskledger_dir_uses_directory_directly(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    storage = tmp_path / "cloud" / "taskledger" / "repo"
    workspace.mkdir()

    result = runner.invoke(
        app,
        ["--root", str(workspace), "init", "--taskledger-dir", str(storage)],
    )

    assert result.exit_code == 0, result.stdout
    config_text = (workspace / "taskledger.toml").read_text(encoding="utf-8")
    assert storage.as_posix() in config_text
    assert (storage / "storage.yaml").exists()
    assert (storage / "ledgers" / "main" / "tasks").is_dir()
    assert not (storage / ".taskledger").exists()
    assert not (workspace / ".taskledger").exists()


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-task-create-uses-configured-external-storage
def test_task_create_uses_configured_external_storage(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    storage = tmp_path / "cloud" / "taskledger" / "repo"
    workspace.mkdir()

    init_result = runner.invoke(
        app,
        ["--root", str(workspace), "init", "--taskledger-dir", str(storage)],
    )
    assert init_result.exit_code == 0, init_result.stdout

    result = runner.invoke(
        app,
        [
            "--root",
            str(workspace),
            "task",
            "create",
            "External storage task",
            "--description",
            "Write task data outside the repo.",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert any((storage / "ledgers" / "main" / "tasks").glob("task-*"))
    assert not (workspace / ".taskledger" / "tasks").exists()


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-relative-storage-resolves-from-config
def test_relative_taskledger_dir_is_relative_to_config_path(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "taskledger.toml").write_text(
        'config_version = 1\ntaskledger_dir = "../state/repo"\n',
        encoding="utf-8",
    )

    paths = resolve_project_paths(workspace)

    assert paths.taskledger_dir == (tmp_path / "state" / "repo").resolve()


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-cli-discovers-taskledger-toml-from-subdirectory
def test_cli_discovers_taskledger_toml_from_subdirectory(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "repo"
    subdir = workspace / "src" / "pkg"
    subdir.mkdir(parents=True)
    assert (
        runner.invoke(
            app,
            ["--root", str(workspace), "init", "--create-sibling-store"],
        ).exit_code
        == 0
    )

    monkeypatch.chdir(subdir)
    result = runner.invoke(app, ["--json", "status"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["workspace_root"] == str(workspace)
    assert payload["result"]["config_path"] == str(
        workspace / ".ledger" / "task" / "config.toml"
    )


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-legacy-config-fallbacks-remain-readable
def test_legacy_dot_taskledger_without_root_config_still_resolves(
    tmp_path: Path,
) -> None:
    _write_storage_root(tmp_path / ".taskledger")

    paths = resolve_project_paths(tmp_path)

    assert paths.taskledger_dir == (tmp_path / ".taskledger").resolve()
    assert paths.config_path == tmp_path / "taskledger.toml"


def test_legacy_project_toml_is_used_as_fallback_config(tmp_path: Path) -> None:
    legacy_dir = tmp_path / ".taskledger"
    _write_storage_root(legacy_dir)
    (legacy_dir / "project.toml").write_text(
        "default_source_max_chars = 42\n", encoding="utf-8"
    )

    paths = resolve_project_paths(tmp_path)

    assert paths.config_path == legacy_dir / "project.toml"
    assert load_project_config_overrides(paths)["default_source_max_chars"] == 42


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-invalid-taskledger-toml-returns-json-error
def test_invalid_taskledger_toml_returns_json_error(tmp_path: Path) -> None:
    (tmp_path / "taskledger.toml").write_text(
        "taskledger_dir = [1, 2, 3]\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["--root", str(tmp_path), "--json", "status"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "taskledger_dir" in payload["error"]["message"]


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-dot-taskledger-toml-wins-and-doctor-warns
def test_dot_taskledger_toml_wins_and_doctor_warns(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    hidden_storage = tmp_path / "state-hidden"
    canonical_storage = tmp_path / "state-canonical"
    _write_storage_root(hidden_storage)
    _write_storage_root(canonical_storage)
    (workspace / ".taskledger.toml").write_text(
        f'config_version = 1\ntaskledger_dir = "{hidden_storage.as_posix()}"\n',
        encoding="utf-8",
    )
    (workspace / "taskledger.toml").write_text(
        f'config_version = 1\ntaskledger_dir = "{canonical_storage.as_posix()}"\n',
        encoding="utf-8",
    )

    paths = resolve_project_paths(workspace)
    doctor = inspect_v2_project(workspace)

    assert paths.taskledger_dir == hidden_storage.resolve()
    assert any(
        "Both taskledger.toml and .taskledger.toml exist" in warning
        for warning in doctor["warnings"]
    )


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-doctor-warns-on-legacy-project-toml
def test_doctor_warns_on_legacy_project_toml(tmp_path: Path) -> None:
    legacy_dir = tmp_path / ".taskledger"
    _write_storage_root(legacy_dir)
    (legacy_dir / "project.toml").write_text("default_source_max_chars = 99\n")

    doctor = inspect_v2_project(tmp_path)

    assert any("Legacy config location" in warning for warning in doctor["warnings"])


# --- prompt_profile tests ---


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-merge-project-config-with-valid-prompt-profile
def test_merge_project_config_with_valid_prompt_profile() -> None:
    overrides = {
        "prompt_profiles": {
            "planning": {
                "profile": "strict",
                "question_policy": "minimal",
                "max_required_questions": 3,
                "min_acceptance_criteria": 2,
                "todo_granularity": "atomic",
                "require_files": False,
                "require_test_commands": False,
                "require_expected_outputs": False,
                "require_validation_hints": False,
                "plan_body_detail": "terse",
                "required_question_topics": ["scope", "approach"],
                "extra_guidance": "Always include a migration plan.",
            }
        }
    }
    config = merge_project_config(overrides)
    assert config.prompt_profile is not None
    p = config.prompt_profile
    assert p.name == "planning"
    assert p.profile == "strict"
    assert p.question_policy == "minimal"
    assert p.max_required_questions == 3
    assert p.min_acceptance_criteria == 2
    assert p.todo_granularity == "atomic"
    assert p.require_files is False
    assert p.require_test_commands is False
    assert p.require_expected_outputs is False
    assert p.require_validation_hints is False
    assert p.plan_body_detail == "terse"
    assert p.required_question_topics == ("scope", "approach")
    assert p.extra_guidance == "Always include a migration plan."


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-merge-project-config-no-prompt-profile-is-none
def test_merge_project_config_no_prompt_profile_is_none() -> None:
    config = merge_project_config({})
    assert config.prompt_profile is None


@pytest.mark.specweave(
    feature=("specs/behavior/features/project_root_config/project-root-config.feature"),
    scenario=(
        "@bdd-project-root-config-merge-project-config-partial-prompt-profile-"
        "uses-defaults"
    ),
)
def test_merge_project_config_partial_prompt_profile_uses_defaults() -> None:
    overrides = {
        "prompt_profiles": {
            "planning": {"profile": "compact", "max_required_questions": 2}
        }
    }
    config = merge_project_config(overrides)
    assert config.prompt_profile is not None
    p = config.prompt_profile
    assert p.profile == "compact"
    assert p.max_required_questions == 2
    assert p.question_policy == "ask_when_missing"
    assert p.todo_granularity == "implementation_steps"
    assert p.require_files is True


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-merge-project-config-preserves-base-prompt-profile
def test_merge_project_config_preserves_base_prompt_profile() -> None:
    base = ProjectConfig()
    overrides: dict[str, object] = {}
    config = merge_project_config(overrides, base=base)
    assert config.prompt_profile is None
    # base with a prompt profile
    base_with = ProjectConfig(
        prompt_profile=PromptProfile(
            name="planning",
            profile="strict",
            question_policy="minimal",
        )
    )
    config = merge_project_config(overrides, base=base_with)
    assert config.prompt_profile is not None
    assert config.prompt_profile.profile == "strict"
    assert config.prompt_profile.question_policy == "minimal"


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-invalid-prompt-profile-is-rejected
def test_validate_prompt_profile_rejects_unknown_keys() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    data: dict[str, object] = {
        "prompt_profiles": {
            "planning": {
                "profile": "balanced",
                "unknown_field": "bad",
            }
        }
    }
    with pytest.raises(LaunchError) as exc:
        _validate_project_config_overrides(data, Path("test.toml"))
    assert "unknown" in str(exc.value).lower()


def test_validate_prompt_profile_rejects_invalid_profile_enum() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    data: dict[str, object] = {"prompt_profiles": {"planning": {"profile": "nonsense"}}}
    with pytest.raises(LaunchError) as exc:
        _validate_project_config_overrides(data, Path("test.toml"))
    assert "profile" in str(exc.value).lower()


def test_validate_prompt_profile_rejects_invalid_question_policy() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    data: dict[str, object] = {
        "prompt_profiles": {"planning": {"question_policy": "ask_always"}}
    }
    with pytest.raises(LaunchError) as exc:
        _validate_project_config_overrides(data, Path("test.toml"))
    assert "question_policy" in str(exc.value).lower()


def test_validate_prompt_profile_rejects_invalid_todo_granularity() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    data: dict[str, object] = {
        "prompt_profiles": {"planning": {"todo_granularity": "mega"}}
    }
    with pytest.raises(LaunchError) as exc:
        _validate_project_config_overrides(data, Path("test.toml"))
    assert "todo_granularity" in str(exc.value).lower()


def test_validate_prompt_profile_rejects_invalid_plan_body_detail() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    data: dict[str, object] = {
        "prompt_profiles": {"planning": {"plan_body_detail": "verbose"}}
    }
    with pytest.raises(LaunchError) as exc:
        _validate_project_config_overrides(data, Path("test.toml"))
    assert "plan_body_detail" in str(exc.value).lower()


def test_validate_prompt_profile_rejects_non_integer_max_questions() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    data: dict[str, object] = {
        "prompt_profiles": {"planning": {"max_required_questions": "five"}}
    }
    with pytest.raises(LaunchError) as exc:
        _validate_project_config_overrides(data, Path("test.toml"))
    assert "max_required_questions" in str(exc.value).lower()


def test_validate_prompt_profile_rejects_non_boolean_field() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    data: dict[str, object] = {
        "prompt_profiles": {"planning": {"require_files": "yes"}}
    }
    with pytest.raises(LaunchError) as exc:
        _validate_project_config_overrides(data, Path("test.toml"))
    assert "require_files" in str(exc.value).lower()


def test_validate_prompt_profile_rejects_excessive_extra_guidance() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    data: dict[str, object] = {
        "prompt_profiles": {"planning": {"extra_guidance": "x" * 5000}}
    }
    with pytest.raises(LaunchError) as exc:
        _validate_project_config_overrides(data, Path("test.toml"))
    assert "extra_guidance" in str(exc.value).lower()


def test_validate_prompt_profile_rejects_non_list_topics() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    data: dict[str, object] = {
        "prompt_profiles": {"planning": {"required_question_topics": "just one string"}}
    }
    with pytest.raises(LaunchError) as exc:
        _validate_project_config_overrides(data, Path("test.toml"))
    assert "required_question_topics" in str(exc.value).lower()


def test_validate_prompt_profile_rejects_negative_integer() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    data: dict[str, object] = {
        "prompt_profiles": {"planning": {"max_required_questions": 0}}
    }
    with pytest.raises(LaunchError) as exc:
        _validate_project_config_overrides(data, Path("test.toml"))
    assert "positive" in str(exc.value).lower()


def test_prompt_profile_to_dict() -> None:
    p = PromptProfile(
        name="planning",
        profile="strict",
        question_policy="minimal",
        max_required_questions=3,
        min_acceptance_criteria=2,
        todo_granularity="atomic",
        require_files=False,
        require_test_commands=False,
        require_expected_outputs=False,
        require_validation_hints=False,
        plan_body_detail="terse",
        required_question_topics=("scope",),
        extra_guidance="Test guidance.",
    )
    d = p.to_dict()
    assert d["name"] == "planning"
    assert d["profile"] == "strict"
    assert d["question_policy"] == "minimal"
    assert d["max_required_questions"] == 3
    assert d["min_acceptance_criteria"] == 2
    assert d["todo_granularity"] == "atomic"
    assert d["require_files"] is False
    assert d["required_question_topics"] == ["scope"]
    assert d["extra_guidance"] == "Test guidance."


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-merge-project-config-with-agent-logging-override
def test_merge_project_config_with_agent_logging_override() -> None:
    config = merge_project_config(
        {
            "agent_logging": {
                "enabled": True,
                "max_inline_chars": 1234,
                "redact_patterns": ["(?i)token=\\S+"],
            }
        }
    )
    assert config.agent_logging.enabled is True
    assert config.agent_logging.max_inline_chars == 1234
    assert config.agent_logging.redact_patterns == ("(?i)token=\\S+",)


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-merge-project-config-preserves-base-agent-logging
def test_merge_project_config_preserves_base_agent_logging() -> None:
    base = ProjectConfig(
        agent_logging=AgentLoggingConfig(
            enabled=True,
            max_inline_chars=2048,
        )
    )
    config = merge_project_config({}, base=base)
    assert config.agent_logging.enabled is True
    assert config.agent_logging.max_inline_chars == 2048


@pytest.mark.specweave(
    feature=("specs/behavior/features/project_root_config/project-root-config.feature"),
    scenario=(
        "@bdd-project-root-config-default-taskledger-toml-includes-commented-"
        "planning-guidance"
    ),
)
def test_default_taskledger_toml_includes_commented_planning_guidance() -> None:
    rendered = render_default_taskledger_toml()
    assert "[ledger]" in rendered
    assert 'code = "tl"' in rendered
    assert 'name = "taskledger"' in rendered
    assert "# [prompt_profiles.planning]" in rendered
    assert '# profile = "balanced"' in rendered
    assert "# require_files = true" in rendered
    assert (
        '# extra_guidance = "Mention docs and validation evidence in every plan."'
        in rendered
    )


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-invalid-project-name-is-rejected
def test_validate_project_name_rejects_non_string() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    with pytest.raises(LaunchError, match="project_name"):
        _validate_project_config_overrides({"project_name": 123}, Path("test.toml"))


def test_validate_project_name_rejects_blank() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    with pytest.raises(LaunchError, match="project_name"):
        _validate_project_config_overrides({"project_name": "   "}, Path("test.toml"))


def test_validate_project_name_rejects_newline() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    with pytest.raises(LaunchError, match="project_name"):
        _validate_project_config_overrides(
            {"project_name": "Taskledger\nRepo"},
            Path("test.toml"),
        )


@pytest.mark.specweave(
    feature=("specs/behavior/features/project_root_config/project-root-config.feature"),
    scenario=(
        "@bdd-project-root-config-render-default-taskledger-toml-includes-"
        "project-name-when-given"
    ),
)
def test_render_default_taskledger_toml_includes_project_name_when_given() -> None:
    rendered = render_default_taskledger_toml(
        project_uuid="u",
        project_name="taskledger",
    )
    assert 'project_name = "taskledger"' in rendered


def test_validate_project_config_allows_ledger_table() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    _validate_project_config_overrides(
        {"ledger": {"code": "TL", "name": "Task Ledger"}},
        Path("taskledger.toml"),
    )


def test_validate_project_config_rejects_unknown_ledger_keys() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    with pytest.raises(LaunchError, match="Unsupported \\[ledger\\] key"):
        _validate_project_config_overrides(
            {"ledger": {"code": "tl", "name": "taskledger", "extra": "x"}},
            Path("taskledger.toml"),
        )


def test_validate_project_config_rejects_invalid_ledger_code() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    with pytest.raises(LaunchError, match="ledger.code"):
        _validate_project_config_overrides(
            {"ledger": {"code": "tl_main", "name": "taskledger"}},
            Path("taskledger.toml"),
        )


def test_load_ledger_identity_defaults_when_table_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "taskledger.toml"
    config_path.write_text('config_version = 2\ntaskledger_dir = ".taskledger"\n')
    identity = load_ledger_identity(config_path)
    assert identity.code == "tl"
    assert identity.name == "taskledger"


def test_load_ledger_identity_normalizes_uppercase_code(tmp_path: Path) -> None:
    config_path = tmp_path / "taskledger.toml"
    config_path.write_text(
        "config_version = 2\n"
        'taskledger_dir = ".taskledger"\n'
        "[ledger]\n"
        'code = "TL"\n'
        'name = "Task Ledger"\n'
    )
    identity = load_ledger_identity(config_path)
    assert identity.code == "tl"
    assert identity.name == "Task Ledger"


def test_validate_sync_git_allows_valid_config() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    data: dict[str, object] = {
        "sync": {
            "git": {
                "repo": "../taskledger-state",
                "project_path": "project-a",
                "remote": "origin",
                "branch": "main",
                "allow_active_locks": False,
                "hooks": True,
            }
        }
    }
    _validate_project_config_overrides(data, Path("taskledger.toml"))


def test_validate_sync_git_rejects_unknown_key() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    with pytest.raises(LaunchError, match="sync.git"):
        _validate_project_config_overrides(
            {"sync": {"git": {"unknown": "value"}}},
            Path("taskledger.toml"),
        )


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-sync-git-path-cannot-escape-project
def test_validate_sync_git_rejects_absolute_project_path() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    with pytest.raises(LaunchError, match="project_path"):
        _validate_project_config_overrides(
            {"sync": {"git": {"project_path": "/abs/path"}}},
            Path("taskledger.toml"),
        )


def test_validate_sync_git_rejects_parent_path_escape() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    with pytest.raises(LaunchError, match="project_path"):
        _validate_project_config_overrides(
            {"sync": {"git": {"project_path": "../escape"}}},
            Path("taskledger.toml"),
        )


# -- event_logging config tests --


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-action-logging-enabled-by-default
def test_action_logging_enabled_by_default() -> None:
    config = merge_project_config({})
    assert config.event_logging.enabled is True


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-merge-project-config-can-disable-action-logging
def test_merge_project_config_can_disable_action_logging() -> None:
    config = merge_project_config({"event_logging": {"enabled": False}})
    assert config.event_logging.enabled is False


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-merge-project-config-preserves-base-event-logging
def test_merge_project_config_preserves_base_event_logging() -> None:
    base = ProjectConfig(event_logging=EventLoggingConfig(enabled=True))
    config = merge_project_config({}, base=base)
    assert config.event_logging.enabled is True


@pytest.mark.specweave(
    feature=("specs/behavior/features/project_root_config/project-root-config.feature"),
    scenario=(
        "@bdd-project-root-config-default-taskledger-toml-includes-commented-"
        "event-logging"
    ),
)
def test_default_taskledger_toml_includes_commented_event_logging() -> None:
    rendered = render_default_taskledger_toml()
    assert "# [event_logging]" in rendered
    assert "# enabled = true" in rendered


# sw: f=specs/behavior/features/project_root_config/project-root-config.feature
# sw: s=@bdd-project-root-config-invalid-event-logging-config-is-rejected
def test_validate_event_logging_rejects_non_table() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    with pytest.raises(LaunchError, match="event_logging.*table"):
        _validate_project_config_overrides(
            {"event_logging": True},
            Path("taskledger.toml"),
        )


def test_validate_event_logging_rejects_non_boolean_enabled() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    with pytest.raises(LaunchError, match="event_logging.enabled.*boolean"):
        _validate_project_config_overrides(
            {"event_logging": {"enabled": "yes"}},
            Path("taskledger.toml"),
        )


def test_validate_event_logging_rejects_unknown_keys() -> None:
    from taskledger.storage.project_config import _validate_project_config_overrides

    with pytest.raises(LaunchError, match="Unknown event_logging"):
        _validate_project_config_overrides(
            {"event_logging": {"unknown": True}},
            Path("taskledger.toml"),
        )
