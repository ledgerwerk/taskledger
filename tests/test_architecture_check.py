from __future__ import annotations

from scripts.check_architecture import _strongly_connected_components, analyze


def test_strongly_connected_components_reports_only_cycles() -> None:
    graph = {
        "a": {"b"},
        "b": {"a", "c"},
        "c": {"c"},
        "d": set(),
    }

    assert _strongly_connected_components(graph) == [["a", "b"]]


def test_architecture_report_captures_import_and_size_baseline() -> None:
    report = analyze()

    assert report["metrics"]["production_python_files"] > 0
    assert report["metrics"]["package_loc"] > 0
    assert isinstance(report["multi_module_sccs"], list)
    assert set(report["layer_violations"]) == {
        "storage_to_services",
        "services_to_cli",
        "domain_to_storage_or_services",
    }
    assert isinstance(report["function_scope_imports"], list)
    assert isinstance(report["modules_over_1500_lines"], list)
    assert isinstance(report["functions_over_250_lines"], list)
