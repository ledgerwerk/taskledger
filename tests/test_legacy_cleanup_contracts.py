from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LEGACY_MODULE_PATHS = {
    "taskledger/api/composition.py",
    "taskledger/api/contexts.py",
    "taskledger/api/execution_requests.py",
    "taskledger/api/items.py",
    "taskledger/api/memories.py",
    "taskledger/api/repos.py",
    "taskledger/api/runs.py",
    "taskledger/api/runtime_support.py",
    "taskledger/api/types.py",
    "taskledger/api/validation.py",
    "taskledger/api/workflows.py",
    "taskledger/cli_compose.py",
    "taskledger/cli_context.py",
    "taskledger/cli_actor_v2.py",
    "taskledger/cli_execution_requests.py",
    "taskledger/cli_implement_v2.py",
    "taskledger/cli_handoff_v2.py",
    "taskledger/cli_item.py",
    "taskledger/cli_migrate_v2.py",
    "taskledger/cli_misc_v2.py",
    "taskledger/cli_memory.py",
    "taskledger/cli_plan_v2.py",
    "taskledger/cli_question_v2.py",
    "taskledger/cli_repo.py",
    "taskledger/cli_runs.py",
    "taskledger/cli_runtime_support.py",
    "taskledger/cli_task_v2.py",
    "taskledger/cli_validate_v2.py",
    "taskledger/cli_validation.py",
    "taskledger/cli_workflow.py",
    "taskledger/compose.py",
    "taskledger/context.py",
    "taskledger/doctor.py",
    "taskledger/links.py",
    "taskledger/models/__init__.py",
    "taskledger/models/core.py",
    "taskledger/models/execution.py",
    "taskledger/services/doctor_v2.py",
    "taskledger/storage/contexts.py",
    "taskledger/storage/items.py",
    "taskledger/storage/memories.py",
    "taskledger/storage/runs.py",
    "taskledger/storage/stages.py",
    "taskledger/storage/validation.py",
    "taskledger/storage/v2.py",
    "taskledger/storage/workflows.py",
    "taskledger/workflow.py",
}


def test_legacy_modules_are_removed() -> None:
    for relative_path in LEGACY_MODULE_PATHS:
        assert not (ROOT / relative_path).exists(), relative_path


# specmason: req=REQ-0028 ac=AC-0334
def test_package_initializers_do_not_use_star_imports() -> None:
    for relative_path in ("taskledger/__init__.py", "taskledger/api/__init__.py"):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "import *" not in text


# specmason: req=REQ-0028 ac=AC-0335
def test_v2_storage_does_not_import_storage_facade() -> None:
    text = (ROOT / "taskledger/storage/task_store.py").read_text(encoding="utf-8")
    assert "from taskledger.storage import" not in text


# specmason: req=REQ-0028 ac=AC-0333
def test_domain_models_does_not_import_legacy_models_package() -> None:
    text = (ROOT / "taskledger/domain/models.py").read_text(encoding="utf-8")
    assert "from taskledger.models import" not in text
