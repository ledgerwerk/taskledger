---
name: taskledger
description: Manage staged coding tasks with plan approval, implementation logging, validation, locks, and fresh-context handoffs
license: Apache-2.0
compatibility: opencode
metadata:
  audience: coding-agents
  workflow: task-management
---

## When to use this skill

Use taskledger for staged coding work that needs a durable task record, reviewable plan, explicit user approval, implementation log, validation evidence, and fresh-context continuation.

## Never do these things

- Do not implement before a plan approval has been recorded. Prefer `plan accept` for explicit chat approval.
- Do not validate before implementation has been finished.
- Do not use repair commands (`repair lock`, `repair run`, `repair task`, `repair index`) in the normal lifecycle. Use them only after `doctor`/`lock show` proves there is stale or corrupted state. (`lock break` is a deprecated alias for `repair lock`.) For a normal expired implementation lock, use `implement resume --repair-expired-lock` instead.
- Do not break locks without a reason.
- Do not break locks for normal actor or harness transfer; use durable handoffs.
- Do not mark validation passed without checking every mandatory acceptance criterion.
- Do not inline large source files into taskledger records by default; use `@path` references.
- Do not import or call `taskledger.storage.*`, `taskledger.services.*`, or `taskledger.domain.*` from ad-hoc Python during normal task work. Use CLI commands or public `taskledger.api.*` only.
- Do not mutate archived tasks; unarchive first (`taskledger task unarchive TASK_ID --reason "..."`) unless the user explicitly requested read-only archived reporting.
- Do not pass approval escape hatches such as `--allow-empty-criteria`, `--allow-open-questions`, `--allow-empty-todos`, `--no-materialize-todos`, `--allow-lint-errors`, or `--allow-agent-approval` unless the user explicitly requested that bypass and gave a reason. All escape hatches require `--reason`.

## Core agent command path

Use this path first for routine work:

```text
usage
actor whoami
task active | task show | task create | task activate | task follow-up
next-action | context | can
config list | config get | config set
plan start -> plan template -> plan upsert -> plan lint -> plan accept
question add | question add-many | question answer | question answer-many | question status | question answers
todo next | todo show | todo done | todo status
implement start | implement resume | implement change | implement scan-changes | implement finish
validate start | validate status | validate check | validate finish
review record
handoff create | handoff show | handoff claim | handoff close
```

Treat release, storage movement, branch-ledger changes, repair/migration,
network sync wrappers, sync hooks, `monitor` (human-only terminal observer),
and source search helpers as advanced,
human-oriented, repair, or beta support commands rather than normal lifecycle
steps.

## Fresh context entry protocol

1. Run `taskledger usage`.
2. Run `taskledger actor whoami`.
3. Run `taskledger task active`.
4. Run `taskledger next-action`.
   - Treat this as the preferred fresh-context entrypoint.
   - Inspect `next_item` before parsing prose.
   - Run `next_command` when it is safe and appropriate.
   - Do not invent question answers, evidence, or approval notes.
5. Run `taskledger todo next`.
6. Run `taskledger context --for planning|implementation|validation --format markdown`.
7. Inspect `taskledger lock show` before active work.
8. Use `taskledger can implement` or `taskledger can validate` before those stages.
   - Use `taskledger can implement-resume` when `next-action` recommends resuming an existing implementation run.
9. If a durable handoff exists, claim it with `taskledger handoff claim handoff-0001` before continuing and close it after the intended next action starts.
10. After `taskledger import ... --replace`, assume imported locks are non-portable by default. Run `taskledger next-action`; if it reports `implement-resume`, use `taskledger implement resume --reason "Continue imported implementation."`.

11. Mutation commands (`todo add`, `todo done`, `todo undone`, `implement finish`) emit compact acknowledgements. For full task or todo detail, use `task show TASK_REF`, `task show` for the active task, `status`, `next-action`, or `todo show`.
    Example human output:

