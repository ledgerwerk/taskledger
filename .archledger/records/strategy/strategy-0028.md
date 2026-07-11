---
schema_version: 4
id: strategy-0028
type: strategy_item
title: Atomic file writes for durability
status: proposed
section: solution_strategy
order: 50
drivers: durability of canonical records; no partial writes
constraints:
  ledgercore atomic primitives; fsync overhead; TASKLEDGER_TEST_FAST_IO
  escape hatch
related_adrs: adr-0046
body_format: markdown
kind: strategy
version: 5
---

## Strategy

All file writes go through the `ledgercore` atomic primitives used by `taskledger/storage/atomic.py`: write to a temp file in the target directory, flush plus fsync, then `os.replace` for atomic rename. Directory fsync follows. Lock creation uses `atomic_create_text` with `O_CREAT | O_EXCL` for exclusive creation. These patterns prevent partial or corrupt writes on crash.

## Trade-offs

- Slightly slower than direct writes due to temp file plus fsync overhead.
- Can be disabled for testing via the `TASKLEDGER_TEST_FAST_IO` environment variable.
- Guarantees that readers always see complete, valid files.
