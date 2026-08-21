"""Pydantic schemas for Build, Combo, EnemyProfile."""

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# Skills cap at 12 at L60 (ZO consts/src/common.ts:279-287); M3 adds +2 and M5 another
# +2, and `skill_levels` stores the EFFECTIVE level with that bonus already included
# (established in #153 against a real scanner export). So the legal ceiling is a
# function of mindscape, and both halves are checkable.
_SKILL_SLOTS = 5
_SKILL_BASE_CAP = 12
_SKILL_ABSOLUTE_CAP = 16  # 12 + 4 at M5+


def _mindscape_skill_bonus(mindscape: int) -> int:
    if mindscape >= 5:  # noqa: PLR2004
        return 4
    if mindscape >= 3:  # noqa: PLR2004
        return 2
    return 0


def _parse_skill_levels(raw: str) -> list[int]:
    """Parse and range-check `skill_levels`, independent of mindscape.

    Until #156 this field had no validation of any kind, so a typo'd 51 was
    indistinguishable from a legitimate 15 — and two live builds ended up
    self-contradicting (Anby and Nicole at mindscape 0 with skills of 13 and 15).
    """
    parts = [p.strip() for p in (raw or "").split(",")]
    if len(parts) != _SKILL_SLOTS:
        msg = (
            f"skill_levels must have exactly {_SKILL_SLOTS} comma-separated "
            f"entries, got {len(parts)}"
        )
        raise ValueError(msg)
    try:
        levels = [int(p) for p in parts]
    except ValueError as exc:
        msg = f"skill_levels entries must all be integers: {raw!r}"
        raise ValueError(msg) from exc
    for lv in levels:
        if not 1 <= lv <= _SKILL_ABSOLUTE_CAP:
            msg = f"skill level {lv} out of range 1-{_SKILL_ABSOLUTE_CAP} in {raw!r}"
            raise ValueError(msg)
    return levels


def _check_skill_levels_against_mindscape(raw: str | None, mindscape: int | None) -> None:
    """Cross-check, when both fields are present.

    A PATCH carrying only `skill_levels` has no mindscape to check against — the
    persisted row is not visible at schema level — so that case gets shape and the
    absolute ceiling only. Documented gap, not an oversight.
    """
    if raw is None:
        return
    levels = _parse_skill_levels(raw)
    if mindscape is None:
        return
    allowed = _SKILL_BASE_CAP + _mindscape_skill_bonus(mindscape)
    over = [lv for lv in levels if lv > allowed]
    if over:
        msg = (
            f"skill level(s) {over} exceed the maximum of {allowed} for mindscape "
            f"{mindscape} (skills cap at {_SKILL_BASE_CAP}; M3 grants +2, M5 +4, and "
            f"skill_levels stores the effective level)"
        )
        raise ValueError(msg)

# --- Build ---


class BuildCreate(BaseModel):
    """Body for `POST /builds` — creates a build for an agent with default gear/level."""

    agent_id: str
    w_engine_id: str | None = None
    w_engine_level: int = 60
    w_engine_refinement: int = 1
    mindscape_level: int = 0
    core_skill_level: int = 5
    # Potential Vision level (#90): 0 = not unlocked, 1..6 = Level I..VI. Defaults to 6 so a
    # build created without naming it keeps the numbers fairy produced before #90,
    # when the Potential-unlocked kit was unconditional.
    potential_rank: int = Field(default=6, ge=0, le=6)
    agent_level: int = 60
    skill_levels: str = "12,12,12,12,12"
    notes: str = ""

    @model_validator(mode="after")
    def _validate_skill_levels(self) -> "BuildCreate":
        _check_skill_levels_against_mindscape(self.skill_levels, self.mindscape_level)
        return self


class BuildUpdate(BaseModel):
    """Body for `PATCH /builds/{id}` — all fields optional, partial update."""

    w_engine_id: str | None = None
    w_engine_level: int | None = None
    w_engine_refinement: int | None = None
    mindscape_level: int | None = None
    core_skill_level: int | None = None
    potential_rank: int | None = Field(default=None, ge=0, le=6)
    agent_level: int | None = None
    skill_levels: str | None = None
    notes: str | None = None
    disabled_buffs: list[str] | None = None
    active_conditions: list[str] | None = None
    stack_counts: dict[str, int] | None = None

    @model_validator(mode="after")
    def _validate_skill_levels(self) -> "BuildUpdate":
        _check_skill_levels_against_mindscape(self.skill_levels, self.mindscape_level)
        return self