```text
todo-work: Implementation is in progress; 1 todos remain.
Next todo: todo-0001 -- Update next-action JSON payload.
Command: taskledger todo show todo-0001
Mark todo done after evidence exists: taskledger todo done todo-0001 --evidence "..."
Progress: 0/1 todos done
```

## User-requested review protocol

When the user asks to review, audit, check, verify, or assess an implementation
or completed task, treat the output as durable review evidence, not as
chat-only commentary.

1. Run the fresh context entry protocol and resolve the task explicitly.
2. Inspect the relevant task context, todos, implementation run, changed files,
   validation evidence, and user-provided review material.
3. Write the final review summary to a markdown file outside `.taskledger/`,
   for example `/tmp/taskledger-review-TASK_ID.md`.
4. Record the review before answering:
   `taskledger review record --task TASK_ID --result pass|fail|blocked --summary-file /tmp/taskledger-review-TASK_ID.md`
5. Verify persistence with `taskledger review list --task TASK_ID` or
   `taskledger review show REVIEW_ID --task TASK_ID`.
6. Include the recorded review id in the final response.

Use `pass` only when no blocking issues were found. Use `fail` when the
review finds a blocking implementation or acceptance-criteria problem. Use
`blocked` when evidence is insufficient, the review is incomplete, or a
required test/evidence gap remains.

Do not skip `review record` merely because the task is already `done`;
post-completion review records are allowed. Skip recording only when the
user explicitly requested read-only review, the task has no implementation
run, the task is archived and must not be mutated, or taskledger cannot
run. If skipped, state the reason explicitly.

## Actor and harness protocol

1. Before mutating taskledger state, verify identity with `taskledger actor whoami`.
2. If identity is wrong, use `taskledger actor set --type <type> --name <name> [--role <role>] [--tool <tool>]` and `taskledger harness set --name <name> [--kind <kind>]` to persist the correct identity.
3. Alternatively, set `TASKLEDGER_ACTOR_TYPE`, `TASKLEDGER_ACTOR_NAME`, `TASKLEDGER_ACTOR_ROLE`, `TASKLEDGER_HARNESS`, and `TASKLEDGER_SESSION_ID` environment variables. Env vars take priority over stored values.
4. Use `taskledger actor clear` and `taskledger harness clear` to remove stored identity and revert to env/auto-detection.
5. Never claim to be a user unless the user explicitly instructed it.
6. User-only actions remain user-only: plan approval, acceptance criterion waivers, and dependency waivers.
7. For handoffs, use `--intended-actor` and `--intended-harness` to document the target actor and harness.

## CLI failure protocol

If any `taskledger ...` command fails with a Python traceback before taskledger emits a normal human or JSON error:

1. Stop issuing mutating taskledger commands immediately.
2. Do not retry the same mutation with different text.
3. Run exactly one read-only health probe: `taskledger actor whoami`.
4. If the health probe fails with the same import traceback, report that taskledger CLI startup is broken and no ledger mutation was recorded.
5. If the health probe succeeds, rerun the failed command once, then continue.
6. For repeated setup mutations, prefer batch commands such as `question add-many` when available.
7. If a command fails with a usage/parse error, do not retry a mutating command by dropping the target selector. Inspect `--help` and use explicit targeting:
   - task-resource commands: `taskledger task show TASK_REF`, `taskledger task cancel TASK_REF --reason "..."`, `taskledger task uncancel TASK_REF --reason "..."`
   - workflow commands: `taskledger plan start --task TASK_REF`, `taskledger implement start --task TASK_REF`, `taskledger validate start --task TASK_REF`

## Branch-scoped ledger protocol

- `.taskledger/` is ignored local state. `taskledger.toml` is checked in and
  stores the current `ledger_ref` and next task number.
- After creating a long-lived Git branch, run `taskledger ledger fork REF` and
  commit the `taskledger.toml` change with the branch work.
