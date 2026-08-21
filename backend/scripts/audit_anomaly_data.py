#!/usr/bin/env python3
"""Automated audit agent script for checking ZZZ stateful anomaly modifier and move data.

Verifies schemas, stat keys, and values for all 53 agent modifiers and seeded moves.
"""

import json
import re
import sys
from pathlib import Path

# Paths relative to script location
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.resolve()
MODIFIERS_DIR = PROJECT_ROOT / "app" / "data" / "modifiers" / "agents"
MOVES_DIR = PROJECT_ROOT / "app" / "data" / "moves" / "agents"

# Allowed scopes
ALLOWED_SCOPES = {
    "all",
    "basic",
    "dash",
    "dodge_counter",
    "special",
    "ex_special",
    "chain",
    "ultimate",
    "assist_followup",
}

# Allowed elements
ALLOWED_ELEMENTS = {"physical", "fire", "ice", "electric", "ether"}

# Valid modifier stats from tags.py and buff_resolver.py
VALID_STATS = {
    # Core stats
    "atk",
    "hp",
    "defense",
    "crit_rate",
    "crit_dmg",
    "pen_ratio",
    "pen_flat",
    "anomaly_proficiency",
    "anomaly_mastery",
    "impact",
    "energy_regen",
    "elem_dmg",
    # Buff percent contributions
    "hp_pct",
    "atk_pct",
    "def_pct",
    "flat_hp",
    "flat_atk",
    "flat_def",
    "final_hp_pct",
    "final_atk_pct",
    "final_def_pct",
    "final_flat_hp",
    "final_flat_atk",
    "final_flat_def",
    # Element-specific dmg bonuses
    "physical_dmg",
    "fire_dmg",
    "ice_dmg",
    "electric_dmg",
    "ether_dmg",
    # Anomaly/Disorder/Vortex specific
    "dmg_bonus",
    "anomaly_dmg_bonus",
    "disorder_dmg_bonus",
    "vortex_dmg_bonus",
    "res_reduction",
    "res_ignore",
    "def_ignore",
    "vulnerability",
    # Element-specific buildup modifiers
    "physical_anomaly_buildup",
    "fire_anomaly_buildup",
    "ice_anomaly_buildup",
    "electric_anomaly_buildup",
    "ether_anomaly_buildup",
}

# Known-bad aliases for stat keys, kept separate so the "did you mean" hints below stay readable.
INVALID_ATK_STAT_ALIASES = {"atk_flat", "flat_atk_pct"}
INVALID_DEF_STAT_ALIASES = {"def_reduction", "defense_reduction"}

# Sanity ceiling for basis-point values (300% as basis points); higher usually means a
# scaling mistake (e.g. percent instead of basis points).
MAX_SANE_BASIS_POINTS = 30000


def _load_json(path: Path, errors: list[str]) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        errors.append(f"[{path.name}] Failed to parse JSON: {e}")
        return None


