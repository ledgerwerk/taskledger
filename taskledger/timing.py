"""Opt-in coarse stage timing for performance diagnostics.

Enable with ``TASKLEDGER_TIMINGS=1``. Timing is disabled by default and adds no
meaningful overhead to hot paths: :func:`stage` is a no-op unless a timer is
active, and :func:`stage_timer` activates one only when explicitly enabled.

Timings are collected per invocation in a :class:`~contextvars.ContextVar` and
emitted to stderr as ``timing <stage> <ms> ms`` lines. This module never reads,
resolves, or caches project/layout context, so enabling it cannot introduce a
process-global project-context cache.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

_ENV = "TASKLEDGER_TIMINGS"


def timings_enabled() -> bool:
    """Return True only when coarse stage timing was explicitly requested."""
    return os.environ.get(_ENV, "").strip().lower() not in ("", "0", "false", "no")


@dataclass
class StageTimer:
    """Collects named coarse-stage durations for a single invocation."""

    stages: list[tuple[str, int]] = field(default_factory=list)
    start: float = field(default_factory=time.perf_counter)

    def add(self, name: str, ms: int) -> None:
        self.stages.append((name, ms))

    def lines(self) -> list[str]:
        total = int((time.perf_counter() - self.start) * 1000)
        rows = [f"timing {name:<24} {ms} ms" for name, ms in self.stages]
        rows.append(f"timing {'total':<24} {total} ms")
        return rows


_active: ContextVar[StageTimer | None] = ContextVar(
    "taskledger_stage_timer", default=None
)


@contextmanager
def stage_timer() -> Iterator[StageTimer | None]:
    """Collect and emit coarse stage timings when explicitly enabled.

    Yields the active :class:`StageTimer` when enabled, otherwise ``None``. The
    report is written to stderr on exit. The timer lives in a per-invocation
    ``ContextVar`` and is cleared on exit, so no process-global state persists.
    """
    if not timings_enabled():
        yield None
        return
    timer = StageTimer()
    token = _active.set(timer)
    try:
        yield timer
    finally:
        _active.reset(token)
        for line in timer.lines():
            print(line, file=sys.stderr)


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Record the wall-clock duration of a named coarse stage when active."""
    timer = _active.get()
    if timer is None:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        timer.add(name, int((time.perf_counter() - start) * 1000))
