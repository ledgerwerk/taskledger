from __future__ import annotations

from pathlib import Path

import pytest

from taskledger.errors import LaunchError
from taskledger.storage.artifact_policy import (
    ABSOLUTE_MAX_ARTIFACT_BYTES,
    bound_text_to_bytes,
    oversized_artifact,
    validate_artifact_limit,
)


def test_text_under_and_at_limit_is_unchanged() -> None:
    for content in ("hello", "exact"):
        result = bound_text_to_bytes(content, max_bytes=len(content.encode()))
        assert result.text == content
        assert result.truncated is False
        assert result.original_bytes == result.stored_bytes


def test_oversized_text_retains_head_tail_and_marker() -> None:
    content = "HEAD\n" + ("middle\n" * 1000) + "TAIL"
    result = bound_text_to_bytes(content, max_bytes=512)

    assert result.truncated is True
    assert len(result.text.encode("utf-8")) <= 512
    assert "HEAD" in result.text
    assert "TAIL" in result.text
    assert "original_bytes=" in result.text
    assert "stored_bytes=512" in result.text
    assert "limit_bytes=512" in result.text
    assert "omitted_bytes=" in result.text


def test_oversized_text_is_utf8_safe() -> None:
    content = "äöü🙂日本語" * 100
    result = bound_text_to_bytes(content, max_bytes=127)

    assert result.text.encode("utf-8").decode("utf-8") == result.text
    assert result.stored_bytes <= 127


@pytest.mark.parametrize("value", [0, -1, True, False, ABSOLUTE_MAX_ARTIFACT_BYTES + 1])
def test_invalid_artifact_limits_are_rejected(value: object) -> None:
    with pytest.raises(LaunchError):
        validate_artifact_limit(value)


def test_tiny_artifact_limit_still_respects_bytes() -> None:
    result = bound_text_to_bytes("content", max_bytes=1)
    assert result.truncated is True
    assert result.stored_bytes <= 1


def test_oversized_artifact_uses_metadata_only(tmp_path: Path) -> None:
    path = tmp_path / "artifact.log"
    path.write_bytes(b"12345")

    assert oversized_artifact(path, max_bytes=4)
    assert not oversized_artifact(path, max_bytes=5)
