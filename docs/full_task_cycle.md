# Full Task Cycle

This page shows one complete taskledger cycle, from a fresh task through
planning, questions, implementation, validation, and closure. It uses the
strict task-first command grammar:

```text
taskledger [--root PATH] [--json] <area> <verb> [RESOURCE_REF] [--task TASK_REF] [options]
```

The examples assume the task is the active task after creation. If another task
is active, add `--task parser-fix` to each task-scoped command.

## 1. Initialize The Ledger

Run this once per workspace:

```bash
taskledger init
taskledger init --taskledger-dir /mnt/cloud/taskledger/project-a
taskledger doctor
taskledger status --full
```

`init` writes `taskledger.toml` in the workspace root and points it at the
default `.taskledger/` storage root unless `--taskledger-dir` chooses an
external location. `doctor` checks integrity. `status --full` shows the
current task, counts, health, and resolved storage paths.

## 2. Create And Activate A Task

Create the task, then make it active:

```bash
taskledger task create "Fix parser edge case" --slug parser-fix --description "Repair parser handling for nested expressions."
taskledger task activate parser-fix --reason "Start parser fix"
taskledger task active
taskledger next-action
```

`task create` records the task but does not implicitly activate it. Active task
selection is explicit so agents can safely switch between tasks.

Optional setup commands are useful when the task depends on context outside the
description:

```bash
taskledger intro create "Parser architecture" --text "The parser is staged into tokenize, parse, and normalize passes."
taskledger intro link intro-0001
taskledger file add --path taskledger/parser.py --kind code --label "Parser implementation"
taskledger file add --path tests/test_parser.py --kind test --required-for-validation
taskledger link add --url https://example.invalid/ticket/123 --label "Support ticket"
```

Introductions are reusable background notes. File links and external links tell
future planning, implementation, and validation agents where important context
lives.

## 3. Start Planning

Start the planning stage and inspect planning context:

```bash
taskledger can plan
taskledger plan start
taskledger context --for planning --format markdown
taskledger handoff plan-context --format markdown
```

`plan start` acquires a visible planning lock. The context commands render the
current task, linked files, questions, requirements, and prior records.

## 4. Ask And Answer Questions

Questions capture missing decisions before approval:

```bash
taskledger question add --text "Should the parser reject or normalize unmatched delimiters?" --required-for-plan
taskledger question add --text "Which files must validation cover?"
taskledger question open
taskledger question answer-many --text "q-0001: Reject unmatched delimiters with a clear parse error."
taskledger question dismiss QUESTION_ID --reason "Validation files are already linked."
taskledger question status
taskledger question answers --format markdown
```

Use `question answer-many` or `question answer` for decisions that should
affect the plan. Use `question dismiss` when the question is no longer
relevant.

## 5. Propose A Plan

Write the plan body in a Markdown file and propose it:

```bash
taskledger plan draft
taskledger plan upsert --file ./plan.md --criterion "Parser rejects unmatched delimiters." --criterion "Regression tests cover nested expressions."
taskledger plan show --version 1
taskledger plan diff --from 1 --to 1
```

`plan upsert` ends the active planning run and creates a reviewable plan
version. Acceptance criteria become validation criteria such as `ac-0001`.

If answers changed after the plan was proposed, regenerate before approval:

```bash
taskledger question answer-many --text "q-0001: Reject unmatched delimiters and keep the original token offset."
taskledger plan upsert --from-answers --file ./plan-v2.md
taskledger plan show --version 2
```

Regeneration keeps the durable answer snapshot aligned with the plan.

For diagnostic commands needed during planning (linting, test runs, code
inspection), preserve their output with `plan command`:

```bash
taskledger plan command -- pytest tests/test_parser.py -q
taskledger plan command -- python -m compileall taskledger
```

`plan command` records command exit code and output in planning diagnostics.
With transcript logging enabled, the same output is also captured in the
ledger-level command transcript. Use it to build evidence into the plan before
proposal.

## 6. Materialize Todos And Approve

Plans can include todos in front matter, or todos can be added manually. Approval
may also materialize structured plan todos:

```bash
taskledger plan materialize-todos --version 2 --dry-run
taskledger plan accept --version 2 --note "Ready to implement."
taskledger todo list
taskledger todo add --text "Add parser regression tests." --mandatory
taskledger todo add --text "Update parser error message docs." --optional
taskledger todo status
```

Mandatory todos gate implementation completion. Optional todos remain visible but
do not block `implement finish`.

If the project has an enabled worker pipeline, plan todos may optionally target
configured worker steps. This is an advisory overlay, not a new lifecycle stage:

```yaml
todos:
  - id: plan-todo-0001
    text: "Add failing regression tests."
    worker_step: "tester"
    validation_hint: "pytest tests/test_parser.py -q"
```

Use the worker overlay explicitly:

```bash
taskledger pipeline next
taskledger context --worker tester
taskledger handoff create --worker tester --summary "Add failing tests only."
```

All approval escape hatches require `--reason`:

- `--allow-empty-criteria --reason "..."`
- `--allow-open-questions --reason "..."`
- `--allow-empty-todos --reason "..."`
- `--no-materialize-todos --reason "..."`

Without a reason, the approval command will fail.

## 7. Start Implementation

Begin implementation and keep durable notes as work progresses:

```bash
taskledger can implement
taskledger context --for implementation --format markdown
taskledger implement start
taskledger implement checklist
taskledger implement log --message "Started parser fix."
taskledger implement command -- pytest tests/test_parser.py -q
taskledger implement change --path taskledger/parser.py --kind edit --summary "Reject unmatched delimiters with source offsets."
taskledger implement change --path tests/test_parser.py --kind test --summary "Added nested expression and delimiter regression tests."
taskledger implement deviation --message "Kept tokenizer unchanged because parser-level validation is sufficient."
taskledger implement artifact --path .taskledger-artifacts/parser-test-output.txt --summary "Parser regression test output."
taskledger implement scan-changes --from-git --summary "Implementation diff summary."
taskledger implement status
```