- Default commands read only the current ledger under
  `.taskledger/ledgers/<ledger_ref>/`.
- Duplicate logical task IDs in different ledgers are expected. Use
  `taskledger ledger adopt --from REF TASK_REF` when branch-local task history
  should be copied into the current ledger.

## Release changelog protocol

Use this protocol when the user asks for release notes, a changelog, or an update to `CHANGELOG.md`.

1. Do not inspect `.taskledger/` storage layout directly. Use taskledger commands:
   - `taskledger status`
   - `taskledger tree`
   - `taskledger release list`
   - `taskledger release show VERSION`
   - `taskledger storage where` when storage location matters
2. If the user gives a natural task range such as `task-0018 to task-0023`, treat it as an inclusive task range.
   - Prefer `taskledger release changelog VERSION --from-task task-0018 --until-task task-0023 ...` when available.
   - On older taskledger versions, convert it to the previous exclusive boundary only when safe, for example `--since-task task-0017 --until-task task-0023`.
3. Generate changelog source before editing:
   - `taskledger release changelog VERSION --since PREVIOUS_VERSION --until-task TASK --output /tmp/VERSION-changelog-source.md`
   - or `taskledger release changelog VERSION --from-task FIRST_TASK --until-task LAST_TASK --output /tmp/VERSION-changelog-source.md`
4. Inspect `Included done tasks` and `Omitted tasks`.
   - Do not silently include omitted tasks in final release notes.
   - If the user explicitly asks for an upcoming/draft release and wants non-done tasks included, rerun with the explicit draft/status option when available.
   - Otherwise report omitted tasks and ask for validation/completion before final release notes.
5. Do not invent a release date.
   - If the user says "upcoming", use an unreleased/placeholder heading unless a date is provided or a release tag already exists.
   - If the user provides a date, use that exact date.
6. When machine output is needed, `--json` is root-level:
   - correct: `taskledger --json task show task-0022`
   - incorrect: `taskledger task show task-0022 --json`
7. For detailed task evidence, use:
   - `taskledger task dossier TASK_REF --format markdown`
   - not `task show --verbose`.
8. Preserve the existing changelog structure.
   - Insert the new release section below `## Unreleased` and above the previous release.
   - Keep or reset the `Unreleased` section only according to the user's release state.
   - Do not leave an empty `## Unreleased` header.
9. After editing `CHANGELOG.md`, read it back and verify:
   - heading order is correct
   - no duplicate release heading exists
   - omitted/non-done tasks are either excluded or clearly marked as draft/unvalidated according to user intent

## Optional worker pipeline overlay

- Worker pipelines are optional project-local overlays, not mandatory lifecycle stages.
- No `[worker_pipeline]` config means no workflow change.
- Use `taskledger pipeline show`, `taskledger pipeline list`, and `taskledger pipeline next` to inspect the configured overlay.
- Use `taskledger context --worker STEP_ID` or `taskledger pipeline context STEP_ID` to render a worker-specific context on top of the existing base context.
- Use `taskledger handoff create --worker STEP_ID` to derive handoff mode and context from a configured worker step.
- In `guided` mode, inspect `taskledger next-action` for `worker_pipeline.next_step`, `context_command`, and `handoff_command` hints. These are advisory only; they do not add new lifecycle gates.
- For review worker steps, persist final review output with `taskledger review record --worker STEP_ID --result pass|fail|blocked --summary-file REVIEW.md` (or `--summary`).
- Reviewer worker steps (`spec-reviewer`, `code-reviewer`) may require `--scope task` when no focused run is available.
- Use `taskledger plan template --with-worker-pipeline --file ./plan.md` only when the project has an enabled worker pipeline and the task should use worker-tagged plan todos.
- `worker_step` on plan todos is valid only when the project has an enabled worker pipeline.

## Planning protocol

