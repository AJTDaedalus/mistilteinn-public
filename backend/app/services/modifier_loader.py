"""Load modifier JSON files and convert to Modifier objects.

Reads the curated modifier JSONs from app/data/modifiers/ and converts
them into Modifier dataclass instances that the buff resolver can evaluate.

Agent modifiers use a flat `value` field (basis points).
W-Engine modifiers use `value_r1`/`value_r5` with linear interpolation.
Disc set modifiers use a flat `value` field.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from math import floor
from pathlib import Path

from app.models.enums import PotentialTag
from app.services.modifiers import (
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)

logger = logging.getLogger(__name__)
_warned_unknown_conditions: set[str] = set()

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "modifiers"

_SOURCE_MAP: dict[str, ModifierSource] = {
    "core_skill": ModifierSource.CORE_SKILL,
    "additional_ability": ModifierSource.ADDITIONAL_ABILITY,
    "mindscape": ModifierSource.MINDSCAPE,
    "w_engine_passive": ModifierSource.WENGINE_PASSIVE,
    "wengine_passive": ModifierSource.WENGINE_PASSIVE,
    "disc_set_2pc": ModifierSource.DISC_SET_2PC,
    "disc_set_4pc": ModifierSource.DISC_SET_4PC,
    "team_buff": ModifierSource.TEAM_BUFF,
    "external": ModifierSource.EXTERNAL,
}

_TARGET_MAP: dict[str, ModifierTarget] = {
    "self": ModifierTarget.SELF,
    "team": ModifierTarget.TEAM,
    "active": ModifierTarget.ACTIVE,
    "summon": ModifierTarget.SUMMON,
}

_SCOPE_MAP: dict[str, AttackScope] = {
    "all": AttackScope.ALL,
    "basic": AttackScope.BASIC,
    "dash": AttackScope.DASH,
    "dodge_counter": AttackScope.DODGE_COUNTER,
    "special": AttackScope.SPECIAL,
    "ex_special": AttackScope.EX_SPECIAL,
    "chain": AttackScope.CHAIN,
    "ultimate": AttackScope.ULTIMATE,
    "assist_followup": AttackScope.ASSIST_FOLLOWUP,
}

# Map condition strings to Condition enum. Falls back to the string itself
# for agent-specific conditions not in the enum (stored as ALWAYS to avoid
# breaking, with a note that the condition is unknown).
_CONDITION_MAP: dict[str, Condition] = {c.value: c for c in Condition}


_MAX_REFINEMENT = 5


def wengine_value_at_refinement(value_r1: int, value_r5: int, refinement: int) -> int:
    """Linearly interpolate W-Engine modifier value for a given refinement level."""
    if refinement <= 1:
        return value_r1
    if refinement >= _MAX_REFINEMENT:
        return value_r5
    return floor(value_r1 + (value_r5 - value_r1) * (refinement - 1) / (_MAX_REFINEMENT - 1))


def _parse_conditions(raw: list[str]) -> tuple[Condition, ...]:
    """Convert condition string list to Condition enum tuple.

    Unknown strings map to Condition.UNKNOWN (which is never in
    ActiveConditions.active), making the modifier inactive by default.
    A warning is logged once per unknown string so kit authors notice typos.
    """
    result = []
    for c in raw:
        mapped = _CONDITION_MAP.get(c)
        if mapped is not None:
            result.append(mapped)
        else:
            if c not in _warned_unknown_conditions:
                logger.warning(
                    "Unknown condition string %r in modifier JSON — "
                    "modifier will be inactive. Add to Condition enum if intentional.",
                    c,
                )
                _warned_unknown_conditions.add(c)
            result.append(Condition.UNKNOWN)
    return tuple(result) if result else (Condition.ALWAYS,)


def _parse_scopes(raw: list[str]) -> tuple[AttackScope, ...]:
    """Convert scope string list to AttackScope enum tuple."""
    result = []
    for s in raw:
        mapped = _SCOPE_MAP.get(s)
        if mapped is not None:
            result.append(mapped)
    return tuple(result) if result else (AttackScope.ALL,)


def _load_json(path: Path) -> dict | None:
    """Load a JSON file, returning None if it doesn't exist."""
    if not path.exists():
        return None
    with path.open() as f:
        return json.load(f)


def _find_file_by_source_id(directory: Path, source_id: str) -> Path | None:
    """Find the modifier JSON file matching a given source_id.

    Raises ``ValueError`` when more than one file claims the id: the first-match
    behaviour this replaces served Velina's fabricated values for Remielle's
    W-Engine 14158 on whichever file the directory glob yielded first
    (docs/TASKS_wengine_id_collision.md, Task H3). No warn-and-pick fallback —
    that would reopen the silent-wrong-data channel this raise closes;
    `validate_kits` Rule 8 (duplicate_source_id) is the CI-time defense, this is
    the runtime one. Sorted glob so the zero-/one-match path is deterministic
    across filesystems.
    """
    if not directory.exists():
        return None
    matches = [
        path
        for path in sorted(directory.glob("*.json"))
        if (data := _load_json(path)) and data.get("source_id") == source_id
    ]
    if len(matches) > 1:
        raise ValueError(
            f"source_id {source_id!r} is claimed by {len(matches)} files in "
            f"{directory.name}/: {', '.join(p.name for p in matches)} — exactly one "
            f"file may own an id (validate_kits L0 duplicate_source_id)"
        )
    return matches[0] if matches else None


