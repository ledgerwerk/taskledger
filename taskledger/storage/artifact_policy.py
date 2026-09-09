"""Shared size policy for Taskledger-owned artifact files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from taskledger.errors import LaunchError

ABSOLUTE_MAX_ARTIFACT_BYTES = 20_000_000


@dataclass(frozen=True, slots=True)
class BoundedText:
    """Text and accounting information for a bounded artifact payload."""

    text: str
    original_bytes: int
    stored_bytes: int
    truncated: bool
    limit_bytes: int


def validate_artifact_limit(
    value: object, *, source: str = "artifact_max_bytes"
) -> int:
    """Validate and return a finite positive artifact byte limit."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LaunchError(f"{source} must be a positive integer")
    if value > ABSOLUTE_MAX_ARTIFACT_BYTES:
        raise LaunchError(f"{source} cannot exceed {ABSOLUTE_MAX_ARTIFACT_BYTES} bytes")
    return value


def _decode_prefix(data: bytes, budget: int) -> str:
    return data[:budget].decode("utf-8", errors="ignore")


def _decode_suffix(data: bytes, budget: int) -> str:
    if budget <= 0:
        return ""
    return data[-budget:].decode("utf-8", errors="ignore")


def _marker(
    original_bytes: int, stored_bytes: int, omitted_bytes: int, limit_bytes: int
) -> str:
    return (
        "\n\n...[taskledger artifact truncated: "
        f"original_bytes={original_bytes} "
        f"stored_bytes={stored_bytes} "
        f"omitted_bytes={omitted_bytes} "
        f"limit_bytes={limit_bytes}]...\n\n"
    )


def bound_text_to_bytes(text: str, *, max_bytes: int) -> BoundedText:
    """Bound UTF-8 encoded text while retaining its beginning and end."""
    limit = validate_artifact_limit(max_bytes, source="max_bytes")
    raw = text.encode("utf-8")
    original = len(raw)
    if original <= limit:
        return BoundedText(text, original, original, False, limit)

    marker = _marker(original, limit, 0, limit)
    for _ in range(8):
        marker_bytes = marker.encode("utf-8")
        if len(marker_bytes) >= limit:
            bounded_marker = _decode_prefix(marker_bytes, limit)
            stored = len(bounded_marker.encode("utf-8"))
            return BoundedText(bounded_marker, original, stored, True, limit)

        remaining = limit - len(marker_bytes)
        head_budget = remaining // 2
        tail_budget = remaining - head_budget
        head = _decode_prefix(raw, head_budget)
        tail = _decode_suffix(raw, tail_budget)
        retained_bytes = len(head.encode("utf-8")) + len(tail.encode("utf-8"))
        stored = retained_bytes + len(marker_bytes)
        omitted = max(0, original - retained_bytes)
        next_marker = _marker(original, stored, omitted, limit)
        bounded = head + next_marker + tail
        if next_marker == marker:
            stored = len(bounded.encode("utf-8"))
            return BoundedText(bounded, original, stored, True, limit)
        marker = next_marker

    bounded = head + marker + tail
    bounded = _decode_prefix(bounded.encode("utf-8"), limit)
    stored = len(bounded.encode("utf-8"))
    return BoundedText(bounded, original, stored, True, limit)


def oversized_artifact(path: Path, *, max_bytes: int) -> bool:
    """Return whether an existing regular artifact exceeds the policy."""
    limit = validate_artifact_limit(max_bytes, source="max_bytes")
    return path.is_file() and path.stat().st_size > limit


__all__ = [
    "ABSOLUTE_MAX_ARTIFACT_BYTES",
    "BoundedText",
    "bound_text_to_bytes",
    "oversized_artifact",
    "validate_artifact_limit",
]