1. `taskledger task create "Short task request" --slug <slug>` when creating a fresh task.
2. For manually completed work (operational tasks, exploratory work, or tasks finished outside the task-first workflow), use `taskledger task record "Title" --summary "..." --change PATH:KIND:SUMMARY` to create a done task directly. **Never use `task record` as a shortcut for active task management**: it records already-completed work only, and does not acquire locks or replace the normal lifecycle gates.
3. `taskledger task activate <slug>` to activate the newly created task for planning.
4. For existing tasks, `taskledger task activate <slug>`.
5. `taskledger plan start`
   - At planning start, run `taskledger plan guidance`. If it prints guidance, follow it when drafting questions, acceptance criteria, todos, and validation hints. Treat it as advisory; never use it to bypass approval, validation, locks, or required user answers.
6. Add questions with `taskledger question add --text "..." --required-for-plan` when decisions are missing.
   - Use `taskledger question add-many --required-for-plan --text $'Question 1\nQuestion 2'` when you already know multiple questions.
7. Ask the questions directly in the harness chat. Do not ask the user to run `taskledger question answer`.
8. Stop after asking required questions; do not invent answers.
9. Required planning questions are user-blocking. Do not satisfy them from repository inference. Record required answers only from explicit user responses with `--source explicit_user_chat` (or `--from-user-chat`).
10. When the user answers in chat, record the answers yourself with `taskledger question answer-many` or `taskledger question answer`.
11. Run `taskledger question status` and review all answered questions with `taskledger question answers` before writing the plan.
12. Before reading source files to discover plan format, run `taskledger plan template --from-answers --file ./plan.md` when answered questions exist, or `taskledger plan template --file ./plan.md` for a fresh plan skeleton.
    - If the project has an enabled worker pipeline and this task should use worker-tagged todos, add `--with-worker-pipeline`.
13. If answered questions exist, write the next plan with `taskledger plan upsert --from-answers --file ./plan.md`.
14. Use `taskledger plan upsert --file ./plan.md` for plans that are not based on newly answered questions.
15. Never edit `.taskledger/` files directly. Treat `.taskledger/` as Taskledger private durable state.
16. To revise a proposed plan in `plan_review`, run:

- `taskledger plan revise`
- `taskledger plan export --version latest --file ./plan.md`
- edit `./plan.md`
- `taskledger plan upsert --file ./plan.md`
- For simple structured removals, prefer `taskledger plan amend ... --reason "..."`

17. Ensure the plan front matter includes `acceptance_criteria` and `todos`; approved plan todos materialize into the implementation checklist.
18. For diagnostic commands needed to build the plan, preserve their output in a linked artifact or use `taskledger plan command -- ...`.
19. A proposed plan must include concrete `acceptance_criteria` and `todos` in front matter unless the user explicitly says the task is trivial.
20. After writing the plan, do not run `taskledger repair lock`; planning locks are released by plan proposal/upsert. Run `taskledger next-action`.
21. After `taskledger plan upsert --from-answers`, run `taskledger question status`. If it still reports `Plan regeneration needed: True`, do not ask for approval. Inspect `taskledger question answers`, `taskledger plan show --version N`, and `taskledger doctor`.
22. Before asking the user to approve, run `taskledger plan review --version N` and paste or summarize the rendered review. Then run `taskledger plan lint --version N` if the review did not include lint. Do not record approval until the user explicitly approves.
23. Record approval only with clear user intent such as approve, accept, go ahead, or start implementation. Prefer `taskledger plan accept --version N --note "User approved in harness: ..."` for normal chat approval. Use `taskledger plan approve --version N --actor user --approval-source explicit_chat --note "..."` only when explicit actor/source metadata is needed (advanced).
24. Never replace a user-provided rich plan with only generated YAML criteria and todos. Preserve the user's plan body after the front matter and use front matter only to expose machine-readable fields to Taskledger.
25. A Taskledger plan is not just YAML front matter. The YAML block is for machine-readable `goal`, `acceptance_criteria`, `todos`, file links, and test commands. The rich human plan must remain as Markdown after the second `---`. Before approval, inspect `taskledger plan show --version N` or the saved `plan-vN.md` and verify that the accepted plan body is non-empty and contains the implementation rationale.

