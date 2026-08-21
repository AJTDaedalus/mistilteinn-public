"""Buff resolution — evaluate active modifiers into flat StatInputs.

Takes a build's modifier sheets + user-toggled conditions and produces
the StatInputs that feed into compute_total_stats -> damage calculator.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Modifier,
    ModifierSource,
    ModifierTarget,
)

if TYPE_CHECKING:
    from app.services.stat_calculator import StatInputs

SourceCategory = Literal["agent", "wengine", "disc_set", "base", "discs", "external"]

_SOURCE_TO_CATEGORY: dict[ModifierSource, SourceCategory] = {
    ModifierSource.CORE_SKILL: "agent",
    ModifierSource.ADDITIONAL_ABILITY: "agent",
    ModifierSource.MINDSCAPE: "agent",
    ModifierSource.TEAM_BUFF: "agent",
    ModifierSource.WENGINE_PASSIVE: "wengine",
    ModifierSource.WENGINE_SECONDARY: "wengine",
    ModifierSource.DISC_SET_2PC: "disc_set",
    ModifierSource.DISC_SET_4PC: "disc_set",
    ModifierSource.EXTERNAL: "external",
}


@dataclass(frozen=True)
class Contribution:
    """One labelled contribution to a stat or damage zone.

    Used by the attribution layer to answer "where did this number come
    from?" — each modifier or aggregate source produces one Contribution
    so the UI can list them per-zone.

    Example:
        Contribution(
            source="Core Passive: Sharp-Toothed",
            value=6660,
            source_category="agent",
            source_kind="core_skill",
            owner_agent_name="Ellen Joe",
        )
    """

    source: str  # e.g. "Core F", "M1: CRIT Rate", "Discs (substats)"
    value: int  # basis points (or raw — same units as the stat)

    # Enrichment fields — None on older / synthesised contributions that
    # don't carry sheet metadata. The UI falls back to `source` when absent.
    source_category: SourceCategory | None = None
    source_kind: str | None = None  # ModifierSource.value string
    owner_agent_name: str | None = None  # which agent produced the buff
    description: str | None = None  # reserved; always None in v0.1
    notes: str | None = None  # curator citation/rationale, threaded from Modifier.notes
    condition: str | None = None  # comma-joined Condition values from the source modifier
    # False when this contribution came from a modifier whose `scaling_stat`
    # was never baked to a flat value (snapshot_builder only bakes base_atk /
    # anomaly_mastery_excess) — the buff is real and active but contributes 0
    # (project_scaling_stat_gaps.md). Always True for base/disc/baked-modifier
    # contributions.
    is_modeled: bool = True


# Stats that map directly to StatInputs fields
_STAT_TO_INPUT: dict[str, str] = {
    "hp_pct": "hp_pct",
    "atk_pct": "atk_pct",
    "def_pct": "def_pct",
    "flat_hp": "flat_hp",
    "flat_atk": "flat_atk",
    "flat_def": "flat_def",
    "final_hp_pct": "final_hp_pct",
    "final_atk_pct": "final_atk_pct",
    "final_def_pct": "final_def_pct",
    "final_flat_hp": "final_flat_hp",
    "final_flat_atk": "final_flat_atk",
    "final_flat_def": "final_flat_def",
    "crit_rate": "crit_rate",
    "crit_dmg": "crit_dmg",
    "anomaly_mastery": "anomaly_mastery",
    "anomaly_mastery_flat": "anomaly_mastery",  # W-Engine passives → flat accumulator
    "anomaly_mastery_pct": "am_pct",  # 2-pc sets, W-Engine secondary → % field
    "anomaly_proficiency_flat": "anomaly_proficiency",  # disc sets (Notes from the Chained 4pc)
    "anomaly_proficiency": "anomaly_proficiency",
    "impact": "impact",  # flat Impact (disc main stat, W-Engine flat)
    "impact_pct": "impact_pct",  # 2-pc sets (Shockstar Disco) → % of base Impact
    "energy_regen": "energy_regen",
    "pen_flat": "pen_flat",
    "pen_ratio": "pen_ratio",
    "physical_dmg": "physical_dmg",
    "fire_dmg": "fire_dmg",
    "ice_dmg": "ice_dmg",
    "electric_dmg": "electric_dmg",
    "ether_dmg": "ether_dmg",
    "wind_dmg": "wind_dmg",
}

# Stats that become dmg_bonuses in the damage calculator (not in StatInputs)
_DMG_BONUS_STATS = {
    "dmg_bonus",  # Generic DMG% (goes to all attacks)
    "basic_dmg_bonus",
    "dash_dmg_bonus",
    "dodge_counter_dmg_bonus",
    "special_dmg_bonus",
    "ex_special_dmg_bonus",
    "chain_dmg_bonus",
    "ultimate_dmg_bonus",
    "assist_followup_dmg_bonus",
}

# Stats that affect the enemy / def calculation
_COMBAT_STATS = {
    "res_reduction",
    "res_ignore",
    # Task 19: res-ignore consumed ONLY by `calculate_luminize_damage`. M1
    # (Naive Oath) scopes its 50% to Luminize alone, which `scopes[]` cannot
    # express -- it gates by move category, and Luminize is not a move but a
    # separate emission fired after a trigger move. Kept out of
    # ELEMENT_SCOPE_HONORED_STATS: the clause is All-Attribute, so there is no
    # element to gate on.
    "luminize_res_ignore",
    "def_ignore",
    "vulnerability",
    "anomaly_dmg_bonus",
    # Anomaly CRIT (issue #162). A SEPARATE pool from `crit_rate`/`crit_dmg` —
    # disc CRIT never reaches anomaly damage. Anomaly damage does not crit
    # unless a kit grants it, so both default to 0 and `calculate_anomaly_damage`
    # treats a zero rate as "cannot crit" in every crit mode. Both are in
    # ELEMENT_SCOPE_HONORED_STATS: the grants that exist are element-scoped
    # (Jane's core is Physical/Assault only, ZO `anom_crit_.physical`), so a row
    # must be able to say which anomaly element it applies to.
    "anomaly_crit_rate",
    "anomaly_crit_dmg",
    # Shock-specific anomaly DMG bonus. Added to anomaly_dmg_bonus
    # (was attributed to "Grace M4"; that is wrong — Grace's M4 is an Energy
    # Generation Rate mindscape. The corpus consumer is her Additional Ability
    # 'Pre-Driven Needle', authored under #90.)
    # when anomaly type is Shock (electric). Per Leifa excludes Disorder —
    # that nuance is not yet implemented (TODO: Disorder exclusion).
    "shock_dmg_bonus",
    # Additive bonus multiplier applied only to disorder / polarity damage.
    "disorder_dmg_bonus",
    # Disorder DMG bonus that scales with remaining aura duration in seconds.
    # Value is bonus-per-second in basis points (e.g. 1800 = 18%/s).
    # Naturally capped by max aura duration — no separate cap field needed.
    # Alice core passive: +18%/s remaining Assault duration, max 180% at 10s.
    "disorder_duration_bonus_rate",
    # Sheer Damage (Rupture specialty) — separate additive pool applied as its
    # own multiplicative zone after BoostArea. Does NOT combine with dmg_bonus.
    "sheer_dmg_bonus",
    # Flat Sheer Force granted by W-engines, disc sets, and supports (Lucia,
    # Pan Yinhu). Added directly to SheerForce before the multiplier chain.
    "sheer_force_flat",
    # Anomaly buildup rate bonuses — generic and per-element.
    # Simulator reads these via combat_bonuses.get("{element}_anomaly_buildup").
    "anomaly_buildup",
    "physical_anomaly_buildup",
    "fire_anomaly_buildup",
    "ice_anomaly_buildup",
    "electric_anomaly_buildup",
    "ether_anomaly_buildup",
    "wind_anomaly_buildup",
    # Vortex DMG boost — anomaly_simulator reads via combat_bonuses.get("vortex_dmg_bonus").
    "vortex_dmg_bonus",
    # MV scaling from a stat (e.g. YSG core: MV scales by crit_dmg × factor).
    # Value is the factor in basis points (e.g. 2500 = 0.25).
    "mv_crit_scaling",
    # Additive bonus to the stun damage multiplier itself (basis points).
    # Multiple sources stack. Conditions: typically enemy_stunned.
    "stun_dmg_mult_bonus",
    # Stun area override value in basis points (max, not sum).
    "stun_area_override",
    # Abloom MV scale bonus (Vivian M2: "Abloom from AP raised to 130%").
    # Added to 10000 base in the boost area, same arithmetic as abloom_dmg_bonus.
    "abloom_mv_bonus",
    # Abloom-specific DMG bonus in boost area (e.g. Frostfall Sickle R1=4000=+40%).
    # Stacks additively with abloom_mv_bonus in calculate_abloom_damage.
    "abloom_dmg_bonus",
    # Abloom crit rate base (bp). Aria M1: 2500 (25%). AM-scaling applied at trigger site.
    "abloom_crit_rate",
    # Abloom crit DMG base (bp). Aria M1: 2500 (25%).
    "abloom_crit_dmg",
    # F-11/F-23a: marks the applier's Shatter as the Frost variant (e.g.
    # Miyabi), extending the Frostbite window from 10s to 20s. Any nonzero
    # value counts as "set" — Miyabi's core passive sets it (Task 31, C9).
    "frostbite_frost_variant",
    # Refringe coefficient's flat, condition-gated additive term (Remielle
    # core passive +10% at 3 Anomaly agents; M2 +20%), in bp. Read by
    # anomaly_simulator._resolve_refringe as `refringe_coefficient`'s
    # `flat_bonus_bp` argument (DESIGN_remielle.md §6.1, Task 18).
    "refringe_flat_bonus_bp",
}

# Stats whose consumer honors `Modifier.element_scope` (C7 / D-KV16). A scoped
# row for any other stat is a silent no-op — validate_kits L0 hard-fails it
# rather than letting it ship quietly. Single source of truth: validate_kits
# imports this set instead of restating it.
ELEMENT_SCOPE_HONORED_STATS: frozenset[str] = frozenset(
    {"res_reduction", "res_ignore", "anomaly_crit_rate", "anomaly_crit_dmg"}
)


def _element_scope_excludes(mod: Modifier, damage_element: str | None) -> bool:
    """True if `mod`'s element_scope rules it out for this damage instance.

    Only meaningful for :data:`ELEMENT_SCOPE_HONORED_STATS` and only when the
    caller supplied a damage element to check against — see `resolve_modifiers`'
    `damage_element` docstring for the None case.
    """
    return (
        mod.element_scope is not None
        and mod.stat in ELEMENT_SCOPE_HONORED_STATS
        and damage_element is not None
        and damage_element not in mod.element_scope
    )


def _gated_out(
    mod: Modifier,
    conditions: ActiveConditions,
    *,
    attack_scope: AttackScope,
    target_filter: ModifierTarget,
    include_active: bool = True,
    damage_element: str | None,
) -> bool:
    """True if `mod` fails any of `resolve_modifiers`' gates for this pass."""
    if mod.target not in {target_filter, ModifierTarget.TEAM, ModifierTarget.ACTIVE}:
        return True
    # ACTIVE-target rows are on-field-only. They are included unconditionally
    # above because almost every damage instance IS on-field -- but a Phase
    # Flow tick is not: the simulator resolves it under the OFF-FIELD merge,
    # and scoring it with ACTIVE buffs applied is a bounded over-credit (B3,
    # docs/DESIGN_team_damage_and_crit_eligibility.md).
    if not include_active and mod.target is ModifierTarget.ACTIVE:
        return True
    if not conditions.is_met(mod.conditions):
        return True
    scope_mismatch = (
        AttackScope.ALL not in mod.scopes
        and attack_scope != AttackScope.ALL
        and attack_scope not in mod.scopes
    )
    if scope_mismatch:
        return True
    return _element_scope_excludes(mod, damage_element)


