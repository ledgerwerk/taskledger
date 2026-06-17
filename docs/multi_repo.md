# Multi-repo context

`taskledger` does not own repository checkout orchestration. It records the
task, links the files and external resources that matter, and renders handoff
context that another harness can use.

## Common workflow

Create or activate the task first:

```bash
taskledger init
taskledger task create "Fix sale customization" --description "Repair sale order behavior."
```

Attach files from the current workspace or from neighboring checkouts:

```bash
taskledger file add --path ../odoo/addons/sale/models/sale_order.py --kind code --label "Upstream sale order reference"
taskledger file add --path custom_sale/models/sale_order.py --kind code --label "Custom sale implementation" --required-for-validation
taskledger link add --url https://example.invalid/ticket/123 --label "Support ticket"
```

Use search helpers to inspect the workspace:

```bash
taskledger search sale_order
taskledger grep "action_confirm"
taskledger symbols sale_order.py
taskledger deps custom_sale.models.sale_order
```

Then render fresh context for the next stage:

```bash
taskledger context --for implementation --format markdown
taskledger handoff create --mode implementation --intended-actor agent --intended-harness codex
```

## Mental model

- `file add` records task-specific source and implementation files.
- `link add` records issue trackers, design notes, pull requests, or other
  external references.
- `search`, `grep`, `symbols`, and `deps` are read-only helpers.
- The active task remains explicit. Without an active task, task-scoped commands
  require `--task` or a positional task reference.