@lru_cache(maxsize=256)
def _cached_find_file(directory_str: str, source_id: str) -> str | None:
    """Cached file lookup by source_id. Returns path string or None."""
    directory = Path(directory_str)
    result = _find_file_by_source_id(directory, source_id)
    return str(result) if result else None


def _raw_mod_to_modifier(raw: dict, *, value_override: int | None = None) -> Modifier:
    """Convert a raw JSON modifier dict to a Modifier dataclass."""
    value = value_override if value_override is not None else raw["value"]
    return Modifier(
        stat=raw["stat"],
        value=value,
        source=_SOURCE_MAP.get(raw.get("source", ""), ModifierSource.EXTERNAL),
        source_label=raw.get("source_label", ""),
        target=_TARGET_MAP.get(raw.get("target", "self"), ModifierTarget.SELF),
        conditions=_parse_conditions(raw.get("conditions", ["always"])),
        scopes=_parse_scopes(raw.get("scopes", ["all"])),
        max_stacks=raw.get("max_stacks", 1),
        min_mindscape=raw.get("min_mindscape", 0),
        potential=PotentialTag(raw["potential"]) if raw.get("potential") else None,
        potential_param=raw.get("potential_param"),
        potential_param_scale=raw.get("potential_param_scale", 10_000),
        max_mindscape=raw.get("max_mindscape"),
        hp_scale_base=raw.get("hp_scale_base", 0),
        hp_scale_threshold=raw.get("hp_scale_threshold", 0),
        hp_scale_per_unit=raw.get("hp_scale_per_unit", 0),
        hp_scale_unit=raw.get("hp_scale_unit", 0),
        atk_scale_ratio=raw.get("atk_scale_ratio", 0),
        flat_addend=raw.get("flat_addend", 0),
        scaling_stat=raw.get("scaling_stat"),
        scaling_ratio=raw.get("scaling_ratio", 0.0),
        excess_threshold=raw.get("excess_threshold", 0),
        notes=raw.get("notes"),
        element_scope=tuple(raw["element_scope"]) if raw.get("element_scope") else None,
    )


def load_agent_modifiers(source_id: str) -> list[Modifier]:
    """Load all modifiers for an agent by hakushin_id."""
    agents_dir = _DATA_DIR / "agents"
    path_str = _cached_find_file(str(agents_dir), source_id)
    if path_str is None:
        return []
    data = _load_json(Path(path_str))
    if data is None:
        return []
    return [_raw_mod_to_modifier(m) for m in data.get("modifiers", [])]


def load_agent_formulas(source_id: str) -> list[dict]:
    """Load an agent's raw ``formulas[]`` entries by hakushin_id.

    Returned unresolved: a formula's multiplier is an op-tree over the build's
    mindscape and core level, which only the snapshot builder knows.
    ``kit_formulas.resolve_kit_formulas`` turns these into ``KitFormula`` objects.
    """
    agents_dir = _DATA_DIR / "agents"
    path_str = _cached_find_file(str(agents_dir), source_id)
    if path_str is None:
        return []
    data = _load_json(Path(path_str))
    if data is None:
        return []
    return list(data.get("formulas", []))


def load_disc_set_modifiers(source_id: str) -> list[Modifier]:
    """Load all modifiers for a disc set by hakushin_id."""
    disc_dir = _DATA_DIR / "disc_sets"
    path_str = _cached_find_file(str(disc_dir), source_id)
    if path_str is None:
        return []
    data = _load_json(Path(path_str))
    if data is None:
        return []
    return [_raw_mod_to_modifier(m) for m in data.get("modifiers", [])]


def load_wengine_modifiers(source_id: str, *, refinement: int = 1) -> list[Modifier]:
    """Load all modifiers for a W-Engine by hakushin_id, interpolated to refinement level."""
    wengine_dir = _DATA_DIR / "w_engines"
    path_str = _cached_find_file(str(wengine_dir), source_id)
    if path_str is None:
        return []
    data = _load_json(Path(path_str))
    if data is None:
        return []

    result = []
    for m in data.get("modifiers", []):
        value_r1 = m.get("value_r1", 0)
        value_r5 = m.get("value_r5", 0)
        value = wengine_value_at_refinement(value_r1, value_r5, refinement)
        result.append(_raw_mod_to_modifier(m, value_override=value))
    return result
