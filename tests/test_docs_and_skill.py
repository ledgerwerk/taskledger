from __future__ import annotations

import importlib
import re
import shlex
from pathlib import Path

import pytest

from taskledger.command_inventory import COMMAND_METADATA

ROOT = Path(__file__).resolve().parents[1]
DOC_PATHS = [
    ROOT / "README.md",
    ROOT / "API.md",
    ROOT / "AGENTS.md",
    *sorted((ROOT / "docs").glob("*.md")),
    ROOT / "skills" / "taskledger" / "SKILL.md",
]
PUBLIC_API_MODULES = (
    "taskledger.api.project",
    "taskledger.api.tasks",
    "taskledger.api.plans",
    "taskledger.api.questions",
    "taskledger.api.task_runs",
    "taskledger.api.reviews",
    "taskledger.api.introductions",
    "taskledger.api.locks",
    "taskledger.api.handoff",
    "taskledger.api.releases",
    "taskledger.api.storage",
    "taskledger.api.sync",
    "taskledger.api.search",
)


def test_skill_is_single_file_without_examples_dir() -> None:
    skill_dir = ROOT / "skills" / "taskledger"
    assert (skill_dir / "SKILL.md").exists()
    assert not (skill_dir / "examples").exists()


def test_docs_directory_uses_markdown_only() -> None:
    assert not list((ROOT / "docs").glob("*.rst"))


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-skills-are-not-packaged-resources
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
        "review",
        "todo",
        "intro",
        "link",
        "file",
        "require",
        "release",
        "config",
        "lock",
        "context",
        "handoff",
        "repair",
        "doctor",
    ):
        assert f"`{name}`" in api_text


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-public-api-docs-match-module-exports
def test_public_api_docs_match_module_exports() -> None:
    api_text = (ROOT / "API.md").read_text(encoding="utf-8")
    api_md = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
    for module_name in PUBLIC_API_MODULES:
        module = importlib.import_module(module_name)
        exported = getattr(module, "__all__", None)
        assert isinstance(exported, list), module_name
        assert all(isinstance(name, str) for name in exported), module_name
        for name in exported:
            assert f"`{name}`" in api_text, f"API.md missing {module_name}.{name}"
            assert f"`{name}`" in api_md, f"docs/api.md missing {module_name}.{name}"


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-readme-mentions-root-alias-and-json-envelope
def test_readme_mentions_root_alias_and_json_envelope() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "--root" in readme
    assert '"ok": true' in readme
    assert '"command": "status"' in readme


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-skill-contains-strict-agent-protocol
def test_skill_contains_strict_agent_protocol() -> None:
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")
    for heading in (
        "When to use this skill",
        "Never do these things",
        "Fresh context entry protocol",
        "User-requested review protocol",
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
    assert "taskledger --json release show 0.4.1" in skill
    assert "task dossier" in skill
    assert "## Release boundary protocol" in skill
    assert "Do not create changelog entries or edit" in skill


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-docs-define-agent-golden-path-and-advanced-surfaces
def test_docs_define_agent_golden_path_and_advanced_surfaces() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    public_surface = (ROOT / "docs" / "public_surface.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")

    normal_plan_path = (
        "plan start -> plan template -> plan upsert -> plan lint -> plan accept"
    )
    for text in (readme, public_surface, skill):
        assert normal_plan_path in text
        assert "handoff create" in text
        assert "storage" in text
        assert "advanced" in text.lower()

    assert "44 top-level CLI entries" in public_surface
    assert "41 registered command groups" not in public_surface
    assert "ledger fork/switch/adopt" in public_surface
    assert "search`/`grep`/`symbols`/`deps`" in public_surface
    assert "## Non-goals" in readme


def test_skill_has_single_repair_warning() -> None:
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")
    assert skill.count("Do not use repair commands") == 1


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-read-report-export-terminology-is-consolidated
def test_read_report_export_terminology_is_consolidated() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    usage = (ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
    public_surface = (ROOT / "docs" / "public_surface.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")

    for text in (readme, usage, public_surface, skill):
        assert "task dossier" in text
        assert "advanced/compatibility" in text
        assert "context" in text
        assert "handoff show" in text

    assert "context`: canonical fresh continuation context" in usage
    assert "task export" in public_surface
    assert "task transcript" in public_surface


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-planning-guidance-docs-are-present
def test_planning_guidance_docs_are_present() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    usage = (ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
    command_contract = (ROOT / "docs" / "command_contract.md").read_text(
        encoding="utf-8"
    )
    api_md = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")

    assert "prompt_profiles.planning" in readme
    assert "taskledger plan guidance" in usage
    assert "required_question_topics" in usage
    assert "Plan guidance command" in command_contract
    assert "has_project_guidance" in command_contract
    assert 'plan_guidance(Path.cwd(), "task-0001")' in api_md
    assert 'plan_guidance(Path.cwd(), "task-0001")' in api_md


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-plan-revision-docs-and-skill-rules-are-present
def test_plan_revision_docs_and_skill_rules_are_present() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    usage = (ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
    command_contract = (ROOT / "docs" / "command_contract.md").read_text(
        encoding="utf-8"
    )
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")

    assert "taskledger plan export --version latest --file ./plan.md" in readme
    assert "taskledger plan review --version" in readme
    assert "taskledger plan amend" in usage
    assert "taskledger plan review --version" in usage
    assert "Never edit `.taskledger/` files directly." in skill
    assert "taskledger plan review --version N" in skill
    assert "taskledger plan revise" in skill
    assert "taskledger plan export" in command_contract
    assert "taskledger plan review" in command_contract


@pytest.mark.specweave(
    feature=("specs/behavior/features/docs_and_skill/docs-and-skill.feature"),
    scenario=(
        "@bdd-docs-and-skill-worker-pipeline-docs-cover-guided-next-action-"
        "and-worker-refs"
    ),
)
def test_worker_pipeline_docs_cover_guided_next_action_and_worker_refs() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    usage = (ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
    command_contract = (ROOT / "docs" / "command_contract.md").read_text(
        encoding="utf-8"
    )
    api_md = (ROOT / "API.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")

    assert "test_command_policy" in readme
    assert "taskledger next-action" in readme
    assert "required_output" in usage
    assert "worker_pipeline" in command_contract
    assert "context_command" in command_contract
    assert "worker_step_id" in api_md
    assert "context_command" in skill


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-transfer-docs-cover-project-identity-and-dry-run
def test_transfer_docs_cover_project_identity_and_dry_run() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    usage = (ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
    command_contract = (ROOT / "docs" / "command_contract.md").read_text(
        encoding="utf-8"
    )
    transfer = (ROOT / "docs" / "transfer.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")

    assert "project_name" in readme
    assert "taskledger-export-{project_slug}-{ledger_ref}-{timestamp}.tar.gz" in readme
    assert "--project-name" in usage
    assert "taskledger import ./taskledger-transfer.tar.gz --dry-run" in usage
    assert "manifest.project.name" in command_contract
    assert "project.uuid" in transfer
    assert "taskledger import --dry-run" in transfer
    assert "taskledger import ./taskledger-transfer.tar.gz --dry-run" in skill


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-sync-docs-promote-git-pull-push-convenience-commands
def test_sync_docs_promote_git_pull_push_convenience_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    usage = (ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
    sync_doc = (ROOT / "docs" / "sync.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")

    for text in (readme, usage, sync_doc, skill):
        assert "taskledger sync git pull" in text
        assert "taskledger sync git push" in text

    assert 'cd "$(taskledger sync git cd)"' in sync_doc


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-docs-do-not-reference-removed-commands
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
        "taskledger file unlink",
        "taskledger link link",
        "taskledger link unlink",
        "taskledger actor whoami --json",
    ]
    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{path}: {needle}"


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-bdd-docs-and-skill-prefer-specweave-and-plain-pytest
def test_docs_and_skill_describe_isolated_ledger() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    usage = (ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
    command_contract = (ROOT / "docs" / "command_contract.md").read_text(
        encoding="utf-8"
    )
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")

    for text in (readme, usage, command_contract, agents, skill):
        assert "opaque" in text.lower() or "ledgerdeck" in text.lower()

    # BDD commands should not appear in docs or skill
    for text in (readme, usage, command_contract, agents, skill):
        assert "bdd gherkin-export" not in text
        assert "bdd export-json" not in text
        assert "import-bdd-report" not in text
        assert "archledger-candidate" not in text


def test_behavior_spec_docs_do_not_promote_bdd_runners() -> None:
    """Verify docs do not reference an external BDD runner or pytest-bdd/behave.

    ARCHITECTURE.md is generated from records; this test catches
    regressions if the source drifts back to the old wording.
    """
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    usage = (ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")

    for text in (architecture, readme, usage, skill):
        assert "taskledger trace" in text or "trace" in text

    assert "external BDD runner executes" not in architecture
    assert "pytest-bdd" not in architecture.lower()
    assert "behave" not in architecture.lower()


def test_readme_links_exist() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", readme):
        if "://" in target or target.startswith("#"):
            continue
        local_target = target.split("#", 1)[0]
        if not local_target:
            continue
        assert (ROOT / local_target).exists(), target


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-readme-skill-path-matches-repository
def test_readme_skill_path_matches_repository() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "skills/taskledger/SKILL.md" in readme
    assert "taskledger/skills/taskledger/SKILL.md" not in readme


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-skill-uses-only-canonical-handoff-group
def test_skill_uses_only_canonical_handoff_group() -> None:
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")
    assert "handoff-protocol" not in skill


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-command-examples-reference-registered-commands
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


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-service-boundary-whitelist-doc-matches-test-constants
def test_service_boundary_whitelist_doc_matches_test_constants() -> None:
    """Verify docs/service_boundary_whitelist.md tracks current whitelist entries."""
    from tests.test_service_boundaries import (
        CLI_SERVICES_IMPORT_WHITELIST,
        FUNCTION_LINE_WHITELIST,
        MODULE_LINE_WHITELIST,
    )

    doc = (ROOT / "docs" / "service_boundary_whitelist.md").read_text(encoding="utf-8")

    # Module whitelist entries must appear in the doc
    for module_path in MODULE_LINE_WHITELIST:
        assert module_path in doc, (
            f"Module whitelist entry missing from doc: {module_path}"
        )

    # Function whitelist entries must appear in the doc
    for func_path in FUNCTION_LINE_WHITELIST:
        # Doc uses :: separator same as test keys
        assert func_path in doc, (
            f"Function whitelist entry missing from doc: {func_path}"
        )

    # CLI services import whitelist entries must appear in the doc
    for import_ref in CLI_SERVICES_IMPORT_WHITELIST:
        # import_ref is like "taskledger/cli.py:taskledger.services.dashboard"
        module_ref = import_ref.split(":", 1)[1]
        assert module_ref in doc, f"CLI services import missing from doc: {module_ref}"


def test_service_boundary_whitelist_doc_matches_cli_import_whitelist_exactly() -> None:
    """Verify CLI services import refs in doc match test whitelist as exact sets."""
    from tests.test_service_boundaries import CLI_SERVICES_IMPORT_WHITELIST

    doc = (ROOT / "docs" / "service_boundary_whitelist.md").read_text(encoding="utf-8")
    doc_refs = set(
        re.findall(
            r"`(taskledger/cli[^`]+:taskledger\.services\.[^`]+)`",
            doc,
        )
    )

    assert doc_refs == set(CLI_SERVICES_IMPORT_WHITELIST), (
        f"Doc refs != test whitelist. "
        f"Extra in doc: {doc_refs - set(CLI_SERVICES_IMPORT_WHITELIST)}. "
        f"Missing from doc: {set(CLI_SERVICES_IMPORT_WHITELIST) - doc_refs}."
    )


# sw: f=specs/behavior/features/docs_and_skill/docs-and-skill.feature
# sw: s=@bdd-docs-and-skill-skill-requires-user-requested-reviews-to-be-recorded
def test_skill_requires_user_requested_reviews_to_be_recorded() -> None:
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")
    assert "## User-requested review protocol" in skill
    assert "treat the output as durable review evidence" in skill
    assert "taskledger review record --task TASK_ID" in skill
    assert "taskledger review list --task TASK_ID" in skill
    assert (
        "Do not skip `review record` merely because the task is already `done`"
    ) in skill


def test_skill_documents_release_boundary_protocol() -> None:
    skill = (ROOT / "skills" / "taskledger" / "SKILL.md").read_text(encoding="utf-8")
    assert "## Release boundary protocol" in skill
    assert 'taskledger release tag VERSION --at-task TASK_ID --note "..."' in skill
    assert "taskledger release list" in skill
    assert "taskledger release show VERSION" in skill
    assert (
        "Do not create changelog entries or edit `CHANGELOG.md` with taskledger"
        in skill
    )


# ── Ledger isolation tests ──────────────────────────────────────

FORBIDDEN_RUNTIME_PATTERNS = (
    "taskledger.api.bdd",
    "taskledger.domain.bdd",
    "bdd_gherkin",
    "bdd_reports",
    "gherkin-export",
    "archledger-candidate",
    "import-bdd-report",
)


def test_taskledger_runtime_has_no_bdd_or_archledger_coupling() -> None:
    runtime_paths = list((ROOT / "taskledger").rglob("*.py"))
    haystack = "\n".join(path.read_text(encoding="utf-8") for path in runtime_paths)
    for pattern in FORBIDDEN_RUNTIME_PATTERNS:
        assert pattern not in haystack, f"Forbidden pattern found in runtime: {pattern}"