class BuildEquipDiscsRequest(BaseModel):
    """Body for ``PATCH /builds/{id}/equip-discs``.

    ``discs`` must contain exactly keys 1-6 (all disc slots) mapping to
    disc UUIDs. All six slots are replaced atomically.
    """

    discs: dict[int, str]

    @field_validator("discs")
    @classmethod
    def _validate_discs(cls, v: dict[int, str]) -> dict[int, str]:
        _valid = frozenset({1, 2, 3, 4, 5, 6})
        if set(v.keys()) != _valid:
            missing = _valid - set(v.keys())
            extra = set(v.keys()) - _valid
            parts = []
            if missing:
                parts.append(f"missing slots: {sorted(missing)}")
            if extra:
                parts.append(f"invalid slots: {sorted(extra)}")
            raise ValueError("; ".join(parts))
        for slot, disc_id in v.items():
            try:
                uuid.UUID(disc_id)
            except ValueError as exc:
                raise ValueError(f"Slot {slot}: {disc_id!r} is not a valid UUID") from exc
        return v


class BuildRead(BaseModel):
    """Response for build read endpoints — full build state, including buffs and overrides."""

    id: str
    agent_id: str
    agent_specialty: str
    w_engine_id: str | None
    w_engine_level: int
    w_engine_refinement: int
    mindscape_level: int
    core_skill_level: int
    potential_rank: int
    agent_level: int
    skill_levels: str
    notes: str
    disabled_buffs: list[str]
    active_conditions: list[str]
    stack_counts: dict[str, int]
    optimizer_priority: int | None = None

    model_config = {"from_attributes": True}


class BuildPriorityUpdate(BaseModel):
    """Body for ``PUT /builds/priority``.

    ``ordered_build_ids`` is the desired priority order (index 0 = rank 1).
    Builds absent from the list are set to NULL (unranked).
    """

    ordered_build_ids: list[str]

    @field_validator("ordered_build_ids")
    @classmethod
    def _validate_ids(cls, v: list[str]) -> list[str]:
        for build_id in v:
            try:
                uuid.UUID(build_id)
            except ValueError as exc:
                raise ValueError(f"{build_id!r} is not a valid UUID") from exc
        if len(v) != len(set(v)):
            raise ValueError("ordered_build_ids must not contain duplicates")
        return v


class BuffDescriptor(BaseModel):
    """One toggleable kit modifier — one stat contribution."""

    id: str
    role: str  # "dps" | "support1" | "support2"
    agent_name: str
    source: str  # ModifierSource value (core_skill, mindscape, ...)
    source_label: str
    stat: str
    value: int
    target: str  # ModifierTarget value
    conditions: list[str]
    enabled: bool
    max_stacks: int = 1


class BuffGroup(BaseModel):
    """One ability / mindscape on one agent, with its in-game description.

    Groups exist so the UI can show the kit text once per ability instead
    of repeating it for every stat the ability provides (e.g. an EX
    Special buff that gives both ATK% and CRIT Rate is one group with
    two ``buffs`` rows).
    """

    role: str  # "dps" | "support1" | "support2"
    agent_name: str
    group_key: str  # "core" | "M1" | "M2" | ...
    name: str  # In-game ability name ("Core Passive: ...", "Mindscape 1: ...")
    description: str  # In-game flavor text from nanoka, or "" if unavailable
    buffs: list[BuffDescriptor]


class BuildBuffsResponse(BaseModel):
    """All toggleable buffs across DPS + support1 + support2, grouped by ability."""

    build_id: str
    groups: list[BuffGroup]


# --- Combo ---


class ComboStepInput(BaseModel):
    """One entry in a combo's saved sequence.

    Either ``move_name`` (preferred — expands at calc time to all hits
    sharing that attack name on the build's agent) or ``attack_id``
    (legacy single-hit) must be set for attack steps. Marker steps
    (``step_type='stun_trigger'`` or ``'stun_end'``) have no move/attack.
    ``label`` is the display tag the user assigned to the step.
    """

    label: str
    agent_id: str | None = None
    attack_id: str | None = None
    move_name: str | None = None
    step_type: str | None = None
    variant_label: str | None = None
    single_tap: bool = False
    cycle_position: int | None = None
    # Hold length for a `hit_mode='channel'` move (docs/DESIGN_channeled_moves.md §4.1).
    # The third parameterized-mode field, alongside `variant_label` (which rows) and
    # `cycle_position` (which row) -- this one is a quantity, not a row selector.
    # None resolves to the spec's `default_s` with a warning, the same
    # saved-combo-compatibility contract `resolve_variant_selection` already sets.
    channel_s: float | None = None