def resolve_modifiers(
    modifiers: list[Modifier],
    conditions: ActiveConditions,
    *,
    attack_scope: AttackScope = AttackScope.ALL,
    target_filter: ModifierTarget = ModifierTarget.SELF,
    damage_element: str | None = None,
    include_active: bool = True,
) -> ResolvedBuffs:
    """Evaluate a list of modifiers against active conditions.

    Args:
        modifiers: All modifiers from the build's sheets.
        conditions: User-toggled condition state.
        attack_scope: Which attack type is being evaluated (for scope filtering).
        target_filter: Only include modifiers targeting this entity.
        damage_element: The element of the damage instance being resolved
            (e.g. "ice"). Filters `element_scope`-restricted rows in
            :data:`ELEMENT_SCOPE_HONORED_STATS` — a row is skipped when it
            carries a scope and this element isn't in it. ``None`` (the
            default) means "no element context" — callers that only need the
            buff roster (team_calculator, /simulate's buff export) or that
            haven't been updated to thread an element (the DAG parity path)
            keep pre-C7 behaviour and see every scoped row unfiltered.
    """
    result = ResolvedBuffs()

    for mod in modifiers:
        # Target / condition / attack-scope / element-scope gates (C7 / D-KV16).
        if _gated_out(
            mod,
            conditions,
            attack_scope=attack_scope,
            target_filter=target_filter,
            damage_element=damage_element,
            include_active=include_active,
        ):
            continue

        # Calculate effective value (handle stacks)
        if mod.max_stacks > 1:
            stacks = conditions.get_stacks(mod.source_label, mod.max_stacks)
            value = mod.value * stacks
        else:
            value = mod.value

        # A modifier that still carries a `scaling_stat` here was never baked
        # (snapshot_builder only bakes base_atk / anomaly_mastery_excess —
        # e.g. Manato/Ben/Yidhari's HP-/DEF-scaled core passives are not).
        # It's a real, active buff that silently contributes 0 — surface it
        # (value forced to 0, is_modeled=False) instead of dropping it via
        # the value==0 skip below, so the buff roster can show it rather
        # than hide it (BRIEF_explainability.md: silence is how trust dies).
        is_modeled = mod.scaling_stat is None
        if not is_modeled:
            value = 0
        elif value == 0:
            continue

        contribution = Contribution(
            source=mod.source_label or mod.source.value,
            value=value,
            source_category=_SOURCE_TO_CATEGORY.get(mod.source),
            source_kind=mod.source.value,
            owner_agent_name=getattr(mod, "owner_name", None),
            condition=", ".join(c.value for c in mod.conditions),
            is_modeled=is_modeled,
            notes=mod.notes,
        )

        # Route to the right bucket
        if mod.stat in _STAT_TO_INPUT:
            result.stat_bonuses[mod.stat] = result.stat_bonuses.get(mod.stat, 0) + value
            result.stat_attributions.setdefault(mod.stat, []).append(contribution)
        elif mod.stat in _DMG_BONUS_STATS:
            result.dmg_bonuses.append(value)
            result.dmg_bonus_attributions.append(contribution)
        elif mod.stat in _COMBAT_STATS:
            result.combat_bonuses[mod.stat] = result.combat_bonuses.get(mod.stat, 0) + value
            result.combat_attributions.setdefault(mod.stat, []).append(contribution)
        else:
            # `mod.stat` isn't in any recognized bucket — the buff is real and
            # active but nothing consumes it. Surface it (is_modeled=False)
            # instead of silently dropping it, mirroring the scaling_stat
            # pattern above (F-27 / project_scaling_stat_gaps.md).
            result.stat_attributions.setdefault(mod.stat, []).append(
                replace(contribution, is_modeled=False)
            )

    return result


