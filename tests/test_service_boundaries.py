from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "taskledger"
MAX_MODULE_LINES = 2000
MAX_FUNCTION_LINES = 250

MODULE_LINE_WHITELIST: dict[str, str] = {
    "taskledger/services/tasks.py": (
        "Temporary compatibility facade while workflow services are extracted."
    ),
}

FUNCTION_LINE_WHITELIST: dict[str, str] = {
    "taskledger/services/doctor_checks/task_checks.py::scan_task_integrity": (
        "Consolidated per-task integrity scan with change/lock validation;"
        " further splitting into focused inspectors is planned."
    ),
    "taskledger/cli_sync.py::register_sync_commands": (
        "Sync command registration currently co-locates legacy sync, archive alias,"
        " git sync, and hook command wiring."
    ),
}

CLI_SERVICES_IMPORT_WHITELIST: dict[str, str] = {
    "taskledger/cli.py:taskledger.services.dashboard": (
        "Dashboard and view rendering are currently service-level read models."
    ),
    "taskledger/cli.py:taskledger.services.agent_logging": (
        "Root CLI initializes recorder and payload/error notes."
    ),
    "taskledger/cli.py:taskledger.services.tree": (
        "Tree rendering currently lives in services/tree.py."
    ),
    "taskledger/cli.py:taskledger.services.doctor": (
        "Repair command uses doctor cleanup helper pending API wrapper."
    ),
    "taskledger/cli.py:taskledger.services.web_dashboard": (
        "Serve command starts the optional web dashboard service."
    ),
    "taskledger/cli_report.py:taskledger.services.html_reports": (
        "Root report commands render HTML reports via the html_reports service."
    ),
    "taskledger/cli_actor.py:taskledger.services.actors": (
        "Actor and harness resolution currently lives in services/actors.py."
    ),
    "taskledger/cli_common.py:taskledger.services.agent_logging": (
        "CLI common emits recorder task/payload/error notes."
    ),
    "taskledger/cli_implement.py:taskledger.services.actors": (
        "Implementation commands resolve actor/harness context."
    ),
    "taskledger/cli_implement.py:taskledger.services.agent_logging": (
        "Implement command wrapper records managed-shell command failures."
    ),
    "taskledger/cli_misc.py:taskledger.services.doctor": (
        "Doctor commands still consume doctor service inspectors directly."
    ),
    "taskledger/cli_pipeline.py:taskledger.services.handoff": (
        "Pipeline context rendering currently reuses the handoff service payloads."
    ),
    "taskledger/cli_pipeline.py:taskledger.services.worker_pipeline": (
        "Pipeline CLI commands read the worker pipeline service overlay directly."
    ),
    "taskledger/cli_plan.py:taskledger.services.actors": (
        "Plan commands resolve actor/harness context."
    ),
    "taskledger/cli_plan.py:taskledger.services.plan_editing": (
        "Plan input path validation currently lives in services/plan_editing.py."
    ),
    "taskledger/cli_plan.py:taskledger.services.plan_lint": (
        "Plan lint payload model is still service-owned."
    ),
    "taskledger/cli_question.py:taskledger.services.actors": (
        "Question commands resolve actor/harness context."
    ),
    "taskledger/cli_plan.py:taskledger.services.workflow_guidance": (
        "Planning guidance profile read model is service-owned."
    ),
    "taskledger/cli_plan.py:taskledger.services.agent_logging": (
        "Plan command wrapper records managed-shell command failures."
    ),
    "taskledger/cli_plan.py:taskledger.services.planning_flow": (
        "Plan guidance command marks guidance viewed via planning flow service."
    ),
    "taskledger/cli_task.py:taskledger.services.actors": (
        "Task record command resolves completed-by actor metadata."
    ),
    "taskledger/cli_task.py:taskledger.services.agent_transcripts": (
        "Task transcript rendering currently lives in services."
    ),
    "taskledger/cli_task.py:taskledger.services.task_reports": (
        "Task report rendering and options are service-owned."
    ),
    "taskledger/cli_task.py:taskledger.services.tasks": (
        "Task events read path still uses services.tasks list_events helper."
    ),
    "taskledger/cli_validate.py:taskledger.services.actors": (
        "Validation commands resolve actor/harness context."
    ),
}

