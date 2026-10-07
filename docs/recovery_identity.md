# UUID identity and allocation recovery

This runbook covers damaged UUID-backed task identity, incomplete task allocations,
misattributed tombstones, and unresolved cross-task relationships. Repair commands
are exceptional recovery surfaces, not normal lifecycle commands. Diagnose first;
apply only a reviewed dry-run plan against an unchanged source.

## Safety boundary

- Stop other Taskledger writers before taking the snapshot or applying a repair.
- Do not infer physical identity from a `task-####` display alias. A repair plan
  must show the physical source path and persisted source ID separately.
- Do not delete tombstones or recovery payloads by hand, choose a UUID by guess,
  or rebuild indexes while canonical identity/schema findings remain unresolved.
- If source provenance is missing, inconsistent, or changed since the dry run,
  stop and preserve the evidence for a human decision.

## Backup and read-only diagnosis

Before any mutation, create and verify a complete backup/snapshot of the checkout's
`.ledger/ledger.toml` and `.ledger/taskledger` configuration, the full resolved
`data` mount, and relevant `indexes`/recovery data. Find the actual mounts with:

```bash
taskledger storage where
taskledger storage path data
taskledger storage path indexes
```

Do not assume the durable data is inside the checkout; the default data mount is
external. Keep the snapshot outside the live mounts and record its location and
verification evidence. Then inspect without mutating:

```bash
taskledger --json doctor
taskledger --json doctor schema
taskledger --json doctor locks
taskledger --json doctor indexes
taskledger repair allocations --audit
taskledger task show TASK_UUID
```

Doctor and audit reads do not rebuild indexes. A UUID task show inspects that
bundle directly and may include relationship diagnostics. Preserve the structured
outputs, record IDs, source paths, migration receipt, event provenance, and
fingerprints before deciding whether a repair is safe.

## Incomplete allocation repair

`repair allocations` is dry-run by default. Review the physical source, display
alias, quarantine destination, tombstone destination, collision findings, and
plan fingerprint. Applying requires explicit scope and the exact reviewed plan ID:

```bash
taskledger repair allocations --task-id task-0019
taskledger repair allocations --task-id task-0019 --apply --plan-id PLAN_ID --reason "Quarantine the reviewed physical source."
```

A normal orphan allocation uses `quarantine_and_tombstone`: the physical source is
preserved in quarantine and a tombstone reserves its retired identity. A stale
incomplete `tasks/task-####/` directory may instead be shadowed by exactly one live
UUID bundle whose persisted legacy ID is the same. The dry-run identifies this as
`quarantine_shadowed_legacy_source`, names the surviving UUID owner, and sets
`planned_tombstone` to null. Applying that reviewed plan quarantines only the stale
directory and creates no tombstone, because the identity remains live. Strict identity
inventory must succeed afterward with that UUID bundle as sole owner.

Ambiguous ownership—including an existing tombstone, multiple live claimants, a
non-live claimant, or a changed physical source—is `blocked_identity_conflict` and
must not be applied. The dry-run reports `apply_safe: false` and no `next_command`.
Doctor's allocation hint begins with the dry-run; apply only the exact plan ID when
that report says it is safe.

For a deliberate bulk operation, inspect the complete dry-run and then use
`--all --apply --plan-id PLAN_ID --reason "..."`. Never use an unscoped apply.
The apply verifies source fingerprints, checks destinations and identity
postconditions, and rolls back or reports an incomplete transaction on failure.

## Reconcile a previously misattributed tombstone

Use this only when the tombstone's repair event and preserved quarantine provide
reviewable provenance for the physical source. The dry-run identifies the old
and corrected IDs and indicates whether evidence is verified or operator-asserted:

```bash
taskledger repair allocations --reconcile-source-id task-0019 --tombstone-id task-0037
```

If the evidence, quarantine, and plan are consistent, apply that exact plan:

