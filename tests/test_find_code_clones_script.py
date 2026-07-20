from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# specmason: req=REQ-0022 ac=AC-0294
def test_find_code_clones_script_json_and_include_tests(tmp_path: Path) -> None:
    _write(
        tmp_path / "taskledger" / "a.py",
        """
def same():
    value = "x"
    return value
""".strip()
        + "\n",
    )
    _write(
        tmp_path / "taskledger" / "b.py",
        """
def same():
    value = "x"
    return value
""".strip()
        + "\n",
    )
    _write(
        tmp_path / "tests" / "test_dup.py",
        """
def same():
    value = "x"
    return value
""".strip()
        + "\n",
    )
    script = Path(__file__).resolve().parents[1] / "scripts" / "find_code_clones.py"

    base = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(tmp_path),
            "--min-lines",
            "3",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    base_payload = json.loads(base.stdout)
    assert base_payload["include_tests"] is False
    assert base_payload["file_count"] == 2
    assert base_payload["exact_duplicate_groups"] >= 1

    with_tests = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(tmp_path),
            "--min-lines",
            "3",
            "--include-tests",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    with_tests_payload = json.loads(with_tests.stdout)
    assert with_tests_payload["include_tests"] is True
    assert with_tests_payload["file_count"] == 3
    assert (
        with_tests_payload["exact_duplicate_groups"]
        >= base_payload["exact_duplicate_groups"]
    )

    human = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(tmp_path),
            "--min-lines",
            "3",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "scan: files=" in human.stdout