EXCEPT_EXCEPTION_WHITELIST: dict[str, str] = {
    "taskledger/cli.py:237": (
        "Optional command group import fallback reports missing modules gracefully."
    ),
    "taskledger/cli.py:893": (
        "Serve command optional import fallback reports missing dashboard gracefully."
    ),
    "taskledger/cli_ledger.py:111": (
        "Ledger root fallback degrades gracefully when legacy storage probes fail."
    ),
    "taskledger/cli_ledger.py:464": (
        "Ledger diagnostics command reports unknown failures as structured CLI errors."
    ),
    "taskledger/launcher.py:16": (
        "Launcher wrapper keeps user-facing startup errors consistent."
    ),
    "taskledger/services/doctor.py:96": (
        "Doctor must continue scanning even when config parsing fails."
    ),
    "taskledger/services/doctor.py:135": (
        "Doctor must continue scanning even when one task metadata read fails."
    ),
    "taskledger/services/doctor.py:139": (
        "Doctor must continue scanning even when one plan read fails."
    ),
    "taskledger/services/doctor.py:222": (
        "Doctor storage probe wraps unexpected file decoding failures."
    ),
    "taskledger/services/doctor.py:255": (
        "Doctor lock inspection ignores malformed optional lock metadata."
    ),
    "taskledger/services/doctor.py:279": (
        "Doctor lock inspection wraps malformed lock reads."
    ),
    "taskledger/services/doctor_checks/project_scan.py:49": (
        "Project scan continues past config load errors."
    ),
    "taskledger/services/doctor_checks/project_scan.py:64": (
        "Project scan continues past project UUID load errors."
    ),
    "taskledger/services/doctor_checks/project_scan.py:79": (
        "Project scan continues past ledger config load errors."
    ),
    "taskledger/services/doctor_checks/task_checks.py:59": (
        "Task scan continues past broken introduction ref resolution."
    ),
    "taskledger/services/tree.py:258": (
        "Tree command handles task ref resolution errors by returning empty."
    ),
    "taskledger/storage/ledger_config.py:85": (
        "Ledger config loader reports parse/runtime differences consistently "
        "across Python versions."
    ),
    "taskledger/storage/migrations.py:267": (
        "Migration scanner continues past one malformed legacy entry."
    ),
    "taskledger/storage/migrations.py:350": (
        "Migration planner emits actionable diagnostics for unknown migration errors."
    ),
    "taskledger/storage/migrations.py:485": (
        "Migration executor records unexpected write failures in audit output."
    ),
    "taskledger/storage/paths.py:138": (
        "Path probe falls back when environment inspection raises platform-"
        "specific errors."
    ),
    "taskledger/storage/project_config.py:424": (
        "TOML parser error handling catches runtime-specific exceptions "
        "during project config loading."
    ),
    "taskledger/storage/task_store.py:414": (
        "rewrite_task_refs falls back to plain string replacement when "
        "front matter parsing fails."
    ),
    "taskledger/storage/task_store.py:973": (
        "list_handoffs_with_errors tolerates malformed handoff records "
        "and continues scanning."
    ),
}


class _FunctionVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self._scope: list[str] = []
        self.lengths: dict[str, int] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if node.end_lineno is not None:
            qualified_name = ".".join([*self._scope, node.name])
            self.lengths[f"{self.rel_path}::{qualified_name}"] = (
                node.end_lineno - node.lineno + 1
            )
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()


def _python_files() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def test_boundary_whitelists_include_reasons() -> None:
    for whitelist in (
        MODULE_LINE_WHITELIST,
        FUNCTION_LINE_WHITELIST,
        EXCEPT_EXCEPTION_WHITELIST,
    ):
        for key, reason in whitelist.items():
            assert key
            assert reason.strip()


def test_service_module_line_budget() -> None:
    module_lines: dict[str, int] = {}
    for path in _python_files():
        rel = _relative(path)
        module_lines[rel] = len(path.read_text(encoding="utf-8").splitlines())

    unexpected = {
        rel: line_count
        for rel, line_count in module_lines.items()
        if line_count > MAX_MODULE_LINES and rel not in MODULE_LINE_WHITELIST
    }
    stale = {
        rel: module_lines.get(rel, 0)
        for rel in MODULE_LINE_WHITELIST
        if module_lines.get(rel, 0) <= MAX_MODULE_LINES
    }

    assert not unexpected, (
        "Modules above line budget without whitelist entry: "
        f"{sorted(unexpected.items())}"
    )
    assert not stale, (
        "Whitelist entries no longer needed for module line budget: "
        f"{sorted(stale.items())}"
    )


