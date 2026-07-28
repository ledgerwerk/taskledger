"""Command metadata inventory."""

from __future__ import annotations

from typing import NamedTuple

# ── audience constants ────────────────────────────────────────────────
STABLE_FOR_AGENTS = "stable_for_agents"
BETA_FOR_AGENTS = "beta_for_agents"
HUMAN_ORIENTED = "human_oriented"
REPAIR = "repair"

# ── surface constants ─────────────────────────────────────────────────
PRIMARY = "primary"
SUPPORT = "support"
ADVANCED = "advanced"
HUMAN = "human"
REPAIR_SURFACE = "repair"
MIGRATION = "migration"
BETA = "beta"

# ── phase constants ───────────────────────────────────────────────────
PHASE_SETUP = "setup"
PHASE_PLANNING = "planning"
PHASE_APPROVAL = "approval"
PHASE_IMPLEMENTATION = "implementation"
PHASE_REVIEW = "review"
PHASE_VALIDATION = "validation"
PHASE_REPORTING = "reporting"
PHASE_TRANSFER = "transfer"
PHASE_RELEASE = "release"
PHASE_REPAIR = "repair"
PHASE_SEARCH = "search"

# ── tier constants ────────────────────────────────────────────────────
TIER_CRITICAL = "critical"
TIER_NORMAL = "normal"
TIER_RARE = "rare"

# ── effect constants ─────────────────────────────────────────────────
EFFECT_NONE = "none"
EFFECT_READ = "read"
EFFECT_WRITE = "write"
EXTERNAL_NONE = "none"
EXTERNAL_FILE_WRITE = "file_write"
EXTERNAL_PROCESS_EXEC = "process_exec"
EXTERNAL_SERVER_SOCKET = "server_socket"
TARGETING_NONE = "none"
TARGETING_ACTIVE_DEFAULT = "active_default"
TARGETING_EXPLICIT_TASK_OPTION = "explicit_task_option"
TARGETING_POSITIONAL_RESOURCE = "positional_resource"
TARGETING_POSITIONAL_OR_ACTIVE = "positional_resource_or_active"
TARGETING_EXPLICIT_REQUIRED = "explicit_target_required"

AGENT_GOLDEN_PATH_COMMANDS: tuple[str, ...] = (
    "actor whoami",
    "usage",
    "task active",
    "task show",
    "task create",
    "task activate",
    "task follow-up",
    "next-action",
    "context",
    "trace",
    "can",
    "plan start",
    "plan template",
    "plan upsert",
    "plan lint",
    "plan accept",
    "question add",
    "question add-many",
    "question answer",
    "question answer-many",
    "question status",
    "question answers",
    "todo next",
    "todo show",
    "todo done",
    "todo status",
    "implement start",
    "implement resume",
    "implement change",
    "implement scan-changes",
    "implement finish",
    "implement snapshot refresh",
    "validate start",
    "validate status",
    "validate check",
    "validate finish",
    "review record",
    "handoff create",
    "handoff show",
    "handoff claim",
    "handoff close",
)


class CommandSpec(NamedTuple):
    audience: str
    effect: str
    surface: str
    phase: str
    tier: str = TIER_NORMAL
    deprecated: bool = False
    replaced_by: str = ""
    ledger_effect: str = ""
    workspace_effect: str = ""
    external_effect: str = ""
    agent_safe: bool = True
    targeting: str = TARGETING_NONE