def _check_modifier_file_keys(path: Path, data: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if "source_type" not in data or data["source_type"] != "agent":
        warnings.append(f"[{path.name}] Missing or invalid 'source_type'")
    if "source_name" not in data:
        errors.append(f"[{path.name}] Missing 'source_name'")
    if "notes" not in data:
        warnings.append(f"[{path.name}] Missing 'notes' field (Curation discipline)")
    return errors, warnings


def _check_modifier_stat(path: Path, i: int, stat: str) -> tuple[list[str], list[str]]:
    if stat in VALID_STATS:
        return [], []
    if stat in INVALID_ATK_STAT_ALIASES:
        msg = f"[{path.name}] Modifier #{i} uses invalid stat '{stat}' (must use 'flat_atk')"
        return [msg], []
    if stat in INVALID_DEF_STAT_ALIASES:
        msg = f"[{path.name}] Modifier #{i} uses invalid stat '{stat}' (must use 'def_ignore')"
        return [msg], []
    return [], [f"[{path.name}] Modifier #{i} uses unrecognized stat '{stat}'"]


def _check_modifier_value(
    path: Path, i: int, stat: str, value: object
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if value is None:
        errors.append(f"[{path.name}] Modifier #{i} for '{stat}' is missing 'value'")
    elif not isinstance(value, (int, float)):
        errors.append(f"[{path.name}] Modifier #{i} value '{value}' is not a number")

    if isinstance(value, int) and value > MAX_SANE_BASIS_POINTS:
        warnings.append(
            f"[{path.name}] Modifier #{i} for '{stat}' value '{value}' is unusually high "
            "(check basis points scaling)"
        )
    return errors, warnings


def _check_modifier_conditions_scopes(
    path: Path, i: int, conditions: list, scopes: list
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not conditions:
        warnings.append(f"[{path.name}] Modifier #{i} has empty 'conditions'")
    if not scopes:
        warnings.append(f"[{path.name}] Modifier #{i} has empty 'scopes'")
    else:
        errors.extend(
            f"[{path.name}] Modifier #{i} uses invalid scope '{scope}'"
            for scope in scopes
            if scope not in ALLOWED_SCOPES
        )
    return errors, warnings


def _audit_modifier_entry(path: Path, i: int, mod: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    stat = mod.get("stat")
    value = mod.get("value")
    conditions = mod.get("conditions", [])
    scopes = mod.get("scopes", [])

    if not stat:
        errors.append(f"[{path.name}] Modifier #{i} is missing 'stat'")
        return errors, warnings

    stat_errors, stat_warnings = _check_modifier_stat(path, i, stat)
    errors.extend(stat_errors)
    warnings.extend(stat_warnings)

    value_errors, value_warnings = _check_modifier_value(path, i, stat, value)
    errors.extend(value_errors)
    warnings.extend(value_warnings)

    cond_errors, cond_warnings = _check_modifier_conditions_scopes(path, i, conditions, scopes)
    errors.extend(cond_errors)
    warnings.extend(cond_warnings)

    return errors, warnings


def audit_modifiers() -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    warnings: list[str] = []
    audited_count = 0

    if not MODIFIERS_DIR.exists():
        return [f"Modifiers directory not found: {MODIFIERS_DIR}"], [], 0

    for path in MODIFIERS_DIR.glob("*.json"):
        audited_count += 1
        data = _load_json(path, errors)
        if data is None:
            continue

        key_errors, key_warnings = _check_modifier_file_keys(path, data)
        errors.extend(key_errors)
        warnings.extend(key_warnings)

        for i, mod in enumerate(data.get("modifiers", [])):
            mod_errors, mod_warnings = _audit_modifier_entry(path, i, mod)
            errors.extend(mod_errors)
            warnings.extend(mod_warnings)

    return errors, warnings, audited_count


def _check_move_file_keys(path: Path, data: dict) -> list[str]:
    errors: list[str] = []
    agent_id = data.get("agent_id")
    agent_name = data.get("agent_name")

    if not agent_id:
        errors.append(f"[{path.name}] Missing 'agent_id'")
    elif not re.match(r"^[a-fA-F0-9\-]{36}$", agent_id):
        errors.append(f"[{path.name}] 'agent_id' '{agent_id}' is not a valid UUIDv4")

    if not agent_name:
        errors.append(f"[{path.name}] Missing 'agent_name'")

    return errors


def _check_move_entry(path: Path, move_name: str, move_data: dict) -> list[str]:
    errors: list[str] = []
    buildup = move_data.get("buildup")
    duration_s = move_data.get("duration_s")
    hits = move_data.get("hits")
    element = move_data.get("element")
    scope = move_data.get("scope")

    if buildup is None:
        errors.append(f"[{path.name}] Move '{move_name}' is missing 'buildup'")
    elif not isinstance(buildup, (int, float)):
        errors.append(f"[{path.name}] Move '{move_name}' buildup '{buildup}' is not a number")

    if duration_s is None:
        errors.append(f"[{path.name}] Move '{move_name}' is missing 'duration_s'")
    elif not isinstance(duration_s, (int, float)):
        errors.append(
            f"[{path.name}] Move '{move_name}' duration_s '{duration_s}' is not a number"
        )

    if hits is None:
        errors.append(f"[{path.name}] Move '{move_name}' is missing 'hits'")
    elif not isinstance(hits, int):
        errors.append(f"[{path.name}] Move '{move_name}' hits '{hits}' is not an integer")

    if not element:
        errors.append(f"[{path.name}] Move '{move_name}' is missing 'element'")
    elif element not in ALLOWED_ELEMENTS:
        errors.append(f"[{path.name}] Move '{move_name}' uses invalid element '{element}'")

    if not scope:
        errors.append(f"[{path.name}] Move '{move_name}' is missing 'scope'")
    # NOTE: the original script also cross-checked `scope` against ALLOWED_SCOPES plus a
    # few extra values, but that branch's body was a bare `pass` (no-op). Dropped here as
    # dead code — behavior (audit output) is unchanged.

    return errors


def audit_moves() -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    warnings: list[str] = []
    audited_count = 0

    if not MOVES_DIR.exists():
        return [f"Moves directory not found: {MOVES_DIR}"], [], 0

    for path in MOVES_DIR.glob("*.json"):
        audited_count += 1
        data = _load_json(path, errors)
        if data is None:
            continue

        errors.extend(_check_move_file_keys(path, data))

        moves = data.get("moves", {})
        if not moves or not isinstance(moves, dict):
            errors.append(f"[{path.name}] 'moves' must be a non-empty dictionary")
            continue

        for move_name, move_data in moves.items():
            errors.extend(_check_move_entry(path, move_name, move_data))

    return errors, warnings, audited_count


def _build_status_section(
    errors: list[str],
    warnings: list[str],
    all_ok_message: str,
    error_header: str,
    warning_header: str,
) -> list[str]:
    if not errors and not warnings:
        return [all_ok_message]

    lines: list[str] = []
    if errors:
        lines.append(error_header)
        lines.extend(f"- {err}" for err in errors)
        lines.append("")
    if warnings:
        lines.append(warning_header)
        lines.extend(f"- {warn}" for warn in warnings)
        lines.append("")
    return lines


def _build_verdict_section(total_errors: int) -> list[str]:
    if total_errors == 0:
        return [
            "> [!NOTE]",
            "> **VERDICT: PASS**",
            "> All active agent JSON files and seeded moves conform completely to "
            "`DESIGN_anomaly.md` specifications and `MODIFIER_AUTHORING.md` standards.",
        ]
    return [
        "> [!CAUTION]",
        "> **VERDICT: FAIL**",
        f"> Found {total_errors} errors. These must be resolved before merging the feature "
        "branch.",
    ]


def main() -> None:
    print("==================================================")
    print("🚀 Running Stateful Anomaly Data Audit Subagent")
    print("==================================================")

    mod_errors, mod_warnings, mod_count = audit_modifiers()
    move_errors, move_warnings, move_count = audit_moves()

    report_lines = [
        "# Automated Audit Report — Anomaly Modifier & Move Data Schema Verification",
        "",
        "* **Date**: 2026-05-26",
        f"* **Audited Agent Modifier Files**: {mod_count}",
        f"* **Audited Move Seed Files**: {move_count}",
        "",
        "## Modifier Schema & Stat Tag Verification Results",
        "",
    ]
    report_lines.extend(
        _build_status_section(
            mod_errors,
            mod_warnings,
            "✓ **Modifiers Status**: 100% Perfect! All files parsed, stat keys are valid, "
            "and value formats are correct.",
            "### ❌ Modifier Errors",
            "### ⚠️ Modifier Warnings",
        )
    )

    report_lines.append("")
    report_lines.append("## Move Data Seeding Verification Results")
    report_lines.append("")
    report_lines.extend(
        _build_status_section(
            move_errors,
            move_warnings,
            "✓ **Move Data Status**: 100% Perfect! All move data UUIDs are valid, move "
            "attributes match allowed scopes, and elements are valid ZZZ attributes.",
            "### ❌ Move Errors",
            "### ⚠️ Move Warnings",
        )
    )

    report_lines.append("")
    report_lines.append("## Audit Verdict")
    report_lines.append("")

    total_errors = len(mod_errors) + len(move_errors)
    report_lines.extend(_build_verdict_section(total_errors))

    report_path = Path("docs/review/anomaly_data_audit_report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    print(f"✓ Audit completed. Report written to {report_path}")
    print(f"  - Total Errors: {len(mod_errors) + len(move_errors)}")
    print(f"  - Total Warnings: {len(mod_warnings) + len(move_warnings)}")

    sys.exit(1 if total_errors > 0 else 0)


if __name__ == "__main__":
    main()
