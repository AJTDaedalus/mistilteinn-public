"""Build snapshot construction from DB models + modifier JSONs.

This is the only layer that knows about both the database and the
modifier JSON files. It translates DB models into BuildSnapshot /
EnemySnapshot value objects that the stateless damage service consumes.

A future rotation engine would replace this with its own snapshot
construction logic (from timeline state), reusing the same value objects.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace as dc_replace
from math import floor as _floor
from typing import TYPE_CHECKING, Any

from app.services.build_damage_service import (
    _SHEER_INTRINSIC_HP_RATIOS,
    BuildSnapshot,
    EnemySnapshot,
)
from app.services.kit_formulas import resolve_kit_formulas
from app.services.modifier_loader import (
    _CONDITION_MAP,
    load_agent_formulas,
    load_agent_modifiers,
    load_disc_set_modifiers,
    load_wengine_modifiers,
)
from app.services.modifiers import (
    ActiveConditions,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
    bind_potential_param,
    mindscape_allows,
    potential_allows,
    slugify,
    synthesize_custom_buffs,
)
from app.services.stat_calculator import TotalStats, accumulate_disc_stats

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from app.models.agent import Agent, Attack
    from app.models.build import Build, EnemyProfile
    from app.models.disc import Disc

_MIN_2PC = 2
_MIN_4PC = 4
_MAX_CORE_TIER = 5  # F-tier, ZO indexing


# Re-exported, not re-implemented: `modifiers.slugify` is the same rule, and custom
# buffs address themselves with it too (`custom_buff_label`). Two copies would be a slug
# that agrees today and drifts later.
_slugify = slugify


def buff_id(hakushin_id: int | str, source_label: str) -> str:
    """Stable identifier for a single kit modifier.

    ``<hakushin_id>:<slug>`` — survives JSON reordering and is reusable
    across DPS / support roles in the same build (an agent's buff_ids
    are agent-local; the role tag is implicit from which slot it occupies).
    """
    return f"{hakushin_id}:{_slugify(source_label)}"


# Maps ZO ``coreStats`` field names to (modifier_stat, scale) tuples.
# Decimal-percentage fields (suffix ``_``) scale × 10000 → basis points.
#
# Per ZO char/util.ts: flat HP/ATK/DEF from core go into BASE (multiplied by
# both initial% and combat% brackets) — handled via _core_base_deltas, not here.
# Core HP% and ATK% go into the initial bracket (ownBuff.initial[stat]).
# Everything else (CRIT, PEN, AP, etc.) goes into base.
_CORE_STAT_MAP: tuple[tuple[str, str, int], ...] = (
    # flat HP/ATK/DEF are excluded — they go into agent base, not a modifier
    ("atk_", "atk_pct", 10000),
    ("hp_", "hp_pct", 10000),
    ("def_", "def_pct", 10000),
    ("crit_", "crit_rate", 10000),
    ("crit_dmg_", "crit_dmg", 10000),
    ("pen_", "pen_ratio", 10000),
    ("anomMas", "anomaly_mastery", 1),
    ("anomProf", "anomaly_proficiency", 1),
    ("impact", "impact", 1),
    ("enerRegen", "energy_regen", 10000),
)

# ZO core flat stat fields that fold directly into agent base stats.
_CORE_FLAT_BASE_FIELDS: tuple[str, ...] = ("atk", "hp", "def")


def _core_base_deltas(core_stats: list | None, tier: int) -> dict[str, int]:
    """Return flat base-stat adjustments from ``coreStats[tier]``.

    ZO routes core flat ATK/HP/DEF into ``base.*`` — they are multiplied by
    both the initial% and combat% brackets, unlike disc flat stats which sit
    in the inner bracket only. Returns {"atk": n, "hp": n, "def": n} with
    only present fields.
    """
    if not core_stats:
        return {}
    tier = max(0, min(_MAX_CORE_TIER, tier))
    if tier >= len(core_stats):
        return {}
    row = core_stats[tier]
    if not isinstance(row, dict):
        return {}
    return {field: int(raw) for field in _CORE_FLAT_BASE_FIELDS if (raw := row.get(field))}


def _core_modifiers(core_stats: list | None, tier: int) -> list[Modifier]:
    """Synthesize Modifier objects from ZO-shaped ``coreStats[tier]``.

    Emits only percentage-type stats (ATK%, HP%, CRIT Rate, etc.) — flat
    HP/ATK/DEF are handled separately via _core_base_deltas and folded into
    agent_base_* so they are multiplied by both stat brackets.

    Returns an empty list for agents with no backfilled data.
    """
    if not core_stats:
        return []
    tier = max(0, min(_MAX_CORE_TIER, tier))
    if tier >= len(core_stats):
        return []
    row = core_stats[tier]
    if not isinstance(row, dict):
        return []

    mods: list[Modifier] = []
    label = f"Core {chr(ord('A') + tier)}"
    for zo_field, stat, scale in _CORE_STAT_MAP:
        raw = row.get(zo_field)
        if not raw:
            continue
        value = int(raw * scale) if scale != 1 else int(raw)
        if value == 0:
            continue
        mods.append(
            Modifier(
                stat=stat,
                value=value,
                source=ModifierSource.CORE_SKILL,
                source_label=label,
            )
        )
    return mods


def _promotion_for_level(level: int) -> int:
    """Return the active promotion tier (0..5) for a 1-indexed level."""
    if level <= 0:
        return 0
    if level >= 60:  # noqa: PLR2004 — ZZZ level cap
        return 5
    # (level - 1) // 10 gives the tier — lv 1..10 → 0, 11..20 → 1, etc.
    return (level - 1) // 10


# Cross-character medians of ``promotionStats[5][field] / base[field]``
# from ZO's allStat_gen.json (49 ZZZ characters). Used as a fallback
# when an agent's row doesn't have ``promotion_stats`` populated — typical
# error vs. real game data is under 3% for HP/DEF, under 5% for ATK.
_FALLBACK_PROMO5_RATIOS: dict[str, float] = {
    "hp": 3.43,
    "atk": 1.79,
    "def": 3.44,
}

# ZZZ W-Engine per-level ATK multiplier in basis points. Index = level
# (1..60); value = atk_multiplier from ZO's ``allWengine`` table.
# Total ATK at level L with ascension A:
#   atk_total = atk_base × (1 + atk_multiplier[L] / 10000 + 0.8922 × A)
# Ascension is ``floor(L / 10)`` clamped to [0, 5].
_WENGINE_ATK_MULTIPLIER_BP: tuple[int, ...] = (
    0,
    1568,
    3136,
    4705,
    6273,
    7841,
    9409,
    10977,
    12545,
    14114,
    15682,
    17250,
    18818,
    20386,
    21954,
    23523,
    25091,
    26659,
    28227,
    29795,
    31363,
    32932,
    34500,
    36068,
    37636,
    39204,
    40772,
    42341,
    43909,
    45477,
    47045,
    48613,
    50181,
    51750,
    53318,
    54886,
    56454,
    58022,
    59590,
    61159,
    62727,
    64295,
    65863,
    67431,
    68999,
    70568,
    72136,
    73704,
    75272,
    76840,
    78408,
    79977,
    81545,
    83113,
    84681,
    86249,
    87817,
    89386,
    90954,
    92522,
    94090,
)


def _wengine_ascension(level: int) -> int:
    """ZZZ W-Engine ascension tier (0..5) for a 1-indexed level."""
    return max(0, min(5, level // 10))


def _scaled_wengine_atk(base_atk: int, level: int) -> int:
    """ATK contribution from a W-Engine at the given level.

    Uses ZO's documented formula:
      atk_total = atk_base × (1 + atk_multiplier[level] / 10000 + 0.8922 × ascension)
    """
    level = max(level, 1)
    if level >= len(_WENGINE_ATK_MULTIPLIER_BP):
        level = len(_WENGINE_ATK_MULTIPLIER_BP) - 1
    mult_bp = _WENGINE_ATK_MULTIPLIER_BP[level]
    ascension = _wengine_ascension(level)
    factor = 1.0 + mult_bp / 10000.0 + 0.8922 * ascension
    return int(base_atk * factor)


def _scaled_base_stat(
    base: int,
    growth_bp: int,
    level: int,
    promotion_stats: list | None,
    field: str,
) -> int:
    """Compute a level-scaled base stat via base + growth + promotion.

    ZZZ stat formula (matches ZO's char.ts):
      total = base + growth × (level - 1) + promotionStats[promo].field

    where ``growth`` is the decimal per-level increment. Our DB stores
    growth as basis points (× 10000) so we divide by 10000 here.

    When the agent's ``promotion_stats`` haven't been backfilled, we
    fall back to a linearly interpolated estimate: ``promo[5] ≈ base ×
    fallback_ratio[field]``, with intermediate tiers scaled by ``i / 5``
    (the within-tier linearity holds across all 49 characters with
    real data, max deviation 1.5%).
    """
    level = max(level, 1)
    growth_contrib = (growth_bp * (level - 1)) // 10000
    promo = _promotion_for_level(level)

    if promotion_stats and promo < len(promotion_stats):
        promo_bonus = int(promotion_stats[promo].get(field, 0))
    else:
        ratio = _FALLBACK_PROMO5_RATIOS.get(field, 0)
        promo5_estimate = base * ratio
        promo_bonus = int((promo / 5) * promo5_estimate)

    return base + growth_contrib + promo_bonus


def _support_total_hp(support_build: Build) -> int:  # type: ignore[name-defined]  # noqa: PLR0912
    """Estimate the support agent's total HP for HP-scaling formulas.

    Includes agent base HP (level-scaled), Core-passive HP%, disc main/substat
    HP stats, W-Engine passive + secondary HP%, and disc-set 2pc/4pc HP% bonuses.
    """
    agent = support_build.agent
    level = support_build.agent_level or 60
    base_hp = _scaled_base_stat(agent.base_hp, agent.hp_growth, level, agent.promotion_stats, "hp")

    core_tier = (
        support_build.core_skill_level
        if support_build.core_skill_level is not None
        else _MAX_CORE_TIER
    )
    # Core passive flat HP goes into base (per ZO), core HP% goes to initial%.
    core_base = _core_base_deltas(agent.core_stats, core_tier)
    base_hp += core_base.get("hp", 0)

    core_hp_pct = 0
    if agent.core_stats and core_tier < len(agent.core_stats):
        hp_raw = agent.core_stats[core_tier].get("hp_")
        if hp_raw:
            core_hp_pct = int(hp_raw * 10000)

    disc_stats = _discs_to_stat_dicts(support_build.discs or [])
    disc = accumulate_disc_stats(disc_stats)

    # W-engine secondary stat HP% → initial bracket; passive HP% → combat bracket.
    we_initial_hp_pct = 0
    we_combat_hp_pct = 0
    we_secondary_hp_pct = 0
    if support_build.w_engine:
        ref = getattr(support_build, "w_engine_refinement", 1) or 1
        for wmod in load_wengine_modifiers(
            str(support_build.w_engine.hakushin_id),
            refinement=ref,
        ):
            if wmod.stat == "hp_pct":
                we_initial_hp_pct += wmod.value
            elif wmod.stat == "final_hp_pct":
                we_combat_hp_pct += wmod.value

        sec_type = support_build.w_engine.secondary_stat_type
        if hasattr(sec_type, "value"):
            sec_type = sec_type.value
        if sec_type == "hp_pct":
            sec_value = support_build.w_engine.secondary_stat_value or 0
            we_level = support_build.w_engine_level or 60
            ascension = _wengine_ascension(we_level)
            we_secondary_hp_pct = round(sec_value * (1.0 + 0.3 * ascension))

    # Disc set 2pc HP% → initial bracket; 4pc final_hp_pct → combat bracket.
    disc_set_initial_hp_pct = 0
    disc_set_combat_hp_pct = 0
    sup_set_counts = _count_disc_sets(support_build.discs or [])
    for set_hid, count in sup_set_counts.items():
        for smod in load_disc_set_modifiers(str(set_hid)):
            is_2pc = smod.source == ModifierSource.DISC_SET_2PC and count >= _MIN_2PC
            is_4pc = smod.source == ModifierSource.DISC_SET_4PC and count >= _MIN_4PC
            if is_2pc or is_4pc:
                if smod.stat == "hp_pct":
                    disc_set_initial_hp_pct += smod.value
                elif smod.stat == "final_hp_pct":
                    disc_set_combat_hp_pct += smod.value

    initial_hp_pct = (
        core_hp_pct
        + disc.hp_pct
        + we_initial_hp_pct
        + we_secondary_hp_pct
        + disc_set_initial_hp_pct
    )
    combat_hp_pct = we_combat_hp_pct + disc_set_combat_hp_pct
    initial_hp = int(base_hp * (1 + initial_hp_pct / 10000) + disc.flat_hp)
    return int(initial_hp * (1 + combat_hp_pct / 10000))


def _support_total_atk(support_build: Build) -> int:  # type: ignore[name-defined]
    """Estimate the support agent's total ATK for ATK-scaling formulas."""
    agent = support_build.agent
    level = support_build.agent_level or 60
    base_atk = _scaled_base_stat(
        agent.base_atk,
        agent.atk_growth,
        level,
        agent.promotion_stats,
        "atk",
    )

    core_tier = (
        support_build.core_skill_level
        if support_build.core_skill_level is not None
        else _MAX_CORE_TIER
    )
    core_base = _core_base_deltas(agent.core_stats, core_tier)
    base_atk += core_base.get("atk", 0)

    wengine_base = 0
    atk_pct = 0
    flat_atk = 0
    final_atk_pct = 0
    if support_build.w_engine:
        wengine_base = _scaled_wengine_atk(
            support_build.w_engine.base_atk,
            support_build.w_engine_level or 60,
        )
        ref = getattr(support_build, "w_engine_refinement", 1) or 1
        for wmod in load_wengine_modifiers(
            str(support_build.w_engine.hakushin_id),
            refinement=ref,
        ):
            if wmod.stat == "atk_pct":
                atk_pct += wmod.value
            elif wmod.stat == "final_atk_pct":
                final_atk_pct += wmod.value
            elif wmod.stat == "flat_atk":
                flat_atk += wmod.value
        sec_type = support_build.w_engine.secondary_stat_type
        if hasattr(sec_type, "value"):
            sec_type = sec_type.value
        if sec_type == "atk_pct":
            sec_val = support_build.w_engine.secondary_stat_value or 0
            we_level = support_build.w_engine_level or 60
            atk_pct += round(sec_val * (1.0 + 0.3 * _wengine_ascension(we_level)))

    disc_stats = _discs_to_stat_dicts(support_build.discs or [])
    disc = accumulate_disc_stats(disc_stats)
    atk_pct += disc.atk_pct
    flat_atk += disc.flat_atk

    total_base = base_atk + wengine_base
    return _floor(
        (total_base * (10000 + atk_pct) / 10000 + flat_atk) * (10000 + final_atk_pct) / 10000
    )


def _support_base_atk(support_build: Build) -> int:  # type: ignore[name-defined]
    """Compute the support agent's base ATK (level-scaled + core passive deltas)."""
    agent = support_build.agent
    level = support_build.agent_level or 60
    base_atk = _scaled_base_stat(
        agent.base_atk,
        agent.atk_growth,
        level,
        agent.promotion_stats,
        "atk",
    )
    core_tier = (
        support_build.core_skill_level
        if support_build.core_skill_level is not None
        else _MAX_CORE_TIER
    )
    core_base = _core_base_deltas(agent.core_stats, core_tier)
    base_atk += core_base.get("atk", 0)
    return base_atk


def _initial_def(owner_build: Build) -> int:  # type: ignore[name-defined]
    """The owner's initial DEF — ZO's ``own.initial.def``.

    Equipment-inclusive, combat-buff-exclusive: base DEF (level-scaled, plus core
    flat DEF) grown by the initial-bracket DEF% sources (core, discs, W-Engine
    passive + secondary, disc-set 2pc) and the disc flat DEF. ``final_def_pct``
    is deliberately excluded — it is the combat bracket, and Ben's core reads
    *initial* DEF ("Ben's initial ATK increases along with his initial DEF").
    """
    agent = owner_build.agent
    level = owner_build.agent_level or 60
    base_def = _scaled_base_stat(
        agent.base_def,
        agent.def_growth,
        level,
        agent.promotion_stats,
        "def",
    )

    core_tier = (
        owner_build.core_skill_level
        if owner_build.core_skill_level is not None
        else _MAX_CORE_TIER
    )
    base_def += _core_base_deltas(agent.core_stats, core_tier).get("def", 0)

    def_pct = 0
    if agent.core_stats and core_tier < len(agent.core_stats):
        def_raw = agent.core_stats[core_tier].get("def_")
        if def_raw:
            def_pct += int(def_raw * 10000)

    if owner_build.w_engine:
        ref = getattr(owner_build, "w_engine_refinement", 1) or 1
        for wmod in load_wengine_modifiers(
            str(owner_build.w_engine.hakushin_id),
            refinement=ref,
        ):
            if wmod.stat == "def_pct":
                def_pct += wmod.value

        sec_type = owner_build.w_engine.secondary_stat_type
        if hasattr(sec_type, "value"):
            sec_type = sec_type.value
        if sec_type == "def_pct":
            sec_value = owner_build.w_engine.secondary_stat_value or 0
            we_level = owner_build.w_engine_level or 60
            def_pct += round(sec_value * (1.0 + 0.3 * _wengine_ascension(we_level)))

    for set_hid, count in _count_disc_sets(owner_build.discs or []).items():
        if count < _MIN_2PC:
            continue
        for smod in load_disc_set_modifiers(str(set_hid)):
            if smod.source == ModifierSource.DISC_SET_2PC and smod.stat == "def_pct":
                def_pct += smod.value

    disc = accumulate_disc_stats(_discs_to_stat_dicts(owner_build.discs or []))
    def_pct += disc.def_pct

    return _floor(base_def * (10000 + def_pct) / 10000 + disc.flat_def)


def _bake_stat_scaled_modifier(mod: Modifier, basis: int) -> Modifier:
    """Return a copy of *mod* with its ratio-scaled value baked in.

    baked = basis * scaling_ratio // 10000 (+ ``value`` as an additive offset).
    A zero ratio bakes nothing — the modifier keeps its literal value and its
    ``scaling_stat``, which L0 reports as an incoherent scale field.
    """
    if mod.scaling_ratio <= 0:
        return mod
    baked = _floor(basis * mod.scaling_ratio / 10000)
    if mod.value:
        baked += mod.value
    return dc_replace(mod, value=baked, scaling_stat=None, scaling_ratio=0.0)


def _bake_am_excess_modifier(mod: Modifier, am: int) -> Modifier:
    """Bake an anomaly_mastery_excess scaled modifier into a flat value.

    excess = max(0, am - threshold); baked = floor(excess * ratio).
    Condition is stripped to ALWAYS — value=0 already encodes the threshold gate.
    """
    excess = max(0, am - mod.excess_threshold)
    baked = _floor(excess * mod.scaling_ratio)
    return dc_replace(
        mod,
        value=baked,
        scaling_stat=None,
        scaling_ratio=0.0,
        conditions=(Condition.ALWAYS,),
    )


def _bake_capped_excess_modifier(mod: Modifier, basis: int) -> Modifier:
    """Bake an excess-over-threshold modifier whose growth is CAPPED.

    ``baked = min(value, floor(max(0, basis - excess_threshold) * scaling_ratio))``

    Shape: "if <stat> exceeds T, each extra point grants R, up to a maximum of C" —
    Jane's Passion (AP > 120 → +2 ATK each, max 600) and her M1 (AP → +0.1% DMG each,
    max 30%).

    `value` IS THE CAP here. That is deliberately the *existing* convention
    (`hp_scale_per_unit` and `atk_scale_ratio` both already read `value` as a cap),
    not a fourth invention — `value` already means three different things across the
    bakers, so the whole set is spelled out here rather than left to be rediscovered:

    ======================================  ==========================================
    baker / mechanism                       meaning of ``value``
    ======================================  ==========================================
    ``_bake_stat_scaled_modifier``          additive OFFSET applied after scaling
    ``_bake_am_excess_modifier``            IGNORED — overwritten by the baked result
    ``hp_scale_per_unit`` / ``atk_scale_ratio``  the CAP
    ``_bake_capped_excess_modifier``        the CAP (this one)
    ======================================  ==========================================

    A cap of 0 would bake everything to 0, which is never what a kit means, so it is
    treated as "no cap authored" and the uncapped result is returned — L0 reports the
    incoherent scale field rather than the engine silently zeroing a real buff.

    Condition is stripped to ALWAYS: the threshold gate is already encoded in the
    arithmetic, matching :func:`_bake_am_excess_modifier`.
    """
    if mod.scaling_ratio <= 0:
        return mod
    excess = max(0, basis - mod.excess_threshold)
    baked = _floor(excess * mod.scaling_ratio)
    if mod.value > 0:
        baked = min(mod.value, baked)
    return dc_replace(
        mod,
        value=baked,
        scaling_stat=None,
        scaling_ratio=0.0,
        conditions=(Condition.ALWAYS,),
    )


def _am_from_modifiers(modifiers: list[Modifier]) -> tuple[int, int]:
    """Sum flat and pct (bp) Anomaly Mastery contributions from a modifier list.

    Summed unconditionally — AM is not typically a conditional stat, so conditional
    AM mods (if any) would be slightly over-counted; matches build/support symmetry.
    """
    am_flat = 0
    am_pct = 0
    for mod in modifiers:
        if mod.stat == "anomaly_mastery":
            am_flat += mod.value
        elif mod.stat == "anomaly_mastery_pct":
            am_pct += mod.value
    return am_flat, am_pct


def _compute_build_am(
    base_am: int,
    disc_stats: list[dict],
    modifiers: list[Modifier],
) -> int:
    """Compute total AM from base + disc + already-collected modifier list.

    Used at snapshot-build time to bake AM-excess modifiers before they are
    handed to resolve_modifiers.  Covers all unconditional AM sources; conditional
    AM mods (if any) would be under-counted, but AM is not typically conditional.
    """
    disc = accumulate_disc_stats(disc_stats)
    mod_flat, am_pct = _am_from_modifiers(modifiers)
    am_flat = disc.anomaly_mastery + mod_flat
    return _floor(base_am * (10000 + am_pct) / 10000) + am_flat


def _support_total_am(support_build: Build) -> int:  # type: ignore[name-defined]
    """Compute a support's total AM for excess baking.

    Mirrors :func:`_compute_build_am`: base + disc + W-Engine secondary, plus AM
    granted by the support's own kit (mindscape-gated), W-Engine passive, and
    disc-set modifiers — so a support's AM-excess buffs bake off the same AM the
    agent would have as a main DPS.
    """
    agent = support_build.agent
    base_am = agent.base_anomaly_mastery
    disc_stats = _discs_to_stat_dicts(support_build.discs or [])
    disc = accumulate_disc_stats(disc_stats)
    am_flat = disc.anomaly_mastery
    am_pct = 0

    # Kit / W-Engine passive / disc-set AM modifiers (AM is a personal stat, so
    # include all targets — not just team-propagated ones).
    support_mc = support_build.mindscape_level or 0
    support_potential = getattr(support_build, "potential_rank", 6)
    am_mods = [
        m
        for m in load_agent_modifiers(str(agent.hakushin_id))
        if mindscape_allows(m, support_mc) and potential_allows(m, support_potential)
    ]
    if support_build.w_engine:
        sup_ref = getattr(support_build, "w_engine_refinement", 1) or 1
        am_mods.extend(
            load_wengine_modifiers(str(support_build.w_engine.hakushin_id), refinement=sup_ref)
        )
    for set_hid, count in _count_disc_sets(support_build.discs or []).items():
        if count >= _MIN_2PC:
            for mod in load_disc_set_modifiers(str(set_hid)):
                is_2pc = mod.source == ModifierSource.DISC_SET_2PC and count >= _MIN_2PC
                is_4pc = mod.source == ModifierSource.DISC_SET_4PC and count >= _MIN_4PC
                if is_2pc or is_4pc:
                    am_mods.append(mod)
    mod_flat, mod_pct = _am_from_modifiers(am_mods)
    am_flat += mod_flat
    am_pct += mod_pct

    if support_build.w_engine:
        sec_type = support_build.w_engine.secondary_stat_type
        if hasattr(sec_type, "value"):
            sec_type = sec_type.value
        sec_value = support_build.w_engine.secondary_stat_value or 0
        if sec_type == "anomaly_mastery_pct" and sec_value:
            we_level = support_build.w_engine_level or 60
            am_pct += round(sec_value * (1.0 + 0.3 * _wengine_ascension(we_level)))
        elif sec_type == "anomaly_mastery" and sec_value:
            we_level = support_build.w_engine_level or 60
            am_flat += round(sec_value * (1.0 + 0.3 * _wengine_ascension(we_level)))
    return _floor(base_am * (10000 + am_pct) / 10000) + am_flat


def _support_total_pen_ratio(support_build: Build) -> int:  # type: ignore[name-defined]
    """Compute a support's total PEN Ratio for pen_ratio-basis scaling (C8).

    PEN Ratio has no base/pct split — it is a flat basis-point accumulator (agent
    base + disc). Mirrors :func:`_support_total_am` in also including PEN Ratio
    granted by the support's own kit (mindscape-gated), W-Engine passive, and
    disc-set modifiers, so a PEN-Ratio-scaled buff (Rina's core: "25% of Rina's
    own PEN Ratio") bakes off the same PEN Ratio the agent would carry as a
    main DPS.
    """
    agent = support_build.agent
    disc = accumulate_disc_stats(_discs_to_stat_dicts(support_build.discs or []))
    pen_ratio = agent.base_pen_ratio + disc.pen_ratio

    support_mc = support_build.mindscape_level or 0
    pen_mods = [
        m
        for m in load_agent_modifiers(str(agent.hakushin_id))
        if mindscape_allows(m, support_mc)
        and potential_allows(m, getattr(support_build, "potential_rank", 6))
    ]
    if support_build.w_engine:
        sup_ref = getattr(support_build, "w_engine_refinement", 1) or 1
        pen_mods.extend(
            load_wengine_modifiers(str(support_build.w_engine.hakushin_id), refinement=sup_ref)
        )
    for set_hid, count in _count_disc_sets(support_build.discs or []).items():
        if count >= _MIN_2PC:
            for mod in load_disc_set_modifiers(str(set_hid)):
                is_2pc = mod.source == ModifierSource.DISC_SET_2PC and count >= _MIN_2PC
                is_4pc = mod.source == ModifierSource.DISC_SET_4PC and count >= _MIN_4PC
                if is_2pc or is_4pc:
                    pen_mods.append(mod)
    pen_ratio += sum(m.value for m in pen_mods if m.stat == "pen_ratio")

    if support_build.w_engine:
        sec_type = support_build.w_engine.secondary_stat_type
        if hasattr(sec_type, "value"):
            sec_type = sec_type.value
        sec_value = support_build.w_engine.secondary_stat_value or 0
        if sec_type == "pen_ratio" and sec_value:
            we_level = support_build.w_engine_level or 60
            pen_ratio += round(sec_value * (1.0 + 0.3 * _wengine_ascension(we_level)))
    return pen_ratio


def _impact_from_modifiers(modifiers: list[Modifier]) -> tuple[int, int]:
    """Sum flat and pct (bp) Impact contributions from a modifier list."""
    impact_flat = 0
    impact_pct = 0
    for mod in modifiers:
        if mod.stat == "impact":
            impact_flat += mod.value
        elif mod.stat == "impact_pct":
            impact_pct += mod.value
    return impact_flat, impact_pct


def _ap_from_modifiers(modifiers: list[Modifier]) -> tuple[int, int]:
    """Sum flat and pct (bp) Anomaly Proficiency contributions from a modifier list.

    Two flat keys exist for AP (`anomaly_proficiency` and the disc-set alias
    `anomaly_proficiency_flat`, see buff_resolver's _STAT_TO_INPUT); both count.
    """
    ap_flat = 0
    ap_pct = 0
    for mod in modifiers:
        if mod.stat in {"anomaly_proficiency", "anomaly_proficiency_flat"}:
            ap_flat += mod.value
        elif mod.stat == "anomaly_proficiency_pct":
            ap_pct += mod.value
    return ap_flat, ap_pct


def _support_total_ap(support_build: Build) -> int:  # type: ignore[name-defined]
    """Compute a build's total Anomaly Proficiency for AP-basis scaling (Track C4).

    Same bracket structure as :func:`_support_total_impact`: base AP takes the
    percent (Initial Stat rule), flat AP from discs / kit / W-Engine / disc sets is
    added after.

    KNOWN LIMITATION, and it must be restated on every kit row that uses this basis:
    ZO scales these off ``own.final.anomProf`` — AP *after* combat buffs. This bakes
    at snapshot time, so the basis is PRE-combat AP and any team buffing AP (Astra,
    Yuzuha, …) under-counts. That is the same limitation `anomaly_mastery_excess`
    already accepts, so the engine stays internally consistent — and it is still a
    large improvement on the status quo, which is a silent zero.
    """
    agent = support_build.agent
    base_ap = agent.base_anomaly_proficiency
    disc = accumulate_disc_stats(_discs_to_stat_dicts(support_build.discs or []))
    ap_flat = disc.anomaly_proficiency
    ap_pct = 0

    support_mc = support_build.mindscape_level or 0
    ap_mods = [
        m
        for m in load_agent_modifiers(str(agent.hakushin_id))
        if mindscape_allows(m, support_mc)
        and potential_allows(m, getattr(support_build, "potential_rank", 6))
    ]
    if support_build.w_engine:
        sup_ref = getattr(support_build, "w_engine_refinement", 1) or 1
        ap_mods.extend(
            load_wengine_modifiers(str(support_build.w_engine.hakushin_id), refinement=sup_ref)
        )
    for set_hid, count in _count_disc_sets(support_build.discs or []).items():
        if count >= _MIN_2PC:
            for mod in load_disc_set_modifiers(str(set_hid)):
                is_2pc = mod.source == ModifierSource.DISC_SET_2PC and count >= _MIN_2PC
                is_4pc = mod.source == ModifierSource.DISC_SET_4PC and count >= _MIN_4PC
                if is_2pc or is_4pc:
                    ap_mods.append(mod)
    mod_flat, mod_pct = _ap_from_modifiers(ap_mods)
    ap_flat += mod_flat
    ap_pct += mod_pct

    if support_build.w_engine:
        sec_type = support_build.w_engine.secondary_stat_type
        if hasattr(sec_type, "value"):
            sec_type = sec_type.value
        sec_value = support_build.w_engine.secondary_stat_value or 0
        if sec_type in {"anomaly_proficiency", "anomaly_proficiency_flat"} and sec_value:
            we_level = support_build.w_engine_level or 60
            ap_flat += round(sec_value * (1.0 + 0.3 * _wengine_ascension(we_level)))
    return _floor(base_ap * (10000 + ap_pct) / 10000) + ap_flat


def _support_total_impact(support_build: Build) -> int:  # type: ignore[name-defined]
    """Compute a support's total Impact for impact-basis scaling (C8).

    Mirrors :func:`_support_total_am`'s bracket structure: agent base Impact% is
    the Initial Stat rule (percent applies to base only), flat Impact (disc +
    kit/W-Engine/disc-set) is added after — matching
    :func:`app.services.stat_calculator.compute_total_stats`'s impact formula,
    and inclusive of the support's own kit so an Impact-scaled buff (Qingyi's
    core: flat ATK from own Impact above a threshold) bakes off the same Impact
    the agent would carry as a main DPS.
    """
    agent = support_build.agent
    base_impact = agent.base_impact
    disc = accumulate_disc_stats(_discs_to_stat_dicts(support_build.discs or []))
    impact_flat = disc.impact
    impact_pct = 0

    support_mc = support_build.mindscape_level or 0
    impact_mods = [
        m
        for m in load_agent_modifiers(str(agent.hakushin_id))
        if mindscape_allows(m, support_mc)
        and potential_allows(m, getattr(support_build, "potential_rank", 6))
    ]
    if support_build.w_engine:
        sup_ref = getattr(support_build, "w_engine_refinement", 1) or 1
        impact_mods.extend(
            load_wengine_modifiers(str(support_build.w_engine.hakushin_id), refinement=sup_ref)
        )
    for set_hid, count in _count_disc_sets(support_build.discs or []).items():
        if count >= _MIN_2PC:
            for mod in load_disc_set_modifiers(str(set_hid)):
                is_2pc = mod.source == ModifierSource.DISC_SET_2PC and count >= _MIN_2PC
                is_4pc = mod.source == ModifierSource.DISC_SET_4PC and count >= _MIN_4PC
                if is_2pc or is_4pc:
                    impact_mods.append(mod)
    mod_flat, mod_pct = _impact_from_modifiers(impact_mods)
    impact_flat += mod_flat
    impact_pct += mod_pct

    if support_build.w_engine:
        sec_type = support_build.w_engine.secondary_stat_type
        if hasattr(sec_type, "value"):
            sec_type = sec_type.value
        sec_value = support_build.w_engine.secondary_stat_value or 0
        if sec_type == "impact" and sec_value:
            we_level = support_build.w_engine_level or 60
            impact_flat += round(sec_value * (1.0 + 0.3 * _wengine_ascension(we_level)))
    return _floor(base_impact * (10000 + impact_pct) / 10000) + impact_flat


def _bake_hp_scaled_modifier(mod: Modifier, support_hp: int) -> Modifier:
    """Return a copy of *mod* with its HP-scaled value baked in."""
    extra_units = max(0, support_hp - mod.hp_scale_threshold) // mod.hp_scale_per_unit
    baked = min(mod.value, mod.hp_scale_base + extra_units * mod.hp_scale_unit)
    return dc_replace(
        mod,
        value=baked,
        hp_scale_base=0,
        hp_scale_threshold=0,
        hp_scale_per_unit=0,
        hp_scale_unit=0,
    )


def _bake_atk_scaled_modifier(mod: Modifier, support_atk: int) -> Modifier:
    """Return a copy of *mod* with ATK-scaled value baked in.

    baked = min(value, floor(support_atk * atk_scale_ratio / 10000) + flat_addend)
    """
    baked = min(mod.value, _floor(support_atk * mod.atk_scale_ratio / 10000) + mod.flat_addend)
    return dc_replace(mod, value=baked, atk_scale_ratio=0, flat_addend=0)


# ---------------------------------------------------------------------------
# Bake dispatch (C1)
# ---------------------------------------------------------------------------
#
# `scaling_stat` names a BASIS: a stat of the modifier's own owner that its value
# is derived from at snapshot-build time. This table is the schema contract —
# scripts/validate_kits.py (L0) reads it out of this module and hard-fails any kit
# JSON naming a basis that is not a key here, because such a modifier is never
# baked: it loads, it renders a buff chip, and it contributes nothing to the calc.
#
# To add a basis: add one row here and its provider to _BASIS_PROVIDERS.
#
# Absent on purpose:
#   `hp` — the Rupture HP→SheerForce intrinsic (Manato, Yidhari, Yixuan: 0.1 SheerForce
#   per point of Max HP) is NOT an ATK buff and is not expressible as one. It lives in
#   `_SHEER_INTRINSIC_HP_RATIOS` and is applied by resolve_sheer_force off *final* HP.
#   See D-KV9. `hp_scale_per_unit` / `atk_scale_ratio` are separate mechanisms with
#   their own fields, baked by _bake_owner_scaled below.
_SCALING_BAKERS: dict[str, tuple[str, Callable[[Modifier, int], Modifier]]] = {
    "base_atk": ("base_atk", _bake_stat_scaled_modifier),
    "def": ("initial_def", _bake_stat_scaled_modifier),
    "anomaly_mastery_excess": ("anomaly_mastery", _bake_am_excess_modifier),
    "pen_ratio": ("total_pen_ratio", _bake_stat_scaled_modifier),
    "impact": ("total_impact", _bake_stat_scaled_modifier),
    # Track C4 — the last missing scaling basis. See _support_total_ap for the
    # pre-combat-basis limitation this inherits from the anomaly_mastery_excess path.
    "anomaly_proficiency_excess": ("anomaly_proficiency", _bake_capped_excess_modifier),
}

_BASIS_PROVIDERS: dict[str, Callable[[Build], int]] = {  # type: ignore[name-defined]
    "base_atk": _support_base_atk,
    "initial_def": _initial_def,
    "anomaly_mastery": _support_total_am,
    "total_hp": _support_total_hp,
    "total_atk": _support_total_atk,
    "total_pen_ratio": _support_total_pen_ratio,
    "total_impact": _support_total_impact,
    "anomaly_proficiency": _support_total_ap,
}


class _ScalingBases:
    """The owner stats a modifier can bake against, computed at most once each.

    Every basis re-derives the owner's equipment-inclusive stats, so it is resolved
    lazily: a build whose modifiers scale off nothing pays for nothing.
    """

    def __init__(
        self,
        owner_build: Build,  # type: ignore[name-defined]
        *,
        anomaly_mastery: int | None = None,
    ) -> None:
        self._build = owner_build
        self._cache: dict[str, int] = {}
        # The DPS's AM depends on AM granted by the modifier list itself, so the
        # caller computes it once every source is collected and passes it in.
        if anomaly_mastery is not None:
            self._cache["anomaly_mastery"] = anomaly_mastery

    def get(self, basis: str) -> int:
        if basis not in self._cache:
            self._cache[basis] = _BASIS_PROVIDERS[basis](self._build)
        return self._cache[basis]


def _bake_owner_scaled(mod: Modifier, bases: _ScalingBases) -> Modifier:
    """Bake every owner-derived scale field on *mod* into a literal value.

    Three independent mechanisms:
      * ``scaling_stat``       → dispatched through _SCALING_BAKERS
      * ``hp_scale_per_unit``  → stepped HP scaling, capped at ``value``
      * ``atk_scale_ratio``    → percent-of-ATK, capped at ``value``

    Each baker clears the fields it consumed, so re-running this on an already-baked
    modifier is a no-op. That is what makes it safe to run over the DPS's whole
    modifier list: support modifiers arrive already baked against *their* owner's
    stats, and are left alone here.
    """
    entry = _SCALING_BAKERS.get(mod.scaling_stat or "")
    if entry is not None:
        basis, baker = entry
        mod = baker(mod, bases.get(basis))
    if mod.hp_scale_per_unit:
        mod = _bake_hp_scaled_modifier(mod, bases.get("total_hp"))
    if mod.atk_scale_ratio:
        mod = _bake_atk_scaled_modifier(mod, bases.get("total_atk"))
    return mod


def applicable_set_modifiers(
    set_counts: dict[int, int],
    disc_set_modifiers: dict[int, list[Modifier]],
    equipper_specialty: str = "",
    equipper_element: str = "",
    equipper_name: str = "",
) -> list[Modifier]:
    """2pc / 4pc rows for sets whose piece count is met, equipper gates resolved.

    The single home for this. It previously existed as two byte-identical
    private copies -- one in `disc_optimizer`, one in `scorer_support` -- which
    drifted: #172 taught the optimizer's copy to resolve ``equipper_is_*`` and
    the scorer's silently kept dropping every gated row, so the disc ranker
    under-scored Lumiflux builds by the same 2.3% the optimizer had. #173 fixed
    the second copy; this removes the possibility of a third divergence.

    ``equipper_*`` default to empty strings, which makes
    :func:`resolve_equipper_conditions` drop any row it cannot satisfy -- the
    conservative direction for a caller with no equipper context.
    """
    out: list[Modifier] = []
    for set_id, count in set_counts.items():
        for mod in disc_set_modifiers.get(set_id, []):
            if not (
                (mod.source == ModifierSource.DISC_SET_2PC and count >= _MIN_2PC)
                or (mod.source == ModifierSource.DISC_SET_4PC and count >= _MIN_4PC)
            ):
                continue
            resolved = resolve_equipper_conditions(
                mod, equipper_specialty, equipper_element, equipper_name
            )
            if resolved is not None:
                out.append(resolved)
    return out


def resolve_equipper_conditions(
    mod: Modifier,
    support_specialty: str,
    support_element: str,
    support_name: str = "",
) -> Modifier | None:
    """Strip ``equipper_is_*`` conditions by checking them against the support.

    ``equipper_is_*`` conditions in support modifiers refer to the SUPPORT's
    own properties, not the DPS's.  We resolve them at collection time so the
    remaining conditions are evaluated against the DPS's active conditions.

    ``support_name`` extends the owned set with the agent-identity family
    (``equipper_is_pyrois`` — Sol Exuvia's "When the equipper is Pyrois" gate).
    It defaults to empty, which — like the other two — makes an identity-gated
    row drop for a caller with no equipper context: the conservative direction.

    Returns None if any ``equipper_is_*`` condition is NOT met → caller drops
    the modifier.  Returns a (possibly new) Modifier without the resolved
    conditions if all are met.
    """
    support_owned = {
        f"equipper_is_{support_specialty}",
        f"equipper_is_{support_element}",
    }
    if support_name:
        support_owned.add(f"equipper_is_{_slugify(support_name)}")
    remaining: list[Condition] = []
    for cond in mod.conditions:
        val = cond.value
        if val.startswith("equipper_is_"):
            if val not in support_owned:
                return None  # condition not met — drop modifier
            # condition met — resolved, don't carry it forward
        else:
            remaining.append(cond)

    remaining_tuple = tuple(remaining) if remaining else (Condition.ALWAYS,)
    if remaining_tuple == mod.conditions:
        return mod  # no change needed

    # `dc_replace`, not a hand-listed rebuild. The rebuild this replaces enumerated
    # ~11 of `Modifier`'s fields, so every field added to the dataclass afterwards was
    # silently dropped on any row whose gate actually resolved — `element_scope`,
    # `scaling_stat`/`scaling_ratio`/`excess_threshold`, `atk_scale_ratio`,
    # `flat_addend`, `min_mindscape`/`max_mindscape`, `notes`. That is a bug which
    # re-arms itself every time the schema grows, and it was live: `sol_exuvia[1]`'s
    # Ether-scoped RES-ignore lost its `element_scope` the moment its Pyrois gate
    # resolved, and `res_ignore` is in `ELEMENT_SCOPE_HONORED_STATS`, so the scope was
    # load-bearing. `_support_modifiers` bakes `scaling_stat` *after* calling this, so
    # the first support row pairing an equipper gate with a scaling basis would have
    # baked to a silent zero. Found by the 2026-08-09 Boisterous Echoes re-audit.
    return dc_replace(mod, conditions=remaining_tuple)


def _support_modifiers(  # noqa: PLR0912
    support_build: Build,  # type: ignore[name-defined]
    disabled_buffs: list[str] | None = None,
) -> list[Modifier]:
    """Collect modifiers contributed by one support Build to the DPS.

    Applies:
    - Agent kit mods filtered by the support's own mindscape_level and
      disabled_buffs (T2.1).
    - Support W-Engine mods that are target=team only (T2.3).
    - Support disc-set 2pc/4pc mods that are target=team only (T2.4).

    Skips core-stat passives — they are personal stats and do not propagate
    to teammates (T2.2).

    ``disabled_buffs``: request-scoped override (DESIGN_buff_context.md §2.1/
    §7 Q1, Task A6). When supplied (not None), replaces
    ``support_build.disabled_buffs`` entirely -- never merged with it. None
    (default) preserves the old build-column read for callers that don't
    resolve a request context.
    """
    support_agent = support_build.agent
    support_mc = support_build.mindscape_level or 0
    support_disabled = (
        set(disabled_buffs)
        if disabled_buffs is not None
        else set(support_build.disabled_buffs or [])
    )
    hid = str(support_agent.hakushin_id)
    sup_specialty = (
        support_agent.specialty.value
        if hasattr(support_agent.specialty, "value")
        else support_agent.specialty
    )
    sup_element = (
        support_agent.element.value
        if hasattr(support_agent.element, "value")
        else support_agent.element
    )

    result: list[Modifier] = []
    bases = _ScalingBases(support_build)
    support_name = support_agent.name

    # T2.1: agent kit mods filtered by support's own mindscape level.
    for mod in load_agent_modifiers(hid):
        if not mindscape_allows(mod, support_mc):
            continue
        if not potential_allows(mod, getattr(support_build, "potential_rank", 6)):
            continue
        if buff_id(hid, mod.source_label) in support_disabled:
            continue
        if mod.target not in (ModifierTarget.TEAM, ModifierTarget.ACTIVE):
            continue
        mod = resolve_equipper_conditions(mod, sup_specialty, sup_element, support_name)
        if mod is None:
            continue
        mod = _bake_owner_scaled(mod, bases)
        result.append(dc_replace(mod, owner_name=support_name))

    # T2.3: support W-Engine — keep only target=team/active modifiers.
    # Resolved against the SUPPORT's identity like T2.1/T2.4: an unresolved
    # `equipper_is_*` left in the row would later be evaluated against the
    # DPS's conditions — wrong equipper (Chief Sidekick on a Fire support
    # buffing a non-Fire DPS must keep its row; the reverse must drop it).
    if support_build.w_engine:
        sup_ref = getattr(support_build, "w_engine_refinement", 1) or 1
        for wmod in load_wengine_modifiers(
            str(support_build.w_engine.hakushin_id),
            refinement=sup_ref,
        ):
            if wmod.target in (ModifierTarget.TEAM, ModifierTarget.ACTIVE):
                wmod = resolve_equipper_conditions(wmod, sup_specialty, sup_element, support_name)
                if wmod is None:
                    continue
                wmod = _bake_owner_scaled(wmod, bases)
                result.append(dc_replace(wmod, owner_name=support_name))

    # T2.4: support disc-set bonuses — keep only target=team/active modifiers.
    sup_set_counts = _count_disc_sets(support_build.discs or [])
    for set_hid, count in sup_set_counts.items():
        if count >= _MIN_2PC:
            for mod in load_disc_set_modifiers(str(set_hid)):
                is_2pc = mod.source == ModifierSource.DISC_SET_2PC and count >= _MIN_2PC
                is_4pc = mod.source == ModifierSource.DISC_SET_4PC and count >= _MIN_4PC
                targets = (ModifierTarget.TEAM, ModifierTarget.ACTIVE)
                if (is_2pc or is_4pc) and mod.target in targets:
                    mod = resolve_equipper_conditions(
                        mod, sup_specialty, sup_element, support_name
                    )
                    if mod is not None:
                        mod = _bake_owner_scaled(mod, bases)
                        result.append(dc_replace(mod, owner_name=support_name))

    return result


def _custom_buff_modifiers(
    custom_buffs: Sequence[Any] | None, disabled: set[str]
) -> list[Modifier]:
    """Synthesized stage buffs, minus the ones this request switched off.

    Filtered on the buff's own `custom:<slug>` id rather than through `buff_id`, which
    agent-qualifies (`<hakushin_id>:<slug>`). A stage buff belongs to the encounter, not
    to an agent — agent-qualifying it would toggle it off for the DPS and leave it on for
    the supports, since each carries a different hakushin id.
    """
    return [
        m for m in synthesize_custom_buffs(custom_buffs or []) if m.source_label not in disabled
    ]


def _resource_costs_of(agent: object) -> dict[str, tuple[float, bool, str]]:
    """``cost_key -> (value, per_sec, resource)`` for an agent, **without triggering IO**.

    Read out of ``__dict__`` rather than by attribute access, and that is the whole point of
    this function. ``resource_costs`` is a lazy relationship: a plain ``agent.resource_costs``
    on an instance that did not eager-load it emits a query, and under asyncpg that is not a
    slow path but a hard ``MissingGreenlet`` — several call sites build a snapshot from a
    partially-loaded Agent (or a plain stub in tests). ``getattr`` with a default does not
    help; the attribute exists, so the descriptor still fires. SQLAlchemy populates
    ``__dict__`` only for attributes it has actually loaded, so a miss here means
    "not loaded", with no query attempted.

    Not loaded reads as **no per-mode costs**, which bills ``Agent.ex_energy_cost`` — exactly
    the behaviour that predates the table, so a caller that forgets the loader option gets
    today's numbers rather than free moves.

    This is also why the repositories eager-load it (``AgentRepository._eager_options``,
    ``BuildRepository.get_by_id``): the fallback is safe, not correct.
    """
    rows = agent.__dict__.get("resource_costs") if hasattr(agent, "__dict__") else None
    if not rows:
        return {}
    return {
        rc.cost_key: (float(rc.value), bool(rc.per_sec), str(rc.resource)) for rc in rows
    }


def build_snapshot_from_db(  # noqa: PLR0912, PLR0915
    build: Build,
    agent: Agent,
    *,
    refinement: int | None = None,
    mindscape_level: int | None = None,
    core_skill_level: int | None = None,
    support_builds: list[Build] | None = None,
    disabled_buffs: list[str] | None = None,
    stack_counts: dict[str, int] | None = None,
    custom_buffs: Sequence[Any] | None = None,
) -> BuildSnapshot:
    """Construct a BuildSnapshot from DB models.

    Args:
        build: Build with agent, w_engine, discs eager-loaded.
        agent: Agent model (needed for base stats and hakushin_id).
        refinement: W-Engine refinement level (1-5). None = build.w_engine_refinement.
        mindscape_level: Which mindscape level to include modifiers for.
                         None = use build.mindscape_level.
        custom_buffs: User-authored stage buffs for THIS request (issue #64). Synthesized
                      into ordinary `Modifier` rows alongside every other source, so they
                      are not a special case anywhere downstream.
        core_skill_level: Override the core upgrade tier (0=A..5=F).
                          None = use build.core_skill_level.
        support_builds: Team support builds to fold into the snapshot. Pass an
                        empty list or None for a solo build with no supports.
        disabled_buffs: Request-scoped override (DESIGN_buff_context.md §2.1/
                        §7 Q1, Task A6). When supplied (not None), replaces
                        ``build.disabled_buffs`` for both this build and every
                        support build -- entries are agent-qualified
                        ``buff_id()`` values so one flat list addresses all
                        team members. None (default) preserves the old
                        build-column read, per build, unchanged.
        stack_counts: Request-scoped override (DESIGN_buff_context.md §2.1,
                      issue #94). When supplied (not None), replaces
                      ``build.stack_counts`` on the returned snapshot. None
                      (default) preserves the old build-column read,
                      unchanged.
    """
    # T2.5: default to the build's own refinement rather than a hardcoded 1.
    if refinement is None:
        refinement = getattr(build, "w_engine_refinement", 1) or 1
    mc_level = mindscape_level if mindscape_level is not None else build.mindscape_level
    # #90. Defaults to 5 (unlocked) when the attribute is absent, matching the DB
    # column's own default and the rule the whole migration follows: an unspecified
    # rank means "as fairy behaved before #90".
    #
    # Deliberately NOT defaulting to 0. Every real build carries the column
    # (NOT NULL DEFAULT 5), so the default only ever applies to synthetic or in-memory
    # builds — and those are derived from real ones, e.g. the optimizer's. Defaulting
    # those to LOCKED would silently strip Potential buffs from all 11 agents on paths
    # nobody is looking at, which is a widespread quiet under-credit; defaulting to
    # UNLOCKED can only mis-serve a build that genuinely lost the field, which the
    # NOT NULL constraint prevents.
    _raw_rank = getattr(build, "potential_rank", None)
    # `getattr(..., 5)` alone is not enough: a Build-like object can carry the
    # attribute set to None (reconstructed fixtures, in-memory doubles), and getattr
    # only supplies its default when the attribute is ABSENT. `or 5` is also wrong —
    # rank 0 is falsy and would silently become "unlocked", inverting the gate for
    # exactly the builds it exists to protect.
    potential_rank = 6 if _raw_rank is None else _raw_rank
    core_tier = (
        core_skill_level
        if core_skill_level is not None
        else (build.core_skill_level if build.core_skill_level is not None else _MAX_CORE_TIER)
    )

    # Collect modifiers from all sources
    modifiers: list[Modifier] = []

    disabled = (
        set(disabled_buffs) if disabled_buffs is not None else set(build.disabled_buffs or [])
    )

    def _enabled(hakushin_id: int | str, mod: Modifier) -> bool:
        return buff_id(hakushin_id, mod.source_label) not in disabled

    dps_name = agent.name
    dps_specialty = (
        agent.specialty.value if hasattr(agent.specialty, "value") else str(agent.specialty)
    )
    dps_element = agent.element.value if hasattr(agent.element, "value") else str(agent.element)

    # ``equipper_is_*`` is an ownership fact, resolvable the moment the owner is
    # known — so it is resolved HERE, at collection, for every source the DPS
    # carries, exactly as disc sets always were and supports are in
    # `_support_modifiers`. Before this, nothing on the static path injected the
    # derived conditions at all (`inject_derived_conditions` had no app/ caller),
    # so an equipper-gated row on the DPS's own kit or W-Engine was silently dead
    # — frostfall_sickle[0] and angel_in_the_shell[1]/[2] shipped that way. Found
    # by the Boisterous Echoes audit, 2026-08-08.
    def _resolve_own(mod: Modifier) -> Modifier | None:
        return resolve_equipper_conditions(mod, dps_specialty, dps_element, dps_name)

    # 1. Agent core skill + mindscape modifiers from JSON
    agent_mods = load_agent_modifiers(str(agent.hakushin_id))
    for mod in agent_mods:
        if not mindscape_allows(mod, mc_level):
            continue
        if not potential_allows(mod, potential_rank):
            continue
        if not _enabled(agent.hakushin_id, mod):
            continue
        resolved = _resolve_own(mod)
        if resolved is None:
            continue
        # #90 Track 2: a row whose value is a Potential ramp takes it here, where the
        # agent (and so its ramps) and the build's rank are both in scope.
        # `getattr`: in-memory agent doubles predate this column. None resolves a bound
        # row to 0 (inert) and leaves every unbound row untouched, so a double cannot
        # silently acquire a value.
        resolved = bind_potential_param(
            resolved, potential_rank, getattr(agent, "potential_params", None)
        )
        modifiers.append(dc_replace(resolved, owner_name=dps_name))

    # 1b. Core passive tier bonuses (atk / crit_ / etc. tied to A..F).
    #     ZO's ``coreStats`` data — backfilled to ``Agent.core_stats``.
    #     These are mechanically guaranteed (you can't unequip a core
    #     tier), so no toggle filter; they're always on if the build has
    #     ``core_skill_level`` set.
    #     Flat ATK/HP/DEF from core go into agent_base_* below (not modifiers).
    modifiers.extend(
        dc_replace(m, owner_name=dps_name) for m in _core_modifiers(agent.core_stats, core_tier)
    )
    core_base = _core_base_deltas(agent.core_stats, core_tier)

    # 1c. Support kit buffs from team members.
    _supports = support_builds or []
    for support_build in _supports:
        if support_build.agent is None:
            continue
        modifiers.extend(
            _support_modifiers(support_build, disabled_buffs),
        )

    # 2. W-Engine modifiers (interpolated to refinement)
    if build.w_engine:
        wengine_mods = load_wengine_modifiers(
            str(build.w_engine.hakushin_id),
            refinement=refinement,
        )
        modifiers.extend(
            dc_replace(resolved, owner_name=dps_name)
            for m in wengine_mods
            if (resolved := _resolve_own(m)) is not None
        )

        # 2b. W-Engine secondary stat — scales with ascension.
        # ZO formula: second_statvalue × (1 + 0.3 × ascension).
        # DB stores the level-0 base value in basis points.
        sec_type = build.w_engine.secondary_stat_type
        if hasattr(sec_type, "value"):
            sec_type = sec_type.value
        sec_value = build.w_engine.secondary_stat_value or 0
        if sec_type and sec_value:
            we_level = build.w_engine_level or 60
            ascension = _wengine_ascension(we_level)
            scaled = round(sec_value * (1.0 + 0.3 * ascension))
            modifiers.append(
                Modifier(
                    stat=sec_type,
                    value=scaled,
                    source=ModifierSource.WENGINE_SECONDARY,
                    source_label="W-Engine secondary",
                    owner_name=dps_name,
                )
            )

    # 3. Disc set modifiers (based on equipped set counts)
    # Resolve equipper_is_* conditions against the DPS agent's own
    # specialty/element/name — they're always the equipper of their own discs.
    set_counts = _count_disc_sets(build.discs)
    for set_hakushin_id, count in set_counts.items():
        if count >= _MIN_2PC:
            set_mods = load_disc_set_modifiers(str(set_hakushin_id))
            for mod in set_mods:
                if not (
                    (mod.source == ModifierSource.DISC_SET_2PC and count >= _MIN_2PC)
                    or (mod.source == ModifierSource.DISC_SET_4PC and count >= _MIN_4PC)
                ):
                    continue
                resolved = resolve_equipper_conditions(mod, dps_specialty, dps_element, dps_name)
                if resolved is not None:
                    modifiers.append(dc_replace(resolved, owner_name=dps_name))

    # 4. User-authored stage / Deadly-Assault buffs for this request (issue #64).
    #
    # Appended here — after every kit source, before the AM computation and the
    # owner-scaled bake below — for two reasons. A custom buff granting Anomaly Mastery
    # must count toward `build_am`, which is computed from this list; and while custom
    # buffs never carry a `scaling_stat` today, leaving them out of the bake pass would
    # make that a silent constraint rather than a stated one.
    #
    # Filtered by `disabled_buffs` on their own `custom:<slug>` id rather than through
    # `_enabled`, which agent-qualifies (`<hakushin_id>:<slug>`). A stage buff belongs to
    # the encounter, not to an agent: agent-qualifying it would mean toggling it off for
    # the DPS and leaving it on for the supports.
    modifiers.extend(_custom_buff_modifiers(custom_buffs, disabled))

    # Build disc stats list for stat aggregation
    disc_stats = _discs_to_stat_dicts(build.discs)

    # Bake owner-scaled modifiers now that every source is collected — the AM basis
    # depends on AM granted by the modifier list itself. Support modifiers were
    # already baked against their own owner's stats in _support_modifiers, which
    # clears the fields it consumed, so this pass leaves them alone.
    build_am = _compute_build_am(agent.base_anomaly_mastery, disc_stats, modifiers)
    dps_bases = _ScalingBases(build, anomaly_mastery=build_am)
    modifiers = [_bake_owner_scaled(m, dps_bases) for m in modifiers]

    wengine_base_atk = (
        _scaled_wengine_atk(
            build.w_engine.base_atk,
            build.w_engine_level or 60,
        )
        if build.w_engine
        else 0
    )

    promotion_stats = agent.promotion_stats
    level = build.agent_level or 60
    return BuildSnapshot(
        agent_base_hp=_scaled_base_stat(
            agent.base_hp,
            agent.hp_growth,
            level,
            promotion_stats,
            "hp",
        )
        + core_base.get("hp", 0),
        agent_base_atk=_scaled_base_stat(
            agent.base_atk,
            agent.atk_growth,
            level,
            promotion_stats,
            "atk",
        )
        + core_base.get("atk", 0),
        agent_base_def=_scaled_base_stat(
            agent.base_def,
            agent.def_growth,
            level,
            promotion_stats,
            "def",
        )
        + core_base.get("def", 0),
        agent_crit_rate=agent.base_crit_rate,
        agent_crit_dmg=agent.base_crit_dmg,
        agent_anomaly_proficiency=agent.base_anomaly_proficiency,
        agent_anomaly_mastery=agent.base_anomaly_mastery,
        agent_base_impact=agent.base_impact,
        agent_pen_ratio=agent.base_pen_ratio,
        agent_pen_flat=agent.base_pen_flat,
        wengine_base_atk=wengine_base_atk,
        agent_name=agent.name,
        agent_element=(agent.element.value if hasattr(agent.element, "value") else agent.element),
        agent_specialty=dps_specialty,
        potential_rank=potential_rank,
        agent_faction_id=int(getattr(agent, "faction_id", 0) or 0),
        agent_source_id=str(agent.hakushin_id or ""),
        agent_base_energy_regen=agent.base_energy_regen,
        agent_sheer_force_hp_ratio=_SHEER_INTRINSIC_HP_RATIOS.get(agent.name, 0),
        agent_level=build.agent_level,
        skill_levels=build.skill_levels or "12,12,12,12,12",
        disc_stats=disc_stats,
        modifiers=modifiers,
        stack_counts=(
            dict(stack_counts) if stack_counts is not None else dict(build.stack_counts or {})
        ),
        mindscape_level=mc_level,
        ex_energy_cost=agent.ex_energy_cost,
        resource_costs=_resource_costs_of(agent),
        # Issue #121: record *which* supports were folded in, so the consumers
        # with opposite requirements can each assert what they need instead of
        # trusting their caller. `_supports` is the same list step 1c ran
        # `_support_modifiers` over, and the same `agent is None` skip applies,
        # so this is exactly the set of supports that contributed modifiers.
        folded_supports=tuple(
            (str(sb.id), sb.agent.name) for sb in _supports if sb.agent is not None
        ),
        kit_formulas=resolve_kit_formulas(
            load_agent_formulas(str(agent.hakushin_id)),
            potential_rank=potential_rank,
            mindscape=mc_level,
            # ZO's `char.core` is 0–6; fairy's `core_skill_level` is the 0–5 tier
            # (ezod_importer: `clamp(talent.core - 1, 0, 5)`). The per-core-level
            # tables a formula subscripts (Miyabi's frostburn, Burnice's afterburn)
            # have 7 entries and are indexed by ZO's number, so undo the offset.
            core_level=core_tier + 1,
        ),
    )


def inject_derived_conditions(
    active: ActiveConditions,
    agent: Agent,
    support_builds: list[Build] | None = None,
) -> None:
    """Auto-inject conditions derivable from build state into *active* in-place.

    Adds:
    - ``equipper_is_<specialty>`` from agent.specialty
    - ``equipper_is_<element>`` from agent.element
    - ``same_element_in_team`` if any support shares the DPS element

    When support_builds is provided, it is used for team-element checks.
    """
    specialty = agent.specialty.value if hasattr(agent.specialty, "value") else agent.specialty
    spec_cond = _CONDITION_MAP.get(f"equipper_is_{specialty}")
    if spec_cond is not None:
        active.active.add(spec_cond)

    element = agent.element.value if hasattr(agent.element, "value") else agent.element
    elem_cond = _CONDITION_MAP.get(f"equipper_is_{element}")
    if elem_cond is not None:
        active.active.add(elem_cond)

    # equipper_is_<name-slug> — the agent-identity family (EQUIPPER_IS_PYROIS).
    # The map lookup makes this a no-op for every agent without a registered
    # identity condition, so the family costs nothing until an engine needs it.
    name_cond = _CONDITION_MAP.get(f"equipper_is_{_slugify(agent.name or '')}")
    if name_cond is not None:
        active.active.add(name_cond)

    _support_iter: list[Build] = support_builds or []

    support_elements = [
        (s.agent.element.value if hasattr(s.agent.element, "value") else s.agent.element)
        for s in _support_iter
        if s.agent is not None
    ]
    if element in support_elements:
        active.active.add(Condition.SAME_ELEMENT_IN_TEAM)


# Threshold values for stat-derived condition injection.  Named to avoid
# PLR2004 (magic value) lint errors.  Values mirror the condition enum names.
_AP_GTE_375 = 375
_AM_GTE_115 = 115
_AM_GTE_150 = 150
_CRIT_RATE_GTE_50_BPS = 5000  # 50 % expressed in basis points
_OFF_FIELD_SWAP_WINDOW_S = 5.0  # seconds; Chaos Jazz 4pc window after swap-in


def inject_stat_threshold_conditions(
    active: ActiveConditions,
    stats: TotalStats,
) -> None:
    """Auto-inject stat-threshold conditions based on fully-resolved stats.

    Call this after a preliminary stat computation (before GTE-gated modifiers
    run) so the threshold check uses unconditional stats.  Injecting into
    *active* in-place means the subsequent full damage pass picks up GTE-gated
    modifiers (e.g. Timeweaver Disorder DMG bonus when AP ≥ 375).
    """
    if stats.anomaly_proficiency >= _AP_GTE_375:
        active.active.add(Condition.ANOMALY_PROFICIENCY_GTE_375)
    if stats.anomaly_mastery >= _AM_GTE_115:
        active.active.add(Condition.ANOMALY_MASTERY_GTE_115)
    if stats.anomaly_mastery >= _AM_GTE_150:
        active.active.add(Condition.ANOMALY_MASTERY_GTE_150)
    if stats.crit_rate >= _CRIT_RATE_GTE_50_BPS:
        active.active.add(Condition.CRIT_RATE_GTE_50)
        active.active.add(Condition.CRIT_RATE_ABOVE_THRESHOLD)


def enemy_snapshot_from_db(
    enemy: EnemyProfile,
    element: str,
) -> EnemySnapshot:
    """Construct an EnemySnapshot from a DB model for a specific element."""
    res_map = {
        "physical": enemy.physical_res,
        "fire": enemy.fire_res,
        "ice": enemy.ice_res,
        "electric": enemy.electric_res,
        "ether": enemy.ether_res,
    }
    return EnemySnapshot(
        level=enemy.level,
        base_def=enemy.defense,
        element_res=res_map.get(element, 0),
        stun_dmg_mult=10000 + (enemy.stun_dmg_taken_ratio or 0),
        res_map=res_map,
    )


def attack_multiplier_at_level(attack: Attack, skill_level: int) -> int:
    """Compute the attack multiplier at a given skill level.

    Returns basis points: damage_base + damage_growth * (level - 1).
    """
    return attack.damage_base + attack.damage_growth * (skill_level - 1)


def _count_disc_sets(discs: list[Disc]) -> dict[int, int]:
    """Count how many discs of each set are equipped. Keyed by set hakushin_id."""
    counts: dict[int, int] = Counter()
    for disc in discs:
        if disc.disc_set and hasattr(disc.disc_set, "hakushin_id"):
            counts[disc.disc_set.hakushin_id] += 1
    return dict(counts)


def _discs_to_stat_dicts(discs: list[Disc]) -> list[dict]:
    """Convert Disc ORM models to dicts for accumulate_disc_stats."""
    result = []
    for disc in discs:
        stat_type = disc.main_stat_type
        if hasattr(stat_type, "value"):
            stat_type = stat_type.value
        result.append(
            {
                "main_stat_type": stat_type,
                "main_stat_value": disc.main_stat_value,
                "substats": disc.substats or [],
            }
        )
    return result