COMMAND_METADATA: dict[str, CommandSpec] = {
    # ── setup / identity ──────────────────────────────────────────
    "actor whoami": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_SETUP,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
    ),
    "actor set": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_SETUP,
        ledger_effect=EFFECT_WRITE,
    ),
    "actor clear": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_SETUP,
        ledger_effect=EFFECT_WRITE,
    ),
    "harness set": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_SETUP,
        ledger_effect=EFFECT_WRITE,
    ),
    "harness clear": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_SETUP,
        ledger_effect=EFFECT_WRITE,
    ),
    # ── orientation ───────────────────────────────────────────────
    "init": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_SETUP,
        ledger_effect=EFFECT_WRITE,
    ),
    "next-action": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_REPORTING,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
    ),
    "can": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
    ),
    "context": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_REPORTING,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
    ),
    "trace": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
    ),
    "config list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_SETUP,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
    ),
    "config show": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_SETUP,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
    ),
    "config get": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_SETUP,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
    ),
    "config keys": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_SETUP,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
    ),
    "config describe": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_SETUP,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
    ),
    "config set": CommandSpec(
        STABLE_FOR_AGENTS,
        "workspace_mutation",
        SUPPORT,
        PHASE_SETUP,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "config validate": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_SETUP,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
    ),
    "config unset": CommandSpec(
        STABLE_FOR_AGENTS,
        "workspace_mutation",
        SUPPORT,
        PHASE_SETUP,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "pipeline show": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
    ),
    "pipeline list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
    ),
    "pipeline next": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
        targeting=TARGETING_ACTIVE_DEFAULT,
    ),
    "pipeline context": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
        targeting=TARGETING_ACTIVE_DEFAULT,
    ),
    # ── task management ───────────────────────────────────────────
    "task create": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "task activate": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_POSITIONAL_RESOURCE,
    ),
    "task deactivate": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "task follow-up": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "task record": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "task active": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_REPORTING,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
    ),
    "task show": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_REPORTING,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
        targeting=TARGETING_POSITIONAL_OR_ACTIVE,
    ),
    "task list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
    ),
    "task edit": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_EXPLICIT_REQUIRED,
    ),
    "task cancel": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_EXPLICIT_REQUIRED,
    ),
    "task uncancel": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_EXPLICIT_REQUIRED,
    ),
    "task close": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_POSITIONAL_OR_ACTIVE,
    ),
    "task archive": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_REPORTING,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_POSITIONAL_RESOURCE,
    ),
    "task unarchive": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_REPORTING,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_POSITIONAL_RESOURCE,
    ),
    "task events": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        ADVANCED,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
        targeting=TARGETING_POSITIONAL_OR_ACTIVE,
    ),
    # ── planning ──────────────────────────────────────────────────
    "plan start": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_PLANNING,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_ACTIVE_DEFAULT,
    ),
    "plan template": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_PLANNING,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_NONE,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "plan guidance": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_PLANNING,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
    ),
    "plan upsert": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_PLANNING,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_WRITE,
    ),
    "plan lint": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_PLANNING,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
    ),
    "plan check": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_PLANNING,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
    ),
    "plan schema": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_NONE,
    ),
    "plan show": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_READ,
    ),
    "plan review": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_APPROVAL,
        ledger_effect=EFFECT_READ,
        external_effect=EXTERNAL_FILE_WRITE,
        targeting=TARGETING_ACTIVE_DEFAULT,
    ),
    "plan export": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_READ,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "plan list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_READ,
    ),
    "plan diff": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_READ,
    ),
    "plan draft": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_NONE,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "plan propose": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "plan regenerate": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "plan materialize-todos": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "plan command": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "plan revise": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "plan amend": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "plan reject": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_APPROVAL,
        ledger_effect=EFFECT_WRITE,
    ),
    # ── approval ──────────────────────────────────────────────────
    "plan accept": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_APPROVAL,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_WRITE,
    ),
    "plan approve": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_APPROVAL,
        ledger_effect=EFFECT_WRITE,
    ),
    # ── questions ─────────────────────────────────────────────────
    "question add": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "question add-many": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "question answer": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_POSITIONAL_RESOURCE,
    ),
    "question answer-many": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "question status": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_PLANNING,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
    ),
    "question answers": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_PLANNING,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
    ),
    "question list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_READ,
    ),
    "question open": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_READ,
    ),
    "question dismiss": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    # ── implementation ────────────────────────────────────────────
    "implement start": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_IMPLEMENTATION,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_ACTIVE_DEFAULT,
    ),
    "implement restart": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_WRITE,
    ),
    "implement resume": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_IMPLEMENTATION,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_WRITE,
    ),
    "implement checklist": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_IMPLEMENTATION,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
    ),
    "implement command": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_IMPLEMENTATION,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "implement change": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_IMPLEMENTATION,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_WRITE,
    ),
    "implement scan-changes": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_WRITE,
    ),
    "implement finish": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_WRITE,
    ),
    "implement snapshot": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_NONE,
    ),
    "implement snapshot refresh": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_ACTIVE_DEFAULT,
    ),
    "implement show": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_READ,
    ),
    "implement status": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_READ,
    ),
    "implement log": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_WRITE,
    ),
    "implement deviation": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_WRITE,
    ),
    "implement artifact": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_WRITE,
    ),
    # ── todos ─────────────────────────────────────────────────────
    "todo add": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_WRITE,
    ),
    "todo done": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_IMPLEMENTATION,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_POSITIONAL_RESOURCE,
    ),
    "todo undone": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_WRITE,
    ),
    "todo next": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_IMPLEMENTATION,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
    ),
    "todo status": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_READ,
    ),
    "todo show": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_READ,
    ),
    "todo list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_IMPLEMENTATION,
        ledger_effect=EFFECT_READ,
    ),
    # ── validation ────────────────────────────────────────────────
    "validate start": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_VALIDATION,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_ACTIVE_DEFAULT,
    ),
    "validate status": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_VALIDATION,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_READ,
    ),
    "validate check": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_VALIDATION,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_WRITE,
    ),
    "validate finish": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_VALIDATION,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_WRITE,
    ),
    "validate waive": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_VALIDATION,
        ledger_effect=EFFECT_WRITE,
    ),
    "validate show": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_VALIDATION,
        ledger_effect=EFFECT_READ,
    ),
    # ── review ────────────────────────────────────────────────────
    "review record": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_REVIEW,
        tier=TIER_CRITICAL,
        ledger_effect=EFFECT_WRITE,
    ),
    "review list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REVIEW,
        ledger_effect=EFFECT_READ,
    ),
    "review show": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REVIEW,
        ledger_effect=EFFECT_READ,
    ),
    # ── handoffs ──────────────────────────────────────────────────
    "handoff create": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
    ),
    "handoff claim": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
    ),
    "handoff close": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        PRIMARY,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
    ),
    "handoff show": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
        targeting=TARGETING_POSITIONAL_RESOURCE,
    ),
    "handoff list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
    ),
    "handoff cancel": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
    ),
    "handoff plan-context": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        ADVANCED,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
    ),
    "handoff implementation-context": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        ADVANCED,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
    ),
    "handoff validation-context": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        ADVANCED,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
    ),
    # ── human-oriented reads ──────────────────────────────────────
    "status": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        HUMAN,
        PHASE_REPORTING,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
    ),
    "view": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        HUMAN,
        PHASE_REPORTING,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
    ),
    "usage": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_SETUP,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        targeting=TARGETING_POSITIONAL_OR_ACTIVE,
    ),
    "monitor": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_REPORTING,
        agent_safe=False,
        ledger_effect=EFFECT_READ,
        targeting=TARGETING_POSITIONAL_OR_ACTIVE,
    ),
    "tree": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        HUMAN,
        PHASE_REPORTING,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
    ),
    "task dossier": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        HUMAN,
        PHASE_REPORTING,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        targeting=TARGETING_POSITIONAL_OR_ACTIVE,
    ),
    "task report": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_REPORTING,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        external_effect=EXTERNAL_FILE_WRITE,
        targeting=TARGETING_POSITIONAL_OR_ACTIVE,
    ),
    "task export": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        HUMAN,
        PHASE_REPORTING,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        external_effect=EXTERNAL_FILE_WRITE,
        targeting=TARGETING_POSITIONAL_OR_ACTIVE,
    ),
    "task transcript": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_REPORTING,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        targeting=TARGETING_POSITIONAL_OR_ACTIVE,
    ),
    "commands": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_REPORTING,
        agent_safe=True,
        ledger_effect=EFFECT_NONE,
    ),
    # ── references / metadata ─────────────────────────────────────
    "file add": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "file link": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
        workspace_effect=EFFECT_READ,
        targeting=TARGETING_EXPLICIT_REQUIRED,
    ),
    "file remove": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "file list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
    ),
    "file status": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
        targeting=TARGETING_EXPLICIT_REQUIRED,
    ),
    "file refresh": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
        workspace_effect=EFFECT_READ,
        targeting=TARGETING_EXPLICIT_REQUIRED,
    ),
    "ref show": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
    ),
    "ref parse": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
    ),
    "link add": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "link remove": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "link list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
    ),
    "intro create": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "intro link": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "intro list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
    ),
    "intro show": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
    ),
    "require add": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
        targeting=TARGETING_POSITIONAL_RESOURCE,
    ),
    "require remove": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    "require list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
    ),
    "require waive": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_PLANNING,
        ledger_effect=EFFECT_WRITE,
    ),
    # ── project transfer / ledgers ────────────────────────────────
    "export": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "import": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "snapshot": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "ledger status": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
    ),
    "ledger list": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
    ),
    "ledger fork": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
    ),
    "ledger switch": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
    ),
    "ledger adopt": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
    ),
    "ledger doctor": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        ADVANCED,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
    ),
    "storage where": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
    ),
    "storage validate": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        PRIMARY,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
    ),
    "storage set": CommandSpec(
        STABLE_FOR_AGENTS,
        "workspace_mutation",
        PRIMARY,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "storage clear-override": CommandSpec(
        STABLE_FOR_AGENTS,
        "workspace_mutation",
        PRIMARY,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "storage migration": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
    ),
    "storage migration status": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
    ),
    "storage migration recover": CommandSpec(
        HUMAN_ORIENTED,
        "workspace_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "storage move": CommandSpec(
        HUMAN_ORIENTED,
        "workspace_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "sync preflight": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "sync status": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "sync commit": CommandSpec(
        HUMAN_ORIENTED,
        "workspace_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "sync export": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        SUPPORT,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "sync import": CommandSpec(
        STABLE_FOR_AGENTS,
        "ledger_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "sync git": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_NONE,
    ),
    "sync git init": CommandSpec(
        HUMAN_ORIENTED,
        "workspace_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_WRITE,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "sync git status": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "sync git cd": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
    ),
    "sync git path": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
    ),
    "sync git import-local": CommandSpec(
        HUMAN_ORIENTED,
        "workspace_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        deprecated=True,
        replaced_by="migrate apply",
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "sync git commit": CommandSpec(
        HUMAN_ORIENTED,
        "workspace_mutation",
        HUMAN,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "sync git export-local": CommandSpec(
        HUMAN_ORIENTED,
        "workspace_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        deprecated=True,
        replaced_by="migrate apply",
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "sync git pull": CommandSpec(
        HUMAN_ORIENTED,
        "workspace_mutation",
        HUMAN,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "sync git push": CommandSpec(
        HUMAN_ORIENTED,
        "workspace_mutation",
        HUMAN,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "sync git sync": CommandSpec(
        HUMAN_ORIENTED,
        "workspace_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        deprecated=True,
        replaced_by="sync git cd",
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_PROCESS_EXEC,
    ),
    "sync git hooks": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_NONE,
    ),
    "sync git hooks install": CommandSpec(
        HUMAN_ORIENTED,
        "workspace_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "sync git hooks status": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    "sync git hooks uninstall": CommandSpec(
        HUMAN_ORIENTED,
        "workspace_mutation",
        ADVANCED,
        PHASE_TRANSFER,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_WRITE,
        external_effect=EXTERNAL_FILE_WRITE,
    ),
    # ── release ───────────────────────────────────────────────────
    "release tag": CommandSpec(
        HUMAN_ORIENTED,
        "ledger_mutation",
        ADVANCED,
        PHASE_RELEASE,
        agent_safe=True,
        ledger_effect=EFFECT_WRITE,
    ),
    "release list": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_RELEASE,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
    ),
    "release show": CommandSpec(
        HUMAN_ORIENTED,
        "safe_read_only",
        HUMAN,
        PHASE_RELEASE,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        targeting=TARGETING_POSITIONAL_RESOURCE,
    ),
    # changelog + build removed; changelog belongs to releaseledger.
    # ── search ────────────────────────────────────
    "search": CommandSpec(
        BETA_FOR_AGENTS,
        "safe_read_only",
        BETA,
        PHASE_SEARCH,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
    ),
    "grep": CommandSpec(
        BETA_FOR_AGENTS,
        "safe_read_only",
        BETA,
        PHASE_SEARCH,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
    ),
    "symbols": CommandSpec(
        BETA_FOR_AGENTS,
        "safe_read_only",
        BETA,
        PHASE_SEARCH,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
    ),
    "deps": CommandSpec(
        BETA_FOR_AGENTS,
        "safe_read_only",
        BETA,
        PHASE_SEARCH,
        ledger_effect=EFFECT_NONE,
        workspace_effect=EFFECT_READ,
    ),
    # ── repair / doctor ───────────────────────────────────────────
    "doctor": CommandSpec(
        REPAIR,
        "safe_read_only",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_READ,
    ),
    "doctor locks": CommandSpec(
        REPAIR,
        "safe_read_only",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_READ,
    ),
    "doctor schema": CommandSpec(
        REPAIR,
        "safe_read_only",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_READ,
    ),
    "doctor indexes": CommandSpec(
        REPAIR,
        "safe_read_only",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_READ,
    ),
    "lock show": CommandSpec(
        REPAIR,
        "safe_read_only",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_READ,
    ),
    "lock list": CommandSpec(
        REPAIR,
        "safe_read_only",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_READ,
    ),
    "lock break": CommandSpec(
        REPAIR,
        "ledger_mutation",
        ADVANCED,
        PHASE_REPAIR,
        tier=TIER_RARE,
        deprecated=True,
        replaced_by="repair lock",
        ledger_effect=EFFECT_WRITE,
    ),
    "repair lock": CommandSpec(
        REPAIR,
        "ledger_mutation",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_WRITE,
    ),
    "repair index": CommandSpec(
        REPAIR,
        "ledger_mutation",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_WRITE,
    ),
    "repair run": CommandSpec(
        REPAIR,
        "ledger_mutation",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_WRITE,
    ),
    "repair task": CommandSpec(
        REPAIR,
        "ledger_mutation",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_WRITE,
    ),
    "repair task-dirs": CommandSpec(
        REPAIR,
        "ledger_mutation",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_WRITE,
    ),
    "repair planning-command-changes": CommandSpec(
        REPAIR,
        "ledger_mutation",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_WRITE,
    ),
    "repair project-identity": CommandSpec(
        REPAIR,
        "ledger_mutation",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_WRITE,
    ),
    "repair locks": CommandSpec(
        REPAIR,
        "ledger_mutation",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_WRITE,
    ),
    "migrate inspect": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        MIGRATION,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_READ,
    ),
    "migrate status": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        MIGRATION,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_READ,
    ),
    "migrate plan": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        MIGRATION,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_READ,
    ),
    "migrate apply": CommandSpec(
        REPAIR,
        "ledger_mutation",
        MIGRATION,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_WRITE,
    ),
    "migrate recover": CommandSpec(
        REPAIR,
        "ledger_mutation",
        MIGRATION,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_WRITE,
    ),
    "migrate cleanup": CommandSpec(
        REPAIR,
        "ledger_mutation",
        MIGRATION,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_WRITE,
    ),
    "help": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_SETUP,
        ledger_effect=EFFECT_NONE,
    ),
    "info": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        SUPPORT,
        PHASE_REPORTING,
        ledger_effect=EFFECT_READ,
    ),
    "runtime": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        MIGRATION,
        PHASE_SETUP,
        tier=TIER_RARE,
        ledger_effect=EFFECT_READ,
    ),
    "reindex": CommandSpec(
        REPAIR,
        "ledger_mutation",
        REPAIR_SURFACE,
        PHASE_REPAIR,
        tier=TIER_RARE,
        ledger_effect=EFFECT_WRITE,
    ),
    "storage path": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
    ),
    "config path": CommandSpec(
        STABLE_FOR_AGENTS,
        "safe_read_only",
        HUMAN,
        PHASE_TRANSFER,
        agent_safe=True,
        ledger_effect=EFFECT_READ,
        workspace_effect=EFFECT_READ,
    ),
}


