from __future__ import annotations

from taskledger.cli import app
from taskledger.command_inventory import (
    COMMAND_METADATA,
    EFFECT_NONE,
    EFFECT_READ,
    EFFECT_WRITE,
    EXTERNAL_FILE_WRITE,
    EXTERNAL_PROCESS_EXEC,
    EXTERNAL_SERVER_SOCKET,
    HUMAN_ORIENTED,
    REPAIR,
    STABLE_FOR_AGENTS,
    TARGETING_ACTIVE_DEFAULT,
    TARGETING_EXPLICIT_REQUIRED,
    TARGETING_NONE,
    TARGETING_POSITIONAL_OR_ACTIVE,
    TARGETING_POSITIONAL_RESOURCE,
    TIER_CRITICAL,
    TIER_NORMAL,
    TIER_RARE,
)


def _registered_command_paths() -> set[str]:
    paths = {command.name for command in app.registered_commands}
    for group in app.registered_groups:
        group_name = group.name
        typer_app = group.typer_instance
        for command in typer_app.registered_commands:
            paths.add(f"{group_name} {command.name}")
    paths.add("doctor")
    return {path for path in paths if path is not None}


def test_registered_commands_have_inventory_metadata() -> None:
    assert _registered_command_paths() == set(COMMAND_METADATA)


def test_inventory_marks_core_and_repair_commands() -> None:
    assert COMMAND_METADATA["task create"].audience == STABLE_FOR_AGENTS
    assert COMMAND_METADATA["plan approve"].audience == STABLE_FOR_AGENTS
    assert COMMAND_METADATA["plan review"].audience == STABLE_FOR_AGENTS
    assert COMMAND_METADATA["implement restart"].audience == STABLE_FOR_AGENTS
    assert COMMAND_METADATA["implement resume"].audience == STABLE_FOR_AGENTS
    assert COMMAND_METADATA["task uncancel"].audience == STABLE_FOR_AGENTS
    assert COMMAND_METADATA["serve"].audience == HUMAN_ORIENTED
    assert COMMAND_METADATA["lock break"].audience == REPAIR
    assert COMMAND_METADATA["doctor"].audience == REPAIR


def test_plan_review_is_classified_read_only() -> None:
    spec = COMMAND_METADATA["plan review"]
    assert spec.effect == "safe_read_only"
    assert spec.ledger_effect == EFFECT_READ
    assert spec.targeting == TARGETING_ACTIVE_DEFAULT


def test_mutating_commands_are_not_marked_safe_read_only() -> None:
    mutating_suffixes = {
        "activate",
        "add",
        "change",
        "answer",
        "approve",
        "artifact",
        "break",
        "cancel",
        "check",
        "close",
        "command",
        "create",
        "deactivate",
        "deviation",
        "dismiss",
        "done",
        "edit",
        "finish",
        "index",
        "link",
        "log",
        "propose",
        "reject",
        "remove",
        "resume",
        "revise",
        "scan-changes",
        "start",
        "task",
        "uncancel",
        "undone",
        "unlink",
        "waive",
    }

    for command, spec in COMMAND_METADATA.items():
        assert not (
            command.split()[-1] in mutating_suffixes and spec.effect == "safe_read_only"
        ), command


# ── new metadata tests ────────────────────────────────────────────────


def test_all_commands_have_ledger_effect() -> None:
    """Every command must have a non-empty ledger_effect after migration."""
    empty = [k for k, v in COMMAND_METADATA.items() if not v.ledger_effect]
    assert empty == [], f"Commands with empty ledger_effect: {empty}"


def test_critical_tier_count_under_25() -> None:
    critical = [k for k, v in COMMAND_METADATA.items() if v.tier == TIER_CRITICAL]
    assert len(critical) <= 25, f"Too many critical: {len(critical)}"


def test_critical_tier_is_primary_surface() -> None:
    """Critical-tier commands should all be primary surface."""
    non_primary = [
        k
        for k, v in COMMAND_METADATA.items()
        if v.tier == TIER_CRITICAL and v.surface != "primary"
    ]
    assert non_primary == [], f"Non-primary critical commands: {non_primary}"


def test_lock_break_is_deprecated() -> None:
    spec = COMMAND_METADATA["lock break"]
    assert spec.deprecated is True
    assert spec.replaced_by == "repair lock"
    assert spec.tier == TIER_RARE


def test_no_other_deprecated_commands() -> None:
    """Only lock break should be deprecated for now."""
    deprecated = [k for k, v in COMMAND_METADATA.items() if v.deprecated]
    assert deprecated == ["lock break"]


def test_process_exec_commands() -> None:
    """Commands that execute subprocesses must have process_exec."""
    process_cmds = [
        k
        for k, v in COMMAND_METADATA.items()
        if v.external_effect == EXTERNAL_PROCESS_EXEC
    ]
    assert "implement command" in process_cmds
    assert "plan command" in process_cmds


def test_server_socket_commands() -> None:
    spec = COMMAND_METADATA["serve"]
    assert spec.external_effect == EXTERNAL_SERVER_SOCKET
    assert spec.agent_safe is False