The plan file should use version ids like `plan-v1`, `plan-v2` in references. Do not use zero-padded forms.

## Implementation protocol

1. `taskledger context --for implementation --format markdown`
2. `taskledger implement start`
   - If validation already failed and the plan is still correct, prefer `taskledger implement restart --summary "Fix failed validation findings."`
   - If implementation start fails because another run is already running, stop and run `taskledger doctor`, not only `taskledger doctor locks`.
   - Do not edit project code until implementation has started or a valid implementation resume command succeeds.
3. `taskledger implement checklist` - review the mandatory and optional todo checklist before starting.
4. If no todos exist, create a concrete checklist: `taskledger todo add --text "..."`. Todo source is inferred automatically from the active lock: `implementer` during implementation, `planner` during planning, `user` otherwise.
5. Work one todo at a time:
   - Make the code changes
   - `taskledger implement change --path ... --kind edit --summary "..."`
   - Run verification through `taskledger implement command -- ...` so exit code and output are recorded.
   - `implement command` mirrors the inner command exit code by default. Use `--allow-failure` when you intentionally want to record a non-zero command without failing the wrapper command.
   - Mark each todo done only after the relevant command or inspection evidence exists: `taskledger todo done <todo-id> --evidence "check-NNNN exited 0"`.
   - Optional: add `--source planner|implementer|user` to override the inferred source, though this is rarely needed.
6. `taskledger implement checklist` after each meaningful change to track progress.
7. In Git workspaces, prefer `taskledger implement scan-changes --from-git --summary "..."` before `implement finish` so change evidence includes a git-backed reconciliation checkpoint.
8. Do not run `implement finish` until `todo status` says all todos are complete.
9. `taskledger implement finish --summary "Completed all implementation todos..."`
10. For any user-requested review, record durable code review evidence after implementation with `taskledger review record ...` before answering; this is allowed before validation starts or after the task is already `done`.

**Critical**: `implement finish` will block until all non-skipped todos are done. Use `todo status` to verify readiness.

## Post-completion follow-up deltas

When a task is done and the user requests a small later change, do not reopen or mutate the completed task. Create a follow-up task linked to the completed parent:

```bash
taskledger task follow-up PARENT_REF "Short delta title" --description "..." --activate
```

Then run the normal compact lifecycle on the follow-up task. Keep the plan small, but preserve approval, implementation evidence, and validation evidence.

## Compact implementation loop

For routine same-session implementation, prefer the next action and the single
next todo over a broad generated context read:

```bash
taskledger --json next-action
taskledger --json todo next
taskledger todo show todo-0003
# implement only that todo
pytest tests/...
taskledger todo done todo-0003 --evidence "pytest tests/... passed"
taskledger --json next-action
```

Rules for agents:

1. Prefer `next-action` and `todo next` over generated context during normal work.
2. Use `validation_hint` before marking a todo done.
3. Mark a todo done only after evidence exists.
4. Record concise evidence.
5. Do not create handoffs or context bundles unless the user explicitly asked to switch harness or session.

## Which read command to use

| Need                      | Command                                             |
| ------------------------- | --------------------------------------------------- |
| Fresh session summary     | `usage`                                             |
| Next step                 | `next-action`                                       |
| Next implementation item  | `todo next`                                         |
| Active task summary       | `task show`                                         |
| Specific task summary     | `task show TASK_REF` or `task show --task TASK_REF` |
| Project/ledger overview   | `status`, `tree`                                    |
| Storage location          | `storage where`                                     |
| Sync safety check         | `sync preflight`                                    |
| Human dashboard           | `monitor`                                           |
| Reviewable report         | `task report`                                       |
| LLM/agent compiled export | `task export`                                       |
| Fresh worker context      | `context` or durable `handoff show`                 |
| Command audit             | `task transcript`                                   |