# ── Family schema mapping helpers ─────────────────────────────────────


def _map_audience(audience: str) -> str:
    """Map Taskledger audience to family audience."""
    return {
        STABLE_FOR_AGENTS: "agent",
        BETA_FOR_AGENTS: "agent",
        HUMAN_ORIENTED: "human",
        REPAIR: "both",
    }.get(audience, "both")


def _map_stability(audience: str, deprecated: bool) -> str:
    """Map Taskledger audience/deprecated to family stability."""
    if deprecated:
        return "deprecated"
    return {
        STABLE_FOR_AGENTS: "stable",
        BETA_FOR_AGENTS: "beta",
        HUMAN_ORIENTED: "stable",
        REPAIR: "stable",
    }.get(audience, "stable")


def _map_effect(effect: str, external_effect: str) -> str:
    """Map Taskledger effect to family effect."""
    if external_effect == EXTERNAL_PROCESS_EXEC:
        return "external-process"
    if external_effect == EXTERNAL_FILE_WRITE:
        return "external-write"
    if effect == EFFECT_WRITE:
        return "workspace-write"
    if effect == "ledger_mutation":
        return "ledger-write"
    return "read"


def _map_requires_workspace(effect: str) -> bool:
    """Determine if command requires workspace."""
    return effect not in {EFFECT_NONE}


