#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FunctionBlock:
    file: str
    name: str
    start: int
    end: int
    body_lines: tuple[str, ...]


def _is_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _normalize_line(line: str) -> str:
    value = line.strip()
    value = re.sub(r"\"[^\"]*\"|'[^']*'", '"<str>"', value)
    value = re.sub(r"\b\d+\b", "<int>", value)
    return value


def _iter_python_files(root: Path, include_tests: bool) -> list[Path]:
    files: list[Path] = []
    package_dir = root / "taskledger"
    if package_dir.exists():
        files.extend(sorted(package_dir.rglob("*.py")))
    if include_tests:
        tests_dir = root / "tests"
        if tests_dir.exists():
            files.extend(sorted(tests_dir.rglob("*.py")))
    return [path for path in files if path.is_file()]


def _function_blocks(path: Path, root: Path) -> list[FunctionBlock]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text)
    blocks: list[FunctionBlock] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
            continue
        start = int(node.lineno)
        end = int(node.end_lineno)
        snippet = tuple(lines[start - 1 : end])
        blocks.append(
            FunctionBlock(
                file=path.relative_to(root).as_posix(),
                name=node.name,
                start=start,
                end=end,
                body_lines=snippet,
            )
        )
    return blocks


def _effective_line_count(lines: tuple[str, ...]) -> int:
    return sum(1 for line in lines if not _is_comment_or_blank(line))


def _scan_exact_duplicates(
    blocks: list[FunctionBlock], min_lines: int
) -> list[dict[str, object]]:
    grouped: dict[str, list[FunctionBlock]] = defaultdict(list)
    for block in blocks:
        if _effective_line_count(block.body_lines) < min_lines:
            continue
        key = "\n".join(block.body_lines).strip()
        if not key:
            continue
        grouped[key].append(block)
    results: list[dict[str, object]] = []
    for matches in grouped.values():
        if len(matches) < 2:
            continue
        results.append(
            {
                "copies": len(matches),
                "locations": [
                    {
                        "file": block.file,
                        "name": block.name,
                        "start": block.start,
                        "end": block.end,
                    }
                    for block in sorted(
                        matches,
                        key=lambda item: (item.file, item.start),
                    )
                ],
            }
        )
    return sorted(results, key=lambda item: int(item["copies"]), reverse=True)


def _normalized_windows(
    path: Path, min_lines: int
) -> list[tuple[int, tuple[str, ...]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    normalized: list[tuple[int, str]] = []
    for index, line in enumerate(lines, start=1):
        if _is_comment_or_blank(line):
            continue
        normalized.append((index, _normalize_line(line)))
    if len(normalized) < min_lines:
        return []
    windows: list[tuple[int, tuple[str, ...]]] = []
    for offset in range(len(normalized) - min_lines + 1):
        start_line = normalized[offset][0]
        body = tuple(item[1] for item in normalized[offset : offset + min_lines])
        windows.append((start_line, body))
    return windows


def _scan_window_clones(
    files: list[Path], root: Path, min_lines: int
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, ...], list[tuple[str, int]]] = defaultdict(list)
    for path in files:
        rel = path.relative_to(root).as_posix()
        for start_line, window in _normalized_windows(path, min_lines):
            grouped[window].append((rel, start_line))
    results: list[dict[str, object]] = []
    for window, matches in grouped.items():
        if len(matches) < 2:
            continue
        files_touched = {item[0] for item in matches}
        if len(files_touched) < 2:
            continue
        results.append(
            {
                "occurrences": len(matches),
                "window_size": min_lines,
                "sample": list(window),
                "locations": [
                    {"file": file_name, "start": start}
                    for file_name, start in sorted(matches)
                ],
            }
        )
    return sorted(results, key=lambda item: int(item["occurrences"]), reverse=True)


def scan(root: Path, min_lines: int, include_tests: bool) -> dict[str, object]:
    files = _iter_python_files(root, include_tests=include_tests)
    blocks: list[FunctionBlock] = []
    for path in files:
        blocks.extend(_function_blocks(path, root))
    exact = _scan_exact_duplicates(blocks, min_lines=min_lines)
    windows = _scan_window_clones(files, root, min_lines=min_lines)
    return {
        "root": root.as_posix(),
        "include_tests": include_tests,
        "min_lines": min_lines,
        "file_count": len(files),
        "function_count": len(blocks),
        "exact_duplicate_groups": len(exact),
        "window_clone_groups": len(windows),
        "exact_duplicates": exact,
        "window_clones": windows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Find duplicate code blocks.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Workspace root containing taskledger/ (and optionally tests/).",
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=8,
        help="Minimum normalized lines for duplicate detection.",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include tests/*.py files in clone detection.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    result = scan(
        root,
        min_lines=max(1, int(args.min_lines)),
        include_tests=args.include_tests,
    )
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(
        "scan: "
        f"files={result['file_count']} functions={result['function_count']} "
        f"exact_groups={result['exact_duplicate_groups']} "
        f"window_groups={result['window_clone_groups']} "
        f"min_lines={result['min_lines']} include_tests={result['include_tests']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
