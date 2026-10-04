from __future__ import annotations

from uuid import UUID

from ledgercore.ids import LedgerIdFormat, slugify_ref
from ledgercore.refs import LedgerResourceRef, parse_resource_ref
from ledgercore.uuids import parse_uuid7 as _parse_uuid7
from ledgercore.uuids import uuid7 as _uuid7

TASK_ID_FORMAT = LedgerIdFormat(prefix="task", separator="-", width=4)


def parse_uuid7(value: str | UUID) -> UUID:
    return _parse_uuid7(value)


def uuid7() -> UUID:
    return _uuid7()


def next_project_id(prefix: str, existing_ids: list[str]) -> str:
    return LedgerIdFormat(prefix=prefix, separator="-", width=4).next(existing_ids)


def allocate_ledger_task_id(
    existing_ids: list[str],
    config_next_number: int,
) -> tuple[str, int]:
    max_existing = 0
    for item in existing_ids:
        try:
            parts = TASK_ID_FORMAT.parse_parts(item)
        except ValueError:
            continue
        max_existing = max(max_existing, parts.number)
    next_number = max(config_next_number, max_existing + 1)
    task_id = TASK_ID_FORMAT.format(next_number)
    return task_id, next_number + 1


def slugify_project_ref(value: str, *, empty: str = "item") -> str:
    return slugify_ref(value, empty=empty)


def parse_taskledger_resource_ref(
    value: str,
    *,
    default_ledger: str | None = None,
    allowed_ledgers: set[str] | None = None,
    allowed_kinds: set[str] | None = None,
) -> LedgerResourceRef:
    return parse_resource_ref(
        value,
        default_ledger=default_ledger,
        allowed_ledgers=allowed_ledgers,
        allowed_kinds=allowed_kinds,
    )


def normalize_local_resource_id(
    value: str,
    *,
    kind: str,
    default_ledger: str | None = None,
    allowed_ledgers: set[str] | None = None,
) -> str:
    ref = parse_resource_ref(
        value,
        default_ledger=default_ledger,
        allowed_ledgers=allowed_ledgers,
        allowed_kinds={kind},
    )
    return ref.local_id


def format_task_id(number: int) -> str:
    return TASK_ID_FORMAT.format(number)


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