@dataclass
class ResolvedBuffs:
    """Result of buff resolution, separated into categories.

    For each bucket we keep both the legacy aggregate (sum / flat list) and
    a parallel ``*_attributions`` field that records per-modifier
    ``Contribution`` rows. The damage calculator only needs the aggregates;
    the API attribution layer reads the lists to surface "this hit's +30%
    DMG came from Core / +20% came from M1 / ..." in the UI.
    """

    stat_bonuses: dict[str, int] = field(default_factory=dict)
    dmg_bonuses: list[int] = field(default_factory=list)
    combat_bonuses: dict[str, int] = field(default_factory=dict)
    stat_attributions: dict[str, list[Contribution]] = field(default_factory=dict)
    dmg_bonus_attributions: list[Contribution] = field(default_factory=list)
    combat_attributions: dict[str, list[Contribution]] = field(default_factory=dict)

    def apply_to_stat_inputs(self, inputs: StatInputs) -> None:
        """Add resolved stat bonuses onto a StatInputs instance."""
        for stat, value in self.stat_bonuses.items():
            field_name = _STAT_TO_INPUT.get(stat)
            if field_name:
                current = getattr(inputs, field_name, 0)
                setattr(inputs, field_name, current + value)

    @property
    def total_dmg_bonus(self) -> int:
        """Sum of all damage bonuses (for the boost zone)."""
        return sum(self.dmg_bonuses)

    @property
    def res_reduction(self) -> int:
        """RES-shred bonus (bp), one additive term inside RESArea (CLAUDE.md damage chain)."""
        return self.combat_bonuses.get("res_reduction", 0)

    @property
    def res_ignore(self) -> int:
        """RES-ignore bonus (bp), added alongside `res_reduction` inside RESArea's clamp."""
        return self.combat_bonuses.get("res_ignore", 0)

    @property
    def luminize_res_ignore(self) -> int:
        """RES-ignore bp that only Luminize sees (Task 19, Remielle M1).

        Additive with :attr:`res_ignore` inside `calculate_luminize_damage`'s
        RESArea, never a replacement — a teammate's shred still applies to
        Luminize like any other damage. Zero for every other agent and for
        Remielle below M1, so no existing number moves.
        """
        return self.combat_bonuses.get("luminize_res_ignore", 0)

    @property
    def def_ignore(self) -> int:
        """DEF-ignore ratio (bp), the `(1-ignore_def)` term inside effective_def."""
        return self.combat_bonuses.get("def_ignore", 0)

    @property
    def vulnerability(self) -> int:
        """Vulnerability bonus (bp) feeding VulnerabilityArea = 1 + sum(vulnerability_debuffs)."""
        return self.combat_bonuses.get("vulnerability", 0)

    @property
    def anomaly_dmg_bonus(self) -> int:
        """Generic AnomalyBoostArea bonus (bp), applied to anomaly damage of any element."""
        return self.combat_bonuses.get("anomaly_dmg_bonus", 0)

    @property
    def anomaly_crit_rate(self) -> int:
        """Anomaly CRIT Rate (bp) — the kit-granted pool, NOT the disc `crit_rate` stat.

        Zero for every agent whose kit does not exempt its anomalies from the
        "anomaly damage does not crit" default, which is nearly all of them.
        `calculate_anomaly_damage` treats zero as "cannot crit" in every crit
        mode, so a zero here is a hard no rather than a 0%-chance roll.
        """
        return self.combat_bonuses.get("anomaly_crit_rate", 0)

    @property
    def anomaly_crit_dmg(self) -> int:
        """Anomaly CRIT DMG (bp) — pairs with :attr:`anomaly_crit_rate`.

        Only read when the rate is non-zero, so an orphaned CRIT DMG grant (a kit
        that adds DMG without a rate) contributes nothing rather than silently
        crediting damage that cannot occur.
        """
        return self.combat_bonuses.get("anomaly_crit_dmg", 0)

    @property
    def shock_dmg_bonus(self) -> int:
        """Shock-specific anomaly DMG bonus (bp). Add to anomaly_dmg_bonus for SHOCK only."""
        return self.combat_bonuses.get("shock_dmg_bonus", 0)

    @property
    def disorder_duration_bonus_rate(self) -> int:
        """Disorder bonus rate (bp/s of remaining aura). Multiply by remaining_s at trigger."""
        return self.combat_bonuses.get("disorder_duration_bonus_rate", 0)

    @property
    def mv_crit_scaling(self) -> int:
        """Factor (bp) for MV scaling from CRIT DMG. e.g. 2500 = 0.25."""
        return self.combat_bonuses.get("mv_crit_scaling", 0)

    @property
    def stun_dmg_mult_bonus(self) -> int:
        """Additive bonus to the stun multiplier (bp). Sums all active sources."""
        return self.combat_bonuses.get("stun_dmg_mult_bonus", 0)

    @property
    def stun_area_override(self) -> int:
        """Stun area override value (bp). Takes the max across active sources instead of sum."""
        return max(
            (c.value for c in self.combat_attributions.get("stun_area_override", [])),
            default=0,
        )

    @property
    def sheer_dmg_bonus(self) -> int:
        """Sheer DMG% bonus (bp). Separate multiplicative zone from dmg_bonus."""
        return self.combat_bonuses.get("sheer_dmg_bonus", 0)

    @property
    def sheer_force_flat(self) -> int:
        """Flat Sheer Force from W-engines, disc sets, and supports (bp raw value)."""
        return self.combat_bonuses.get("sheer_force_flat", 0)

    @property
    def abloom_dmg_bonus(self) -> int:
        """Abloom-specific DMG bonus in bp (e.g. Frostfall Sickle R1=4000=+40%)."""
        return self.combat_bonuses.get("abloom_dmg_bonus", 0)
