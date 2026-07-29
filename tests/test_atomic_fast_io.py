from __future__ import annotations

from pathlib import Path

import pytest
from ledgercore import atomic as ledgercore_atomic

from taskledger.storage import atomic


# specmason: req=REQ-0006 ac=AC-0082
def test_atomic_write_skips_fsync_when_fast_test_io_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[int] = []
    monkeypatch.setenv("TASKLEDGER_TEST_FAST_IO", "1")
    monkeypatch.setattr(ledgercore_atomic.os, "fsync", lambda fd: calls.append(fd))

    atomic.atomic_write_text(tmp_path / "x.txt", "hello")

    assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "hello"
    assert calls == []


# specmason: req=REQ-0006 ac=AC-0082
@pytest.mark.durable_io
def test_atomic_write_uses_fsync_by_default(tmp_path: Path, monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.delenv("TASKLEDGER_TEST_FAST_IO", raising=False)
    monkeypatch.setattr(ledgercore_atomic.os, "fsync", lambda fd: calls.append(fd))

    atomic.atomic_write_text(tmp_path / "x.txt", "hello")

    assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "hello"
    assert calls
