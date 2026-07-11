# Documentation freshness

Taskledger uses Documentledger to connect sections under `docs/` to the Python source units they describe. The committed `.documentledger.toml` defines the scan roots and validation commands. The committed `.documentledger/` records hold the current scan baseline, section links, tracked source hashes, and freshness state.

Do not edit `.documentledger/` records directly. Use the `docledger` commands below so record validation and versioning remain intact.

## Detect documentation affected by code changes

Run the freshness workflow from the repository root:

```bash
docledger --json status
docledger --json scan
docledger --json docs affected
docledger docs build-context --affected --print
```

Inspect each affected section and its linked changed source units before editing. Update only the affected sections unless the changed contract requires a broader consistency correction. The generated context also reports changed source files that have no documentation links. Review those files explicitly instead of treating an empty affected-section list as proof that no documentation work is needed.

## Maintain section links

Prefer links from one documentation section to the smallest source unit that owns the documented behavior. A CLI section should normally link to its command callback or owning CLI module. API reference sections should link to the corresponding public API module. Lifecycle and storage explanations may link to the owning service, policy, model, or storage module.

For a single edge, use `links add-section` with a source unit returned by `docledger sources list` or `docledger sources show`:

```bash
docledger links add-section \
  --doc docs/usage.md \
  --section planning-guidance-profiles \
  --source-unit py:module:taskledger/services/workflow_guidance.py \
  --coverage workflow \
  --impact behavior \
  --reason "Documents project planning guidance behavior."
```

For a reviewed set of links, write a `documentledger.mapping_proposal.v1` YAML file outside `.documentledger/`, validate it, and then apply it:

```bash
docledger links import-map --file /tmp/taskledger-doc-map.yaml --validate
docledger links import-map --file /tmp/taskledger-doc-map.yaml --apply
docledger --json links audit
```

Use broad file fallback links only when a precise Python unit is not meaningful. Do not add speculative links merely to eliminate unlinked-source output.

## Validate and mark sections fresh

The configured validation commands are authoritative for this documentation set. Run them after updating affected sections:

```bash
pytest tests/test_docs_and_skill.py tests/test_command_example_linter.py
sphinx-build -W -b html docs docs/_build/html
docledger --json links audit
```

Mark a section fresh only after its content and links have been validated against the latest scan:

```bash
docledger mark-fresh \
  --doc docs/usage.md \
  --section planning-guidance-profiles \
  --reason "Docs updated and validated after scan version 3."
```

Then run `docledger --json docs affected` again. A section-level mark updates its tracked source hashes immediately, so a follow-up scan is optional confirmation rather than a prerequisite for clearing affectedness.

## Review boundaries

Documentledger reports evidence, not documentation policy. Internal implementation units do not need links when a change cannot affect user, integrator, operator, or contributor documentation. Conversely, public CLI grammar, JSON contracts, lifecycle gates, public Python APIs, persisted storage behavior, transfer semantics, and operational recovery rules should have an owning documentation section and source link.