Use `implement command` when you want taskledger to record a command run as
part of implementation. With transcript logging enabled, it also records managed
stdout/stderr in the task transcript. Use `implement deviation` when the
implementation differs from the approved plan.

### Fresh-worker implementation

```bash
taskledger handoff create --mode implementation --todo todo-0003
taskledger context --for implementer --todo todo-0003
```

## 8. Complete Implementation Todos

Mark mandatory todos done with evidence:

Compact same-session loop:

```bash
taskledger --json next-action
taskledger --json todo next
taskledger todo show todo-0003
# implement only that todo
pytest tests/test_parser.py -q
taskledger todo done todo-0003 --evidence "pytest tests/test_parser.py -q"
taskledger --json next-action
```

Prefer this loop over broad generated context during normal work. Use
`validation_hint` before marking a todo done. Create a handoff or wider
context only when the task needs a harness or session switch.

```bash
taskledger todo next
taskledger todo done TODO_ID --evidence "pytest tests/test_parser.py -q" --artifact .taskledger-artifacts/parser-test-output.txt
taskledger todo done TODO_ID --evidence "Reviewed parser docs."
taskledger todo status
taskledger implement finish --summary "Implemented parser delimiter rejection and tests."
```

Todo source is inferred from the active lock: todos added during implementation
are recorded as `source=implementer`, during planning as `source=planner`,
and outside an active stage as `source=user`.

`implement finish` releases the implementation lock only when mandatory todos
are complete.

## 9. Validate The Work

Start validation, run checks against each acceptance criterion, and finish the
validation stage:

```bash
taskledger can validate
taskledger context --for validation --format markdown
taskledger validate start
taskledger validate status
taskledger validate check --criterion ac-0001 --status pass --evidence "pytest tests/test_parser.py -q"
taskledger validate check --criterion ac-0002 --status pass --evidence "pytest tests/test_parser.py -q"
taskledger validate show
taskledger validate finish --result passed --summary "Parser fix validated with regression tests."
```

### If validation finds a bug

```bash
taskledger validate check --criterion ac-0002 --status fail --evidence "pytest tests/test_parser.py -q"
taskledger validate finish --result failed --summary "ac-0002 failed."
taskledger next-action
taskledger context --for implementation --format markdown
taskledger implement restart --summary "Fix ac-0002 validation failure."
```

If a criterion is intentionally not validated, a user can waive it:

```bash
taskledger validate waive --criterion ac-0003 --reason "Covered by upstream integration test." --actor user
```

Waivers should be rare and explicit.

### Fresh-worker review

```bash
taskledger context --for spec-reviewer --run run-0008
taskledger context --for code-reviewer --run run-0008
```

## 10. Close The Task

After validation passes, close the task and inspect final state:

```bash
taskledger task dossier --format markdown
taskledger handoff create --mode validation --summary "Parser fix is implemented and validated."
taskledger handoff show HANDOFF_ID --format text
taskledger task close --note "Fixed parser delimiter handling and validated parser regressions."
taskledger release tag 0.4.2 --at-task parser-fix --note "0.4.2 released."
taskledger task show
taskledger task show parser-fix
taskledger status --full
taskledger doctor
```

After validation passes, the task is in `done` state. `task close` is a
final acknowledgement command for an already-done task. Release boundaries are
tracked by `taskledger release tag`. The dossier and handoff commands preserve
a fresh-context summary for future agents or reviewers.

### Post-completion follow-up deltas

When the original task is complete and a later small delta is needed, keep the
parent task closed and create a new follow-up child task:

```bash
taskledger task follow-up parser-fix "Rename parser error copy" --description "Small post-completion delta." --activate
taskledger plan start
taskledger plan upsert --file ./plan.md
taskledger plan accept --version 1 --note "Approved tiny follow-up delta."
```

Use the normal lifecycle on the follow-up task. Do not reopen the completed
parent task for ordinary deltas.

## 11. Recovery And Maintenance Commands

These commands are not part of the happy path, but they complete the operational
cycle:

```bash
taskledger lock show
taskledger doctor locks
taskledger lock break --reason "Recover stale planning lock."
taskledger implement resume --reason "Reacquire implementation lock for existing running run."
taskledger task uncancel --task TASK_REF --reason "Restore the task to a safe durable stage."
taskledger repair index
taskledger repair task --reason "Inspect task record after manual edit."
taskledger reindex
taskledger --json export
taskledger snapshot ./taskledger-snapshot --include-bodies --include-run-artifacts
```

Locks are never cleared silently. Use `lock break` only after inspecting the
lock and recording a reason. If a broken stale lock leaves an implementation run
still marked `running`, continue with `implement resume` instead of starting a
new implementation run. If a task is truly `cancelled`, use `task uncancel`
to restore a safe durable stage before re-entering planning, implementation, or
validation through the normal stage-specific commands. After `task uncancel`,
run `next-action` again; if it reports `implement-resume`, reacquire the
existing implementation run rather than running `implement start`.

## Task-centered traceability

Taskledger owns temporal work truth: task history, plans, acceptance criteria,
implementation changes, validation checks, reviews, locks, and handoffs.
Cross-ledger links are opaque file or ID references.

Use `taskledger trace TASK --format json` to emit a read-only
`taskledger.trace.v1` task bundle. The bundle links task IDs, accepted AC IDs,
opaque link refs, source refs, evidence refs, changes, reviews, and handoffs.

Evidence import is explicit and auditable through
`taskledger validate check --criterion ... --status ... --evidence ...`.