class ComboCreate(BaseModel):
    """Body for `POST /combos`."""

    name: str
    team_id: str
    sequence: list[ComboStepInput] | None = None
    description: str = ""


class ComboUpdate(BaseModel):
    """Body for `PATCH /combos/{id}` — all fields optional, partial update."""

    name: str | None = None
    sequence: list[ComboStepInput] | None = None
    description: str | None = None


class ComboRead(BaseModel):
    """Response for combo read endpoints."""

    id: str
    name: str
    team_id: str
    sequence: list[dict[str, Any]] | None
    description: str

    model_config = {"from_attributes": True}


# --- EnemyProfile ---


class EnemyProfileCreate(BaseModel):
    """Body for `POST /enemies` — creates a custom enemy profile for damage calc."""

    name: str
    level: int = 60
    hp: int = 0
    atk: int = 0
    defense: int = 50
    physical_res: int = 0
    fire_res: int = 0
    ice_res: int = 0
    electric_res: int = 0
    ether_res: int = 0
    wind_res: int = 0
    anomaly_capacity_physical: int = 100
    anomaly_capacity_fire: int = 100
    anomaly_capacity_ice: int = 100
    anomaly_capacity_electric: int = 100
    anomaly_capacity_ether: int = 100
    anomaly_capacity_wind: int = 100
    anomaly_res_physical: int = 0
    anomaly_res_fire: int = 0
    anomaly_res_ice: int = 0
    anomaly_res_electric: int = 0
    anomaly_res_ether: int = 0
    anomaly_res_wind: int = 0
    anomaly_duration_default: float = 10.0
    stun_buildup_multiplier: int = 10000
    stun_threshold: int = 0
    stun_dmg_taken_ratio: int = 5000
    rarity: int = 1
    tags: str = ""


class EnemyProfileUpdate(BaseModel):
    """Body for `PATCH /enemies/{id}` — all fields optional, partial update."""

    name: str | None = None
    level: int | None = None
    defense: int | None = None
    physical_res: int | None = None
    fire_res: int | None = None
    ice_res: int | None = None
    electric_res: int | None = None
    ether_res: int | None = None
    wind_res: int | None = None
    anomaly_capacity_physical: int | None = None
    anomaly_capacity_fire: int | None = None
    anomaly_capacity_ice: int | None = None
    anomaly_capacity_electric: int | None = None
    anomaly_capacity_ether: int | None = None
    anomaly_capacity_wind: int | None = None
    anomaly_res_physical: int | None = None
    anomaly_res_fire: int | None = None
    anomaly_res_ice: int | None = None
    anomaly_res_electric: int | None = None
    anomaly_res_ether: int | None = None
    anomaly_res_wind: int | None = None
    anomaly_duration_default: float | None = None
    stun_buildup_multiplier: int | None = None
    stun_threshold: int | None = None
    stun_dmg_taken_ratio: int | None = None
    tags: str | None = None


class EnemyProfileRead(BaseModel):
    """Response for enemy profile read endpoints."""

    id: str
    hakushin_id: int | None
    name: str
    level: int
    hp: int
    atk: int
    defense: int
    physical_res: int
    fire_res: int
    ice_res: int
    electric_res: int
    ether_res: int
    wind_res: int
    anomaly_capacity_physical: int
    anomaly_capacity_fire: int
    anomaly_capacity_ice: int
    anomaly_capacity_electric: int
    anomaly_capacity_ether: int
    anomaly_capacity_wind: int
    anomaly_res_physical: int
    anomaly_res_fire: int
    anomaly_res_ice: int
    anomaly_res_electric: int
    anomaly_res_ether: int
    anomaly_res_wind: int
    anomaly_duration_default: float
    stun_buildup_multiplier: int
    stun_threshold: int
    stun_dmg_taken_ratio: int
    rarity: int
    tags: str

    model_config = {"from_attributes": True}
