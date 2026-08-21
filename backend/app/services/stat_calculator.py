"""Stat aggregation — combine agent base stats, W-Engine, discs, and set bonuses.

All values use basis points (100 = 1%) unless noted as flat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor


@dataclass
class TotalStats:
    """Fully resolved stats for a build, ready for damage calculation."""

    # Final computed values
    hp: int = 0
    atk: int = 0
    defense: int = 0  # "def" is reserved

    crit_rate: int = 500  # basis points, 500 = 5%
    crit_dmg: int = 5000  # 5000 = 50%
    anomaly_mastery: int = 0
    anomaly_proficiency: int = 0
    impact: int = 0
    energy_regen: int = 0
    pen_flat: int = 0
    pen_ratio: int = 0

    # Damage bonuses (basis points)
    physical_dmg: int = 0
    fire_dmg: int = 0
    ice_dmg: int = 0
    electric_dmg: int = 0
    ether_dmg: int = 0
    wind_dmg: int = 0

    def elemental_dmg(self, element: str) -> int:
        """Look up the DMG% bonus (bp) for a given element by name, e.g. "fire" -> fire_dmg."""
        return getattr(self, f"{element}_dmg", 0)


@dataclass
class StatInputs:
    """Raw stat inputs before aggregation."""

    # Agent base stats (from model, at level 60)
    agent_base_hp: int = 0
    agent_base_atk: int = 0
    agent_base_def: int = 0

    # W-Engine base ATK
    wengine_base_atk: int = 0

    # Percentage bonuses (basis points, sum of all sources)
    hp_pct: int = 0
    atk_pct: int = 0
    def_pct: int = 0

    # Flat bonuses (sum of all sources)
    flat_hp: int = 0
    flat_atk: int = 0
    flat_def: int = 0

    # "Final" multipliers — applied after the first aggregation
    # (rare, from certain W-Engine passives or set bonuses)
    final_hp_pct: int = 0
    final_atk_pct: int = 0
    final_def_pct: int = 0
    final_flat_hp: int = 0
    final_flat_atk: int = 0
    final_flat_def: int = 0

    # Combat stats
    crit_rate: int = 500
    crit_dmg: int = 5000
    # Anomaly Mastery: % applied to base only (Initial Stat rule); flat added after.
    agent_base_am: int = 0  # agent's base_anomaly_mastery (the "Base Stat")
    am_pct: int = 0  # sum of AM% bonuses (2-pc set, W-Engine secondary)
    anomaly_mastery: int = 0  # flat accumulator: disc + W-Engine flat additions
    anomaly_proficiency: int = 0
    # Impact: % applied to base only (Initial Stat rule); flat added after — same
    # bracket as Anomaly Mastery above. ZO listing.ts:50 puts `impact` in
    # flatAndPercentStats alongside atk/def/hp, and common/index.ts:40 applies the
    # percent to the base. Impact feeds Daze buildup, not damage (references/ZZZ
    # Stats and Damage Calculation) — and fairy does not model Daze buildup, so this
    # is a display stat today.
    agent_base_impact: int = 0
    impact_pct: int = 0
    impact: int = 0  # flat accumulator: disc main/sub + W-Engine flat
    energy_regen: int = 0
    pen_flat: int = 0
    pen_ratio: int = 0

    # Elemental damage bonuses
    physical_dmg: int = 0
    fire_dmg: int = 0
    ice_dmg: int = 0
    electric_dmg: int = 0
    ether_dmg: int = 0
    wind_dmg: int = 0


@dataclass
class DiscStats:
    """Accumulated stats from a set of discs."""

    flat_hp: int = 0
    flat_atk: int = 0
    flat_def: int = 0
    hp_pct: int = 0
    atk_pct: int = 0
    def_pct: int = 0
    crit_rate: int = 0
    crit_dmg: int = 0
    pen_flat: int = 0
    pen_ratio: int = 0
    anomaly_mastery: int = 0
    anomaly_proficiency: int = 0
    impact: int = 0
    energy_regen: int = 0
    physical_dmg: int = 0
    fire_dmg: int = 0
    ice_dmg: int = 0
    electric_dmg: int = 0
    ether_dmg: int = 0
    wind_dmg: int = 0

    # Set bonus effects (unconditional only, conditional tracked separately)
    set_bonuses: list[dict] = field(default_factory=list)


def compute_total_stats(inputs: StatInputs) -> TotalStats:
    """Aggregate all stat sources into final TotalStats.

    ATK formula (from Thereallo1026 guide):
      ATK = ((Agent_Base_ATK + WEngine_Base_ATK) * (1 + ATK%) + Flat_ATK)
            * (1 + Final_ATK%) + Final_Flat_ATK

    Same structure for HP and DEF.
    All percentage values in basis points (10000 = 100%).
    """
    base_atk = inputs.agent_base_atk + inputs.wengine_base_atk

    atk = floor(
        (base_atk * (10000 + inputs.atk_pct) / 10000 + inputs.flat_atk)
        * (10000 + inputs.final_atk_pct)
        / 10000
        + inputs.final_flat_atk
    )

    hp = floor(
        (inputs.agent_base_hp * (10000 + inputs.hp_pct) / 10000 + inputs.flat_hp)
        * (10000 + inputs.final_hp_pct)
        / 10000
        + inputs.final_flat_hp
    )

    defense = floor(
        (inputs.agent_base_def * (10000 + inputs.def_pct) / 10000 + inputs.flat_def)
        * (10000 + inputs.final_def_pct)
        / 10000
        + inputs.final_flat_def
    )

    anomaly_mastery = floor(
        inputs.agent_base_am * (10000 + inputs.am_pct) / 10000 + inputs.anomaly_mastery
    )

    impact = floor(inputs.agent_base_impact * (10000 + inputs.impact_pct) / 10000) + inputs.impact

    return TotalStats(
        hp=hp,
        atk=atk,
        defense=defense,
        crit_rate=inputs.crit_rate,
        crit_dmg=inputs.crit_dmg,
        anomaly_mastery=anomaly_mastery,
        anomaly_proficiency=inputs.anomaly_proficiency,
        impact=impact,
        energy_regen=inputs.energy_regen,
        pen_flat=inputs.pen_flat,
        pen_ratio=inputs.pen_ratio,
        physical_dmg=inputs.physical_dmg,
        fire_dmg=inputs.fire_dmg,
        ice_dmg=inputs.ice_dmg,
        electric_dmg=inputs.electric_dmg,
        ether_dmg=inputs.ether_dmg,
        wind_dmg=inputs.wind_dmg,
    )


# Maps disc stat keys → DiscStats field names. Hoisted to module scope so it is
# built once, not rebuilt on every accumulate_disc_stats call (hot in the optimizer).
_DISC_STAT_MAP = {
    "hp": "flat_hp",
    "atk": "flat_atk",
    "def": "flat_def",
    "hp_pct": "hp_pct",
    "atk_pct": "atk_pct",
    "def_pct": "def_pct",
    "crit_rate": "crit_rate",
    "crit_dmg": "crit_dmg",
    "pen_flat": "pen_flat",
    "pen_ratio": "pen_ratio",
    "anomaly_mastery": "anomaly_mastery",
    "anomaly_proficiency": "anomaly_proficiency",
    "impact": "impact",
    "energy_regen": "energy_regen",
    "physical_dmg": "physical_dmg",
    "fire_dmg": "fire_dmg",
    "ice_dmg": "ice_dmg",
    "electric_dmg": "electric_dmg",
    "ether_dmg": "ether_dmg",
    "wind_dmg": "wind_dmg",
}


def accumulate_disc_stats(discs: list[dict]) -> DiscStats:
    """Sum stats from a list of disc dicts (main + substats).

    Each disc dict should have: main_stat_type, main_stat_value, substats.
    """
    result = DiscStats()
    stat_map = _DISC_STAT_MAP

    for disc in discs:
        main_type = disc.get("main_stat_type", "")
        main_value = disc.get("main_stat_value", 0)
        target = stat_map.get(main_type)
        if target:
            setattr(result, target, getattr(result, target) + main_value)

        for sub in disc.get("substats", []) or []:
            sub_type = sub.get("stat", "")
            sub_value = sub.get("value", 0)
            target = stat_map.get(sub_type)
            if target:
                setattr(result, target, getattr(result, target) + sub_value)

    return result