```bash
taskledger repair allocations --reconcile-source-id task-0019 --tombstone-id task-0037 --apply --plan-id PLAN_ID --reason "Correct the tombstone to the physical source identity."
```

The prior tombstone is retained in recovery, the corrected tombstone records the
retired physical source, the quarantine payload is preserved, and an audit event
records the reconciliation. If provenance does not match the requested physical
source, do not apply and do not remove the old tombstone manually.

Prior allocation repairs can be reviewed read-only with:

```bash
taskledger repair allocations --audit
```

## Backfill a known relationship UUID

For a selected UUID task bundle, relation repair is also dry-run by default. Review
the source fingerprint and authoritative target UUID before applying:

```bash
taskledger repair relation --task-uuid TASK_UUID --field parent_task_uuid
taskledger repair relation --task-uuid TASK_UUID --field parent_task_uuid --apply --plan-id PLAN_ID --reason "Backfill the reviewed parent UUID."
```

For a requirement sidecar, supply `--field required_task_uuid` and
`--requirement-id REQUIREMENT_ID`. The repair refuses ambiguous mapping evidence,
changed source records, or invalid postconditions.

## Verify and rebuild derived indexes

After canonical identity, relationships, and schema are healthy, explicitly rebuild
indexes and inspect them. Do not use index rebuilding as a diagnostic step:

```bash
taskledger --json doctor schema
taskledger repair allocations --audit
taskledger repair index
taskledger --json doctor indexes
taskledger --json doctor
```

Require structured, healthy doctor output and no unresolved identity or relation
findings before resuming ordinary writes.

## Readio incident runbook (not executed here)

This section records steps for the operator on the separate Readio machine. No
Readio checkout, ledger, backup, or external data mount was accessed or changed
while this procedure was written. The UUIDs below are copied from the supplied
incident report and must be re-confirmed from that machine's backup and migration
receipt before use:

- live task 37: `00dc6acf-ac25-76b7-9c95-3e6e51ff322d`
- child task 38: `00dc6acf-ac26-706f-a725-473d7990a711`
- physical incomplete source: `tasks/task-0019`
- suspect old tombstone: `task-0037`

On the Readio machine, stop writers and snapshot the checkout configuration plus
the full resolved Taskledger data mount and recovery payload before running any
repair. Then:

1. Run the read-only doctor, schema, lock, index, and allocation-audit commands
   above. Directly inspect the two UUID bundles and the v5-to-v6 migration receipt.
   Confirm that task 37's persisted legacy identity maps to its live UUID and that
   task 38 is its intended follow-up.
2. Review the old tombstone, its allocation-repair event, and the quarantine
   directory as one evidence set. Confirm that the quarantined payload came from
   physical `tasks/task-0019`; do not infer that from display alias `task-0037`.
3. Run the tombstone reconciliation dry-run for source `task-0019` and old
   tombstone `task-0037`. Apply only if its provenance, payload, destination, and
   reviewed plan fingerprint all agree. Otherwise stop and retain the snapshot and
   evidence for manual investigation; never delete the tombstone or payload by
   hand as a shortcut.
4. Run a dry-run relation repair on task 38 for `parent_task_uuid`. Confirm the
   target is the task-37 UUID from the migration receipt and live task record,
   then apply the exact reviewed plan. Do not choose among conflicting targets.
5. Re-run read-only doctor/schema and allocation-provenance checks. Confirm one
   live task-37 identity, a correct task-0019 retirement record, intact recovery
   payload, and UUID-backed task-38 relationship. Only then rebuild indexes
   explicitly and run doctor/schema/index checks again.
6. Inspect every other prior allocation-repair event against its physical source,
   quarantine directory, and tombstone. Do not bulk reverse unrelated repairs;
   reconcile only individually evidenced mismatches.

If any postcondition fails, stop further writes and use the verified snapshot and
repair audit trail for recovery. This runbook is guidance only; it does not imply
that the separate Readio recovery was carried out.
