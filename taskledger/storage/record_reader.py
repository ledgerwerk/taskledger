from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast

from taskledger.domain.states import TASKLEDGER_SCHEMA_VERSION
from taskledger.errors import LaunchError
from taskledger.storage.frontmatter import (
    normalize_front_matter_newlines,
    read_markdown_front_matter,
)

T = TypeVar("T")


def load_markdown_record(
    path: Path,
    parser: Callable[[dict[str, object]], T],
    *,
    front_matter_reader: Callable[
        [Path], tuple[dict[str, object], str]
    ] = read_markdown_front_matter,
) -> T:
    metadata, body = front_matter_reader(path)
    metadata["body"] = normalize_front_matter_newlines(body).rstrip("\n")
    metadata = ensure_schema_compat(metadata)
    return parser(metadata)


def ensure_schema_compat(record: dict[str, object]) -> dict[str, object]:
    version = record.get("schema_version", 1)
    if cast(int, version) > TASKLEDGER_SCHEMA_VERSION:
        raise LaunchError(
            f"Record schema too new: {version} "
            f"(current max: {TASKLEDGER_SCHEMA_VERSION}). "
            "Please upgrade taskledger."
        )
    return record
