from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# specmason: req=REQ-0066 ac=AC-0749
def test_services_tasks_has_no_duplicate_top_level_function_names() -> None:
    path = ROOT / "taskledger" / "services" / "tasks.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    seen: set[str] = set()
    duplicates: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            if node.name in seen:
                duplicates.add(node.name)
            seen.add(node.name)

    assert duplicates == set()
