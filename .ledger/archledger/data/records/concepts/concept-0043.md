---
schema_version: 4
id: concept-0043
type: concept
title: Atomic file writes
status: proposed
section: cross_cutting_concepts
order: 40
applies_to: []
body_format: markdown
kind: concept
version: 2
---

All file writes go through `atomic_write_text` (temp file, flush, fsync, `os.replace`, directory fsync) or `atomic_create_text` (`O_CREAT | O_EXCL` for lock files). These primitives come from `ledgercore.atomic` and are re-exported by `taskledger/storage/atomic.py`. This prevents partial writes on crash. Test environments can disable fsync via `TASKLEDGER_TEST_FAST_IO=1` for speed.
