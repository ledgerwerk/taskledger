from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.search import (
    _discovery_tokens,
    _read_text_file,
    discover_relevant_files,
    grep_project,
    iter_repo_files,
    module_dependencies,
    search_project,
    symbols_project,
)
from taskledger.storage.init import init_project_state
from taskledger.storage.repos import add_repo


def setup_repo_with_files(
    tmp_path: Path,
    name: str,
    files: dict[str, bytes | str],
) -> Path:
    paths, _ = init_project_state(tmp_path)
    repo_dir = tmp_path / name
    repo_dir.mkdir()
    for rel, data in files.items():
        p = repo_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            p.write_bytes(data)
        else:
            p.write_text(data, encoding="utf-8")
    add_repo(paths, name=name, path=repo_dir)
    return paths


# specmason: req=REQ-0047 ac=AC-0525
def test_search_grep_and_symbols_basic(tmp_path: Path):
    # Create a repo with text files, a binary file and a python symbol
    files = {
        "file1.py": "def searchFunc():\n    pass\n",
        "file2.txt": "searchToken here\nsecond searchToken\nother",
        "bad.txt": b"\xff\xff\xff",
        "image.png": b"\x89PNG\r\n",
    }
    paths = setup_repo_with_files(tmp_path, "repo_a", files)

    # search_project should find content matches (case-insensitive)
    results = search_project(paths, query="searchToken")
    assert any(r.kind == "content" and "searchToken" in r.text for r in results)

    # grep_project should accept a regex and find matches
    grep_results = grep_project(paths, pattern="searchToken")
    assert any(r.kind == "content" and "searchToken" in r.text for r in grep_results)

    # invalid regex should raise LaunchError
    with pytest.raises(LaunchError):
        grep_project(paths, pattern="[unclosed")

    # symbols_project should discover the python symbol
    sym = symbols_project(paths, query="searchfunc")
    assert any(
        s.kind == "symbol" and s.symbol and s.symbol.lower().startswith("searchfunc")
        for s in sym
    )

    # iter_repo_files should skip binary/unknown extensions and hidden dirs
    seen = [str(rel) for _repo, _file, rel in iter_repo_files(paths)]
    assert "file1.py" in seen
    assert "file2.txt" in seen
    assert all(not item.endswith("image.png") for item in seen)


# specmason: req=REQ-0047 ac=AC-0524
def test_module_dependencies_and_errors(tmp_path: Path):
    # valid manifest
    files = {
        "mymodule/__manifest__.py": "{'name': 'my_mod_name', 'depends': ['a', 'b']}",
    }
    paths = setup_repo_with_files(tmp_path, "repo_b", files)

    info = module_dependencies(paths, repo_ref="repo_b", module="mymodule")
    assert info.repo == "repo_b"
    assert info.module == "mymodule"
    assert "__manifest__.py" in info.manifest_path
    assert info.depends == ("a", "b")

    # missing module should raise
    with pytest.raises(LaunchError):
        module_dependencies(paths, repo_ref="repo_b", module="nope")

    # bad manifest shape for depends
    bad_files = {
        "badmod/__manifest__.py": "{'name': 'x', 'depends': 'notalist'}",
    }
    # write into same repo dir
    repo_root = Path(paths.workspace_root) / "repo_b"
    for rel, data in bad_files.items():
        p = repo_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding="utf-8")

    with pytest.raises(LaunchError):
        module_dependencies(paths, repo_ref="repo_b", module="badmod")


# specmason: req=REQ-0047 ac=AC-0523
def test_discovery_tokens_and_discover_files(tmp_path: Path):
    # discovery tokens filters stop words and short tokens
    tokens = _discovery_tokens("The quick brown fox and the something")
    assert "quick" in tokens and "brown" in tokens and "something" in tokens
    assert all(len(t) >= 4 for t in tokens)

    # create repo with files that include the token
    files = {
        "alpha.txt": "contains discoverme token",
        "beta.py": "nothing here",
        "module/__manifest__.py": "{'name': 'module', 'depends': []}",
    }
    paths = setup_repo_with_files(tmp_path, "repo_c", files)

    # discovery should return ranked repo:path strings
    results = discover_relevant_files(paths, query="discoverme")
    assert any(r.startswith("repo_c:") for r in results)

    # queries that produce no useful tokens should raise
    with pytest.raises(LaunchError):
        discover_relevant_files(paths, query="and the for from this")


def test_read_text_file_returns_none_on_decode_error(tmp_path: Path):
    _paths, _ = init_project_state(tmp_path)
    p = tmp_path / "bin.txt"
    p.write_bytes(b"\xff\xfe\xff")
    assert _read_text_file(p) is None