def _map_targeting(targeting: str) -> str:
    """Map Taskledger targeting to family targeting."""
    return {
        TARGETING_NONE: "none",
        TARGETING_ACTIVE_DEFAULT: "positional_resource_or_active",
        TARGETING_EXPLICIT_TASK_OPTION: "positional_resource_or_active",
        TARGETING_POSITIONAL_RESOURCE: "positional_resource",
        TARGETING_POSITIONAL_OR_ACTIVE: "positional_resource_or_active",
        TARGETING_EXPLICIT_REQUIRED: "positional_resource",
    }.get(targeting, "none")


def get_command_family_metadata(path: str) -> dict[str, object]:
    """Get family-schema metadata for a command path."""
    spec = COMMAND_METADATA.get(path)
    if spec is None:
        return {}
    return {
        "path": path,
        "summary": "",  # summaries come from command help text
        "audience": _map_audience(spec.audience),
        "stability": _map_stability(spec.audience, spec.deprecated),
        "effect": _map_effect(spec.effect, spec.external_effect),
        "requires_workspace": _map_requires_workspace(spec.effect),
        "requires_active_record": spec.targeting
        in {
            TARGETING_ACTIVE_DEFAULT,
            TARGETING_EXPLICIT_TASK_OPTION,
            TARGETING_POSITIONAL_OR_ACTIVE,
        },
        "targeting": _map_targeting(spec.targeting),
        "supports_json": True,
        "aliases": (),
        "deprecated": spec.deprecated,
        "replacement": spec.replaced_by or None,
        "extensions": {
            "taskledger": {
                "surface": spec.surface,
                "phase": spec.phase,
                "tier": spec.tier,
                "ledger_effect": spec.ledger_effect,
                "workspace_effect": spec.workspace_effect,
                "external_effect": spec.external_effect,
                "agent_safe": spec.agent_safe,
            }
        },
    }


def get_all_command_family_metadata() -> dict[str, dict[str, object]]:
    """Get family-schema metadata for all registered commands."""
    return {path: get_command_family_metadata(path) for path in COMMAND_METADATA}


# ── Command summaries (from CLI help text) ──────────────────────────────

COMMAND_SUMMARIES: dict[str, str] = {}


def register_command_summary(path: str, summary: str) -> None:
    """Register a command summary from CLI help text."""
    COMMAND_SUMMARIES[path] = summary


def get_command_summary(path: str) -> str:
    """Get a command summary, falling back to empty string."""
    return COMMAND_SUMMARIES.get(path, "")