`task dossier`, root `view`, and legacy `handoff *-context` renderers remain
advanced/compatibility read surfaces. Prefer `context --for ...` and
`handoff show` for new agent protocols. Use `file status TASK_REF` when you need
linked-file drift checks.

## Validation protocol

1. `taskledger context --for validation --format markdown`
2. `taskledger validate start`
3. Check `taskledger validate status` to see current validation state and blockers.
4. Run verification checks outside taskledger.
5. Record criterion results: `taskledger validate check --criterion ac-0001 --status pass|fail|warn|not_run --evidence "..."`
6. Optionally waive criteria with user authority: `taskledger validate waive --criterion ac-0001 --reason "..."`.
7. Check `taskledger validate status` again to confirm all mandatory gates pass.
8. Finish with `taskledger validate finish --result passed|failed|blocked --summary "..."`

### Recovery Rules

- If validation fails, record the failure and do not hide it.
- Do not treat code review summaries as validation evidence unless the validation stage records criterion checks separately.
- Run `taskledger validate status` to inspect all blocking issues before finishing.
- If validation fails because implementation has a bug, finish validation as failed, run `taskledger next-action`, then restart implementation with `taskledger implement restart`. Use implementation context or an implementation handoff for the next actor.

### Waiver Rules

- Only user actors can waive acceptance criteria.
- Each waiver must include a reason and is permanently recorded in the validation history.
- Waived criteria are marked as satisfied for gate checking but remain visible in status reports.

## Opaque links and external artifacts

Taskledger stores task-local work state and opaque links. Cross-ledger
semantics belong to an organizer such as ledgerdeck. Use `taskledger link`
or `taskledger file` for references to external artifacts; taskledger does
not interpret those references.

```bash
taskledger link add --url specs/behavior/features/checkout/payment.feature --label "behavior spec"
taskledger file link specs/behavior/features/checkout/payment.feature --kind doc --label "behavior spec"
taskledger validate check --criterion ac-0001 --status pass --evidence "pytest tests/test_checkout_payment.py::test_payment_flow"
```

## Required logging

- Every implementation run must have a todo checklist unless the user explicitly says the task is too small.
- Log every meaningful implementation change with `taskledger implement change`.
- Record deviations from the approved plan with `taskledger implement deviation`.
- Mark todos done with evidence: `taskledger todo done <todo-id> --evidence "pytest -q"`.
- When transcript logging is enabled in project config, run task-relevant commands through `taskledger plan command -- ...` or `taskledger implement command -- ...` so stdout/stderr becomes durable transcript evidence.
- Do not paste secrets into command arguments, evidence strings, or expected command output when transcript logging is enabled.
- Use `taskledger handoff create --mode implementation|validation --intended-actor agent --intended-harness codex` when switching actor or harness.
- Use `taskledger handoff claim handoff-0001` before continuing work from a handoff.
- Use `taskledger file add --path ... --kind code|test|doc|config|dir|other` for files that matter.
- Store failed validation; do not hide it.

## Fresh-worker context protocol

Use focused contexts for one-worker tasks:

- Implement one todo:
  `taskledger context --for implementer --todo todo-0003`
- Review spec compliance for an implementation run:
  `taskledger context --for spec-reviewer --run run-0008`
- Review code quality for an implementation run:
  `taskledger context --for code-reviewer --run run-0008`
- Store durable handoff context before switching harness:
  `taskledger handoff create --mode implementation --todo todo-0003`

## Handoff protocol

Use durable handoffs when switching harnesses or switching between human and agent work.

To hand work to another actor:

1. Run `taskledger handoff create --mode implementation|validation --intended-actor agent|user --intended-harness codex --summary "..."`
2. Do not break a lock for normal transfer.
3. Tell the receiving actor to claim the handoff before continuing.

