from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "taskledger"
MAX_MODULE_LINES = 1500
MAX_FUNCTION_LINES = 250


def _module_for(path: Path, root: Path) -> tuple[str, str]:
    relative = path.relative_to(root).with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        module = ".".join(parts[:-1])
        package = module
    else:
        module = ".".join(parts)
        package = module.rpartition(".")[0]
    return module, package


def _import_targets(
    node: ast.Import | ast.ImportFrom,
    *,
    package: str,
    modules: set[str],
) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names if alias.name in modules}

    if node.level:
        relative_name = "." * node.level + (node.module or "")
        try:
            base = importlib.util.resolve_name(relative_name, package)
        except ImportError:
            return set()
    else:
        base = node.module or ""

    targets = {base} if base in modules else set()
    for alias in node.names:
        candidate = f"{base}.{alias.name}" if base else alias.name
        if candidate in modules:
            targets.add(candidate)
    return targets


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, module: str, package: str, modules: set[str]) -> None:
        self.module = module
        self.package = package
        self.modules = modules
        self.function_scope: list[str] = []
        self.function_import_count: defaultdict[str, int] = defaultdict(int)
        self.edges: set[str] = set()
        self.function_imports: list[dict[str, Any]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.function_scope.append(node.name)
        self.generic_visit(node)
        self.function_scope.pop()

    def visit_Import(self, node: ast.Import) -> None:
        self._record(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._record(node)

    def _record(self, node: ast.Import | ast.ImportFrom) -> None:
        targets = _import_targets(node, package=self.package, modules=self.modules)
        self.edges.update(targets)
        if not self.function_scope or not targets:
            return
        scope = ".".join(self.function_scope)
        self.function_import_count[scope] += 1
        ordinal = self.function_import_count[scope]
        self.function_imports.append(
            {
                "id": f"{self.module}::{scope}:import-{ordinal}",
                "line": node.lineno,
                "targets": sorted(targets),
            }
        )


def _strongly_connected_components(
    graph: dict[str, set[str]],
) -> list[list[str]]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(module: str) -> None:
        nonlocal index
        indices[module] = index
        lowlinks[module] = index
        index += 1
        stack.append(module)
        on_stack.add(module)

        for target in graph[module]:
            if target not in indices:
                visit(target)
                lowlinks[module] = min(lowlinks[module], lowlinks[target])
            elif target in on_stack:
                lowlinks[module] = min(lowlinks[module], indices[target])

        if lowlinks[module] != indices[module]:
            return
        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == module:
                break
        if len(component) > 1:
            components.append(sorted(component))

    for module in sorted(graph):
        if module not in indices:
            visit(module)
    return sorted(components)


def analyze(root: Path = ROOT) -> dict[str, Any]:
    package_root = root / "taskledger"
    files = sorted(package_root.rglob("*.py"))
    module_info = {path: _module_for(path, root) for path in files}
    modules = {module for module, _ in module_info.values()}
    graph = {module: set() for module in modules}
    function_imports: list[dict[str, Any]] = []
    module_lines: dict[str, int] = {}
    long_functions: list[dict[str, Any]] = []

    for path, (module, package) in module_info.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _ImportVisitor(module, package, modules)
        visitor.visit(tree)
        graph[module] = visitor.edges
        function_imports.extend(visitor.function_imports)
        lines = len(path.read_text(encoding="utf-8").splitlines())
        module_lines[module] = lines

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = node.end_lineno or node.lineno
                span = end_line - node.lineno + 1
                if span > MAX_FUNCTION_LINES:
                    long_functions.append(
                        {
                            "function": f"{module}::{node.name}",
                            "lines": span,
                            "start_line": node.lineno,
                        }
                    )

    def has_prefix(module: str, prefix: str) -> bool:
        return module == prefix or module.startswith(f"{prefix}.")

    layer_violations = {
        "storage_to_services": sorted(
            f"{source} -> {target}"
            for source, targets in graph.items()
            if has_prefix(source, "taskledger.storage")
            for target in targets
            if has_prefix(target, "taskledger.services")
        ),
        "services_to_cli": sorted(
            f"{source} -> {target}"
            for source, targets in graph.items()
            if has_prefix(source, "taskledger.services")
            for target in targets
            if target == "taskledger.cli" or target.startswith("taskledger.cli_")
        ),
        "domain_to_storage_or_services": sorted(
            f"{source} -> {target}"
            for source, targets in graph.items()
            if has_prefix(source, "taskledger.domain")
            for target in targets
            if has_prefix(target, "taskledger.storage")
            or has_prefix(target, "taskledger.services")
        ),
    }
    components = _strongly_connected_components(graph)
    large_modules = [
        {"module": module, "lines": lines}
        for module, lines in sorted(module_lines.items())
        if lines > MAX_MODULE_LINES
    ]
    function_imports.sort(key=lambda item: item["id"])
    long_functions.sort(key=lambda item: item["function"])

    return {
        "metrics": {
            "production_python_files": len(files),
            "package_loc": sum(module_lines.values()),
            "function_scope_imports": len(function_imports),
        },
        "multi_module_sccs": components,
        "layer_violations": layer_violations,
        "modules_over_1500_lines": large_modules,
        "functions_over_250_lines": long_functions,
        "function_scope_imports": function_imports,
    }


def _strict_violations(report: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if report["multi_module_sccs"]:
        violations.append("private runtime import graph contains multi-module SCCs")
    for name, edges in report["layer_violations"].items():
        if edges:
            violations.append(f"{name}: {len(edges)} forbidden import edges")
    if report["modules_over_1500_lines"]:
        violations.append(
            f"{len(report['modules_over_1500_lines'])} modules exceed "
            f"{MAX_MODULE_LINES} lines"
        )
    if report["functions_over_250_lines"]:
        violations.append(
            f"{len(report['functions_over_250_lines'])} functions exceed "
            f"{MAX_FUNCTION_LINES} lines"
        )
    if report["function_scope_imports"]:
        violations.append(
            f"{len(report['function_scope_imports'])} Taskledger-local "
            "function-scope imports need removal or justification"
        )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report Taskledger import and size boundaries."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit the full report as JSON."
    )
    parser.add_argument(
        "--strict", action="store_true", help="Fail while any reported debt remains."
    )
    args = parser.parse_args()
    report = analyze()
    violations = _strict_violations(report)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        metrics = report["metrics"]
        print(f"Production Python files: {metrics['production_python_files']}")
        print(f"Package LOC: {metrics['package_loc']}")
        print(
            "Taskledger-local function-scope imports: "
            f"{metrics['function_scope_imports']}"
        )
        print(f"Multi-module SCCs: {len(report['multi_module_sccs'])}")
        print(
            f"Modules over {MAX_MODULE_LINES} lines: "
            f"{len(report['modules_over_1500_lines'])}"
        )
        print(
            f"Functions over {MAX_FUNCTION_LINES} lines: "
            f"{len(report['functions_over_250_lines'])}"
        )
        for violation in violations:
            print(f"- {violation}")

    return int(args.strict and bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
