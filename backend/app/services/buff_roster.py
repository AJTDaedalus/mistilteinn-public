"""Buff-roster pivot — "every resolved buff, once" build-level view.

:class:`~app.services.buff_resolver.ResolvedBuffs` is organised by
calculation bucket (``stat_attributions`` / ``dmg_bonus_attributions`` /
``combat_attributions``) because that's what the damage calculator needs.
The buff roster re-pivots the same :class:`Contribution` rows by buff
instead, for a build-level panel that lists every active modifier once
regardless of which zone it happens to feed (DESIGN_explainability.md §2.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.buff_resolver import Contribution, ResolvedBuffs, SourceCategory

# Maps a resolved-buff stat key to the damage-equation zone it feeds, using
# the same zone names attribution.py's `zone_formulas` uses as keys ("base",
# "boost", "crit", "def", "res", "vulnerability", "stun", "anomaly_prof",
# "anomaly_boost", "disorder_boost", "sheer_force", "sheer_boost"). Stats
# that don't participate in the 7-multiplier chain (raw HP/DEF, buildup
# rate, impact, energy regen, Abloom's separate mini-chain) fall back to
# `_DEFAULT_ZONE` — still listed in the roster, just not equation-drillable.
_STAT_TO_ZONE: dict[str, str] = {
    # Base (ATK — the standard/anomaly scaling stat)
    "atk_pct": "base",
    "flat_atk": "base",
    "final_atk_pct": "base",
    "final_flat_atk": "base",
    "mv_crit_scaling": "base",
    # Crit
    "crit_rate": "crit",
    "crit_dmg": "crit",
    # Anomaly proficiency
    "anomaly_mastery": "anomaly_prof",
    "anomaly_mastery_flat": "anomaly_prof",
    "anomaly_mastery_pct": "anomaly_prof",
    "anomaly_proficiency_flat": "anomaly_prof",
    "anomaly_proficiency": "anomaly_prof",
    # DEF
    "pen_ratio": "def",
    "pen_flat": "def",
    "def_ignore": "def",
    # RES
    "res_reduction": "res",
    "res_ignore": "res",
    # Vulnerability
    "vulnerability": "vulnerability",
    # Stun
    "stun_dmg_mult_bonus": "stun",
    "stun_area_override": "stun",
    # Boost (elemental DMG% lands in the same additive zone as dmg_bonus)
    "physical_dmg": "boost",
    "fire_dmg": "boost",
    "ice_dmg": "boost",
    "electric_dmg": "boost",
    "ether_dmg": "boost",
    "wind_dmg": "boost",
    # AnomalyBoost
    "anomaly_dmg_bonus": "anomaly_boost",
    "shock_dmg_bonus": "anomaly_boost",
    # DisorderBoost
    "disorder_dmg_bonus": "disorder_boost",
    "disorder_duration_bonus_rate": "disorder_boost",
    # SheerBoost / SheerForce (Rupture agents)
    "sheer_dmg_bonus": "sheer_boost",
    "sheer_force_flat": "sheer_force",
}
_DEFAULT_ZONE = "other"

# Stats whose bp value is a raw/flat quantity, not a percentage — displayed
# as-is rather than divided by 100.
_FLAT_STATS = {
    "flat_hp",
    "flat_atk",
    "flat_def",
    "final_flat_hp",
    "final_flat_atk",
    "final_flat_def",
    "pen_flat",
    "impact",
    "anomaly_mastery",
    "anomaly_mastery_flat",
    "anomaly_proficiency_flat",
    "anomaly_proficiency",
    "sheer_force_flat",
    "energy_regen",
    "stun_area_override",
}


@dataclass(frozen=True)
class BuffRosterEntry:
    """One resolved buff, pivoted for a build-level "active buffs" panel.

    Mirrors ``app.schemas.damage.BuffRosterEntrySchema``.
    """

    source_label: str
    source_category: SourceCategory | None
    source_kind: str | None
    owner_agent_name: str | None
    stat: str
    zone: str
    value_bp: int
    magnitude_display: str
    condition: str | None
    is_modeled: bool
    notes: str | None = None  # curator citation/rationale, threaded from Contribution.notes


def _format_magnitude(stat: str, value: int) -> str:
    sign = "-" if value < 0 else "+"
    magnitude = abs(value)
    if stat in _FLAT_STATS:
        return f"{sign}{magnitude}"
    return f"{sign}{magnitude / 100:.2f}%"


def _entry(contribution: Contribution, stat: str, zone: str) -> BuffRosterEntry:
    return BuffRosterEntry(
        source_label=contribution.source,
        source_category=contribution.source_category,
        source_kind=contribution.source_kind,
        owner_agent_name=contribution.owner_agent_name,
        stat=stat,
        zone=zone,
        value_bp=contribution.value,
        magnitude_display=_format_magnitude(stat, contribution.value),
        condition=contribution.condition,
        is_modeled=contribution.is_modeled,
        notes=contribution.notes,
    )


def pivot_buff_roster(resolved: ResolvedBuffs) -> list[BuffRosterEntry]:
    """Walk every ``Contribution`` in *resolved*, pivoted to one row per buff.

    Round-trips losslessly: grouping the returned entries by ``stat`` and
    summing ``value_bp`` reproduces ``resolved.stat_bonuses`` /
    ``resolved.combat_bonuses`` / ``resolved.total_dmg_bonus`` exactly —
    this function only re-labels the same contributions, it never
    recomputes or drops one.
    """
    entries: list[BuffRosterEntry] = []

    for stat, contributions in resolved.stat_attributions.items():
        zone = _STAT_TO_ZONE.get(stat, _DEFAULT_ZONE)
        entries.extend(_entry(c, stat, zone) for c in contributions)

    entries.extend(_entry(c, "dmg_bonus", "boost") for c in resolved.dmg_bonus_attributions)

    for stat, contributions in resolved.combat_attributions.items():
        zone = _STAT_TO_ZONE.get(stat, _DEFAULT_ZONE)
        entries.extend(_entry(c, stat, zone) for c in contributions)

    return entries
