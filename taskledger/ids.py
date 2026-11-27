from __future__ import annotations

from uuid import UUID

from ledgercore.ids import LedgerIdFormat, slugify_ref
from ledgercore.uuids import parse_uuid7 as _parse_uuid7
from ledgercore.uuids import uuid7 as _uuid7

TASK_ID_FORMAT = LedgerIdFormat(prefix="task", separator="-", width=4)


def parse_uuid7(value: str | UUID) -> UUID:
    return _parse_uuid7(value)


def uuid7() -> UUID:
    return _uuid7()


def next_project_id(prefix: str, existing_ids: list[str]) -> str:
    return LedgerIdFormat(prefix=prefix, separator="-", width=4).next(existing_ids)


def slugify_project_ref(value: str, *, empty: str = "item") -> str:
    return slugify_ref(value, empty=empty)


def normalize_numeric_ref(ref: str, prefix: str) -> str:
    fmt = LedgerIdFormat(prefix=prefix, separator="-", width=4)
    try:
        parts = fmt.parse_parts(ref)
    except ValueError:
        return ref
    return fmt.format(parts.number)


def numeric_id_sort_key(value: str, *, prefix: str) -> tuple[int, str]:
    fmt = LedgerIdFormat(prefix=prefix, separator="-", width=4)
    try:
        return (fmt.parse_parts(value).number, value)
    except ValueError:
        return (10**9, value)