def test_service_function_line_budget() -> None:
    long_functions: dict[str, int] = {}
    for path in _python_files():
        rel = _relative(path)
        visitor = _FunctionVisitor(rel)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        long_functions.update(
            {
                name: line_count
                for name, line_count in visitor.lengths.items()
                if line_count > MAX_FUNCTION_LINES
            }
        )

    unexpected = {
        name: line_count
        for name, line_count in long_functions.items()
        if name not in FUNCTION_LINE_WHITELIST
    }
    stale = {
        name: long_functions.get(name, 0)
        for name in FUNCTION_LINE_WHITELIST
        if long_functions.get(name, 0) <= MAX_FUNCTION_LINES
    }

    assert not unexpected, (
        "Functions above line budget without whitelist entry: "
        f"{sorted(unexpected.items())}"
    )
    assert not stale, (
        "Whitelist entries no longer needed for function line budget: "
        f"{sorted(stale.items())}"
    )


def test_except_exception_sites_are_whitelisted() -> None:
    found_sites: set[str] = set()
    for path in _python_files():
        rel = _relative(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                found_sites.add(f"{rel}:{node.lineno}")

    expected_sites = set(EXCEPT_EXCEPTION_WHITELIST)
    unexpected = sorted(found_sites - expected_sites)
    stale = sorted(expected_sites - found_sites)

    assert not unexpected, f"Unapproved except Exception sites: {unexpected}"
    assert not stale, f"Whitelist sites no longer present: {stale}"


def test_cli_services_imports_are_whitelisted() -> None:
    found_imports: set[str] = set()
    for path in ROOT.glob("taskledger/cli*.py"):
        rel = _relative(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not node.module or not node.module.startswith("taskledger.services"):
                continue
            found_imports.add(f"{rel}:{node.module}")

    expected_imports = set(CLI_SERVICES_IMPORT_WHITELIST)
    unexpected = sorted(found_imports - expected_imports)
    stale = sorted(expected_imports - found_imports)

    assert not unexpected, f"Unapproved CLI->services imports: {unexpected}"
    assert not stale, f"Stale CLI->services import whitelist entries: {stale}"


def test_validation_module_has_no_private_tasks_imports() -> None:
    path = ROOT / "taskledger" / "services" / "validation.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    forbidden: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "taskledger.services.tasks":
            continue
        for alias in node.names:
            if alias.name.startswith("_"):
                forbidden.append(alias.name)

    assert not forbidden, (
        "validation.py must not import private helpers from services.tasks: "
        f"{sorted(forbidden)}"
    )


def test_tasks_validation_gate_wrapper_has_no_local_import_workaround() -> None:
    path = ROOT / "taskledger" / "services" / "tasks.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    target: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "_build_validation_gate_report":
                target = node
                break

    assert target is not None, "_build_validation_gate_report not found"
    local_imports = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.ImportFrom)
        and node.module == "taskledger.services.validation"
    ]
    assert not local_imports, (
        "_build_validation_gate_report should call a top-level imported validation "
        "helper instead of using a local import workaround."
    )


def _function_node(path: Path, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"{name} not found in {path}")


def _assert_wrapper_imports_module(
    path: Path,
    *,
    function_name: str,
    module_name: str,
) -> None:
    target = _function_node(path, function_name)
    local_imports = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.ImportFrom) and node.module == module_name
    ]
    assert local_imports, (
        f"{function_name} should delegate via local import from {module_name}."
    )


def test_tasks_planning_entrypoints_delegate_to_planning_flow() -> None:
    path = ROOT / "taskledger" / "services" / "tasks.py"
    for function_name in (
        "start_planning",
        "propose_plan",
        "upsert_plan",
        "approve_plan",
    ):
        _assert_wrapper_imports_module(
            path,
            function_name=function_name,
            module_name="taskledger.services.planning_flow",
        )


def test_tasks_implementation_entrypoints_delegate_to_implementation_flow() -> None:
    path = ROOT / "taskledger" / "services" / "tasks.py"
    for function_name in (
        "start_implementation",
        "restart_implementation",
        "resume_implementation",
        "log_implementation",
        "add_implementation_deviation",
        "add_implementation_artifact",
        "run_implementation_command",
        "finish_implementation",
    ):
        _assert_wrapper_imports_module(
            path,
            function_name=function_name,
            module_name="taskledger.services.implementation_flow",
        )


def test_tasks_validation_entrypoints_delegate_to_validation_flow() -> None:
    path = ROOT / "taskledger" / "services" / "tasks.py"
    for function_name in (
        "start_validation",
        "validation_status",
        "add_validation_check",
        "waive_criterion",
        "finish_validation",
    ):
        _assert_wrapper_imports_module(
            path,
            function_name=function_name,
            module_name="taskledger.services.validation_flow",
        )
