from __future__ import annotations

import importlib
import re
import shlex
from pathlib import Path

from taskledger.command_inventory import COMMAND_METADATA

ROOT = Path(__file__).resolve().parents[1]
DOC_PATHS = [
    ROOT / "README.md",
    ROOT / "API.md",
    ROOT / "AGENTS.md",
    *sorted((ROOT / "docs").glob("*.rst")),
    ROOT / "skills" / "taskledger" / "SKILL.md",
]
PUBLIC_API_MODULES = (
    "taskledger.api.project",
    "taskledger.api.tasks",
    "taskledger.api.plans",
    "taskledger.api.questions",
    "taskledger.api.task_runs",
    "taskledger.api.introductions",
    "taskledger.api.locks",
    "taskledger.api.handoff",
    "taskledger.api.releases",
    "taskledger.api.search",
)


def test_skill_is_single_file_without_examples_dir() -> None:
    skill_dir = ROOT / "skills" / "taskledger"
    assert (skill_dir / "SKILL.md").exists()
    assert not (skill_dir / "examples").exists()


def test_docs_directory_uses_rst_only() -> None:
    assert not list((ROOT / "docs").glob("*.md"))


def test_skills_are_not_packaged_resources() -> None:
    assert not (ROOT / "taskledger" / "skills").exists()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "skills/taskledger" not in pyproject


def test_api_docs_mentions_all_task_first_command_groups() -> None:
    api_text = (ROOT / "API.md").read_text(encoding="utf-8")
    for name in (
        "task",
        "plan",
        "question",
        "implement",
        "validate",
        "todo",
        "intro",
        "link",
        "file",
        "require",
        "release",
        "lock",
        "context",
        "handoff",
        "repair",
        "doctor",
    ):
        assert f"`{name}`" in api_text


def test_public_api_docs_match_module_exports() -> None:
    api_md = (ROOT / "API.md").read_text(encoding="utf-8")
    api_rst = (ROOT / "docs" / "api.rst").read_text(encoding="utf-8")
    for module_name in PUBLIC_API_MODULES:
        module = importlib.import_module(module_name)
        exported = getattr(module, "__all__", None)
        assert isinstance(exported, list), module_name
        assert all(isinstance(name, str) for name in exported), module_name
        for name in exported:
            assert f"`{name}`" in api_md, f"API.md missing {module_name}.{name}"
            assert f"``{name}``" in api_rst, (
                f"docs/api.rst missing {module_name}.{name}"
            )


def test_readme_mentions_root_alias_and_json_envelope() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "--root" in readme
    assert '"ok": true' in readme
    assert '"command": "status"' in readme


def test_skill_contains_strict_agent_protocol() -> None:
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")
    for heading in (
        "When to use this skill",
        "Never do these things",
        "Fresh context entry protocol",
        "CLI failure protocol",
        "Planning protocol",
        "Implementation protocol",
        "Validation protocol",
        "Required logging",
        "Failure handling",
        "Command examples",
    ):
        assert f"## {heading}" in skill
    assert "Do not implement before" in skill
    assert "taskledger context" in skill
    assert "Do not ask the user to run `taskledger question answer`" in skill
    assert "record the answers yourself" in skill
    assert "Stop issuing mutating taskledger commands" in skill
    assert "taskledger plan template --from-answers --file ./plan.md" in skill
    assert "taskledger question add-many" in skill
    assert "taskledger plan guidance" in skill
    assert "Treat it as advisory" in skill


def test_planning_guidance_docs_are_present() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    usage = (ROOT / "docs" / "usage.rst").read_text(encoding="utf-8")
    command_contract = (ROOT / "docs" / "command_contract.rst").read_text(
        encoding="utf-8"
    )
    api_md = (ROOT / "API.md").read_text(encoding="utf-8")
    api_rst = (ROOT / "docs" / "api.rst").read_text(encoding="utf-8")

    assert "prompt_profiles.planning" in readme
    assert "taskledger plan guidance" in usage
    assert "required_question_topics" in usage
    assert "Plan guidance command" in command_contract
    assert "has_project_guidance" in command_contract
    assert 'plan_guidance(Path.cwd(), "task-0001")' in api_md
    assert 'plan_guidance(Path.cwd(), "task-0001")' in api_rst


def test_transfer_docs_cover_project_identity_and_dry_run() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    usage = (ROOT / "docs" / "usage.rst").read_text(encoding="utf-8")
    command_contract = (ROOT / "docs" / "command_contract.rst").read_text(
        encoding="utf-8"
    )
    transfer = (ROOT / "docs" / "transfer.rst").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")

    assert "project_name" in readme
    assert "taskledger-export-{project_slug}-{ledger_ref}-{timestamp}.tar.gz" in readme
    assert "--project-name" in usage
    assert "taskledger import ./taskledger-transfer.tar.gz --dry-run" in usage
    assert "manifest.project.name" in command_contract
    assert "project.uuid" in transfer
    assert "taskledger import --dry-run" in transfer
    assert "taskledger import ./taskledger-transfer.tar.gz --dry-run" in skill


def test_docs_do_not_reference_removed_commands() -> None:
    forbidden = [
        "taskledger repo ",
        "taskledger runs ",
        "taskledger context save",
        "taskengine context run",
        "runtildone --harness",
        "handoff-protocol",
        "taskledger todo toggle",
        "taskledger task new",
        "taskledger task clear-active",
        "taskledger implement add-change",
        "taskledger validate add-check",
        "taskledger file link",
        "taskledger file unlink",
        "taskledger link link",
        "taskledger link unlink",
        "taskledger actor whoami --json",
    ]
    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{path}: {needle}"


def test_readme_links_exist() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", readme):
        if "://" in target or target.startswith("#"):
            continue
        local_target = target.split("#", 1)[0]
        if not local_target:
            continue
        assert (ROOT / local_target).exists(), target


def test_readme_skill_path_matches_repository() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "skills/taskledger/SKILL.md" in readme
    assert "taskledger/skills/taskledger/SKILL.md" not in readme


def test_skill_uses_only_canonical_handoff_group() -> None:
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")
    assert "handoff-protocol" not in skill


def test_command_examples_reference_registered_commands() -> None:
    for path in DOC_PATHS:
        for line_number, command_line in _taskledger_example_lines(path):
            tokens = shlex.split(command_line, comments=True)
            command = _command_key(tokens)
            if command is None:
                continue
            assert command in COMMAND_METADATA, f"{path}:{line_number}: {command_line}"


def _taskledger_example_lines(path: Path) -> list[tuple[int, str]]:
    examples: list[tuple[int, str]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("$ "):
            stripped = stripped[2:].strip()
        if not stripped.startswith("taskledger "):
            continue
        if any(marker in stripped for marker in ("...", "<", ">", "QUESTION_ID")):
            continue
        examples.append((line_number, stripped))
    return examples


def _command_key(tokens: list[str]) -> str | None:
    if not tokens or tokens[0] != "taskledger":
        return None
    remaining = tokens[1:]
    while remaining and remaining[0].startswith("-"):
        option = remaining.pop(0)
        if option in {"--cwd", "--root"} and remaining:
            remaining.pop(0)
    if not remaining:
        return None
    first = remaining[0]
    group_commands = {key.split(" ", 1)[0] for key in COMMAND_METADATA if " " in key}
    if first not in group_commands:
        return first
    if len(remaining) == 1:
        return first
    return f"{first} {remaining[1]}"