def test_file_write_commands() -> None:
    """Export, snapshot, release changelog write external files."""
    file_write_cmds = [
        k
        for k, v in COMMAND_METADATA.items()
        if v.external_effect == EXTERNAL_FILE_WRITE
    ]
    assert "export" in file_write_cmds
    assert "snapshot" in file_write_cmds
    assert "release changelog" in file_write_cmds
    assert "plan template" in file_write_cmds


def test_workspace_read_commands() -> None:
    """Search/grep/symbols/deps read the workspace filesystem."""
    for cmd in ("search", "grep", "symbols", "deps"):
        assert COMMAND_METADATA[cmd].workspace_effect == EFFECT_READ, cmd
        assert COMMAND_METADATA[cmd].ledger_effect == EFFECT_NONE, cmd


def test_repair_commands_are_rare() -> None:
    """All repair/doctor/migration commands should be rare tier."""
    repair_cmds = [
        k for k, v in COMMAND_METADATA.items() if v.surface in ("repair", "migration")
    ]
    non_rare = [k for k in repair_cmds if COMMAND_METADATA[k].tier != TIER_RARE]
    assert non_rare == [], f"Repair commands not rare: {non_rare}"


def test_tier_values_are_valid() -> None:
    """Every tier must be one of the known constants."""
    valid_tiers = {TIER_CRITICAL, TIER_NORMAL, TIER_RARE}
    invalid = [k for k, v in COMMAND_METADATA.items() if v.tier not in valid_tiers]
    assert invalid == [], f"Commands with invalid tier: {invalid}"


def test_ledger_effect_values_are_valid() -> None:
    """Every ledger_effect must be one of the known constants."""
    valid = {EFFECT_NONE, EFFECT_READ, EFFECT_WRITE}
    invalid = [k for k, v in COMMAND_METADATA.items() if v.ledger_effect not in valid]
    assert invalid == [], f"Commands with invalid ledger_effect: {invalid}"


def test_legacy_mutation_commands_classified_correctly() -> None:
    """Commands with effect=ledger_mutation that are not ledger writes
    should have explicit non-write ledger_effect (export reads to file)."""
    legacy_mut_not_write = [
        k
        for k, v in COMMAND_METADATA.items()
        if v.effect == "ledger_mutation" and v.ledger_effect != EFFECT_WRITE
    ]
    # export reads ledger and writes external file, so ledger_effect=read
    assert sorted(legacy_mut_not_write) == ["export"]


def test_read_only_commands_have_read_or_none_ledger_effect() -> None:
    """safe_read_only effect should have read or none ledger_effect."""
    mismatches = [
        k
        for k, v in COMMAND_METADATA.items()
        if v.effect == "safe_read_only"
        and v.ledger_effect not in (EFFECT_READ, EFFECT_NONE)
    ]
    assert mismatches == [], f"Bad read-only ledger_effect: {mismatches}"


def test_deprecated_hidden_by_default_in_commands_cli() -> None:
    """taskledger commands should not show lock break."""
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(app, ["commands"])
    assert result.exit_code == 0
    assert "lock break" not in result.stdout

    result_with = runner.invoke(app, ["commands", "--include-deprecated"])
    assert result_with.exit_code == 0
    assert "lock break" in result_with.stdout


def test_tier_filter_in_commands_cli() -> None:
    """taskledger commands --tier critical returns only critical commands."""
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(app, ["commands", "--tier", "critical"])
    assert result.exit_code == 0
    lines = [
        line
        for line in result.stdout.strip().split("\n")
        if line and not line.startswith("-")
    ]
    # header + data lines
    data_lines = lines[1:]  # skip header
    critical_names = [k for k, v in COMMAND_METADATA.items() if v.tier == TIER_CRITICAL]
    assert len(data_lines) == len(critical_names)


def test_commands_json_includes_new_fields() -> None:
    """taskledger --json commands should include all new metadata fields."""
    import json

    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(app, ["--json", "commands", "--tier", "critical"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    cmds = payload["result"]["commands"]
    assert len(cmds) > 0
    first = cmds[0]
    for field in (
        "tier",
        "targeting",
        "deprecated",
        "replaced_by",
        "ledger_effect",
        "workspace_effect",
        "external_effect",
        "agent_safe",
    ):
        assert field in first, f"Missing field: {field}"


def test_targeting_values_are_valid() -> None:
    valid = {
        TARGETING_NONE,
        TARGETING_ACTIVE_DEFAULT,
        TARGETING_POSITIONAL_RESOURCE,
        TARGETING_POSITIONAL_OR_ACTIVE,
        TARGETING_EXPLICIT_REQUIRED,
    }
    invalid = [k for k, v in COMMAND_METADATA.items() if v.targeting not in valid]
    assert invalid == [], f"Commands with invalid targeting: {invalid}"


def test_targeting_metadata_for_key_commands() -> None:
    assert COMMAND_METADATA["plan start"].targeting == TARGETING_ACTIVE_DEFAULT
    assert COMMAND_METADATA["implement start"].targeting == TARGETING_ACTIVE_DEFAULT
    assert COMMAND_METADATA["validate start"].targeting == TARGETING_ACTIVE_DEFAULT
    assert COMMAND_METADATA["task show"].targeting == TARGETING_POSITIONAL_OR_ACTIVE
    assert COMMAND_METADATA["task cancel"].targeting == TARGETING_EXPLICIT_REQUIRED