To receive work:

1. Run `taskledger actor whoami`.
2. Run `taskledger handoff claim handoff-0001`.
3. Run `taskledger next-action`.
4. Run `taskledger context --for implementation|validation --format markdown`.

## Never do these things

- Do not finish implementation while `taskledger todo status` shows open, active, or blocked todos.
- Do not skip mandatory todos unless the user explicitly authorizes the skip with a reason.
- Do not rely on prior chat context when a taskledger handoff exists; claim and read the durable context.

## Failure handling

- If an implementation lock has expired between sessions and the run is still resumable, use `taskledger implement resume --repair-expired-lock --reason "..."`. This is the normal fresh-session continuation path for expired implementation locks.
- If a lock is stale, inspect it first with `taskledger lock show` or `taskledger next-action` (both return a `classification`), then run `taskledger repair lock --reason "..."` only when diagnostics prove corruption, expiry, or a dead local holder PID. Use generic `repair lock` only when `doctor`/`lock show` confirms corrupted or orphaned state, not for normal expired implementation locks.

Lock recovery decision tree:

1. Run `taskledger lock show --task TASK` or `taskledger next-action`.
2. If there is no lock, follow `next-action`.
3. If `classification` is `expired` and it is an implementation lock for a running run: run `taskledger implement resume --repair-expired-lock --task TASK --reason "..."`.
4. If `classification` is `active_dead_local_process`: run `taskledger repair lock --task TASK --reason "Holder PID ... is no longer running."`, then `taskledger implement resume --task TASK --reason "..."`.
5. If `classification` is `active_live_local_process` or `active_other_actor`: do not repair; use a handoff or wait for the holder to release.
6. If `classification` is `active_unverifiable_remote_or_unknown_process`: do not infer staleness from local process checks; inspect handoffs or ask the user before repairing.

`--repair-expired-lock` is not a general stale-lock takeover flag. It only handles locks whose `expires_at` is in the past. For non-expired active locks, use the classification returned by `lock show` or `next-action`.

- If breaking an implementation lock leaves a running implementation run behind, use `taskledger implement resume --reason "..."` instead of `implement start`.
- If a cancelled task is restored with `task uncancel`, run `taskledger next-action` before starting work. If the task still has a running implementation run, resume that run instead of starting a new one.
- If `taskledger next-action` recommends a command but `taskledger can <action>` rejects it, treat this as a lifecycle inconsistency. Run `taskledger doctor` and follow the repair guidance.
- Use `taskledger repair run --task TASK --run RUN --reason "..."` only when diagnostics identify an orphaned running planning run with no matching active lock.
- If doctor reports a running implementation run with no matching lock and the task is still resumable, run `taskledger implement resume --task TASK --run RUN --reason "Reacquire implementation lock."`.
- Never use repair to bypass approval, validation, or active implementation locks.
- If validation fails, record the failure and return to implementation or replanning.
- If indexes are stale, run `taskledger repair index`; `taskledger reindex` is a compatibility alias.
- If a task is truly cancelled and the user wants to continue, use `taskledger task uncancel --task TASK_REF --reason "..." [--to STAGE]` to restore a safe durable stage before re-entering an active stage.
- If dependencies must be bypassed, only a user waiver may unblock implementation.

## Transcript review mode

Use transcript review rendering for fast post-run diagnosis:

```bash
taskledger task transcript --task TASK_REF
taskledger task transcript --task TASK_REF --raw
taskledger task transcript --task TASK_REF --failures
```

Review mode is the default. Use `--raw` when full per-record audit rows are needed.

## Command examples

```bash
taskledger actor whoami
taskledger actor set --type agent --name my-agent --role implementer
taskledger actor clear
taskledger harness set --name pi --kind agent_harness
taskledger harness clear
taskledger task create "Parser fix" --slug parser-fix
taskledger task follow-up parser-fix "Rename parser copy" --description "Small post-completion delta." --activate
taskledger question add --text "Should legacy storage be removed?" --required-for-plan
taskledger question add-many --required-for-plan --text $'What release boundary should be used?\nShould the changelog include validation evidence?'
taskledger question answer --question q-0001 --text "No." --from-user-chat
taskledger question answer-many --text $'q-0001: No.\nq-0002: Yes.' --from-user-chat
taskledger question answer-many --text "q-0001: No." --text "q-0002: Yes." --from-user-chat
taskledger question answer-many --file answers.yaml --source explicit_user_chat
taskledger question status
taskledger question answers
taskledger question list --status answered
taskledger next-action
# Read advisory planning guidance before drafting plan content.
taskledger plan guidance
taskledger plan template --from-answers --file ./plan.md
taskledger plan upsert --from-answers --file ./plan.md
taskledger plan review --version 1
taskledger plan lint --version 1
taskledger plan accept --version 1 --note "User approved in harness."
taskledger context --for implementation --format markdown
taskledger context --for implementer --todo todo-0003
taskledger context --for spec-reviewer --run run-0008
taskledger context --for code-reviewer --run run-0008
taskledger review record --worker code-review --from-git --result pass --summary-file ./REVIEW.md
taskledger release tag 0.4.1 --at-task task-0030 --note "0.4.1 released"
taskledger release list
taskledger release show 0.4.1
taskledger release changelog 0.4.2 --since 0.4.1 --until-task task-0035 --output /tmp/taskledger-0.4.2-changelog-source.md
taskledger release changelog 0.4.2 --from-task task-0031 --until-task task-0035 --output /tmp/taskledger-0.4.2-changelog-source.md
taskledger --json release changelog 0.4.2 --since 0.4.1 --until-task task-0035
taskledger task dossier task-0035 --format markdown
taskledger import ./taskledger-transfer.tar.gz --dry-run
taskledger export --task task-0040
taskledger export task-0040 -o ./task0040.tar.gz
taskledger import ./task0040.tar.gz --id-policy renumber-on-conflict
taskledger ledger status
taskledger ledger fork feature-a
taskledger ledger switch main
taskledger ledger adopt --from feature-a task-0030
taskledger ledger doctor
taskledger storage where
taskledger sync preflight
taskledger sync status
taskledger sync export --output ./taskledger-transfer.tar.gz
taskledger sync import ./taskledger-transfer.tar.gz --dry-run
taskledger sync git status
taskledger sync git pull
taskledger sync git push
taskledger sync git push --message "Checkpoint task state."
taskledger implement resume --reason "Reacquire implementation lock for existing running run."
taskledger implement resume --repair-expired-lock --reason "Continue after expired lock."
taskledger implement restart --summary "Fix failed validation findings."
taskledger implement change --path taskledger/services/tasks.py --kind edit --summary "Hardened validation gates."
taskledger task uncancel --task TASK_REF --actor agent --allow-agent-uncancel --reason "User explicitly requested continuation in harness."
taskledger todo done todo-0001 --evidence "uv run pytest -q" --artifact tests/test_parser.py
taskledger validate check --criterion ac-0001 --status pass --evidence "uv run pytest -q"
taskledger handoff create --mode implementation --todo todo-0003 --intended-actor agent --intended-harness codex --summary "Ready for focused implementation."
taskledger handoff create --mode validation --intended-actor agent --intended-harness codex --summary "Ready for validation."
taskledger task dossier --format markdown
taskledger task export task-0030 -o task-0030.llm.md
```

## Task-centered traceability

Taskledger owns temporal work truth. Cross-ledger links are opaque file or
ID references.

Use `taskledger trace TASK --format json` for a read-only `taskledger.trace.v1`
bundle that exposes task IDs, accepted AC IDs, opaque link refs, source refs,
evidence refs, implementation/review refs, and handoffs.
