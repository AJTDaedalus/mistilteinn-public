"""Modifier and buff system for conditional stat effects.

Translates text-based kit descriptions (core skills, W-Engine passives,
disc set bonuses, mindscapes) into structured modifiers that the
BuffResolver can evaluate into flat StatInputs for damage calculation.

Design inspired by frzyc/genshin-optimizer's Pando engine tag system:
each modifier carries context tags (source, scope, condition) so the
same resolution logic works across all buff types.
"""

from __future__ import annotations

import dataclasses
import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.models.enums import PotentialTag

if TYPE_CHECKING:
    from collections.abc import Sequence


class ModifierSource(enum.StrEnum):
    """Where the modifier comes from."""

    CORE_SKILL = "core_skill"
    # An agent's "Additional Ability" text, which has no separate DB row (it
    # ships as part of the core_skills description). Distinct string from
    # CORE_SKILL so curated modifiers can cite which kit-text block they come
    # from without a DB row to point at.
    ADDITIONAL_ABILITY = "additional_ability"
    MINDSCAPE = "mindscape"
    WENGINE_PASSIVE = "wengine_passive"
    WENGINE_SECONDARY = "wengine_secondary"
    DISC_SET_2PC = "disc_set_2pc"
    DISC_SET_4PC = "disc_set_4pc"
    TEAM_BUFF = "team_buff"
    EXTERNAL = "external"  # Food buffs, Bangboo, manual overrides


class ModifierTarget(enum.StrEnum):
    """Who the modifier applies to."""

    SELF = "self"
    TEAM = "team"  # All squad members
    ACTIVE = "active"  # Only the on-field character
    SUMMON = "summon"  # Guard boars, etc.


class Condition(enum.StrEnum):
    """Toggleable conditions the user can activate in the UI.

    Each condition maps to a checkbox or state the user sets when
    configuring a build. The damage calculator doesn't know about
    game state — the user declares what's active.

    UNKNOWN is a sentinel for condition strings not in this enum.
    It is never added to ActiveConditions.active, so modifiers that
    reference it are always inactive (safe default for typos / new kits
    not yet modelled).
    """

    # Sentinel — never in active set; unknown JSON condition strings map here.
    UNKNOWN = "unknown"

    # Always active (no toggle needed)
    ALWAYS = "always"

    # Team composition conditions
    #
    # Two families, deliberately different derivation semantics (D-KV14):
    #   - Presence family (*_IN_TEAM below, specialty-keyed): team-global,
    #     include the owner. An agent's own specialty counts toward its
    #     team's presence check — e.g. a Stun-specialty agent gating a buff
    #     on STUN_IN_TEAM satisfies its own gate without a second Stun
    #     teammate. (Hugo's "1/2 Stun characters" core ATK buff is NOT this
    #     shape — it's self-targeted (ownBuff in ZO), not a team buff, and
    #     Hugo is Attack specialty, so he never satisfies his own gate; see
    #     Task 17 Batch 6 Gate-2 audit, docs/LOG_kit_curation.md.)
    #   - SAME_*/union family: owner-relative, exclude the owner. ZO's
    #     in-game "additional ability" gates read "another squad member
    #     shares X" — derived per member against the *other* two, not a
    #     team-global set applied uniformly (see team_calculator.py
    #     ``_derive_owner_relative_conditions``).
    SAME_ELEMENT_IN_TEAM = "same_element_in_team"
    SAME_FACTION_IN_TEAM = "same_faction_in_team"
    SAME_ATTRIBUTE_OR_STUN_IN_TEAM = "same_attribute_or_stun_in_team"
    SAME_SPECIALTY_OR_FACTION_IN_TEAM = "same_specialty_or_faction_in_team"
    SAME_ATTRIBUTE_OR_FACTION_IN_TEAM = "same_attribute_or_faction_in_team"
    # D-KV23 (Task 17 Batch 6): three-way union, added for Ellen's Additional
    # Ability (ZO gate sum(stun, ice, VictoriaHousekeepingCo) >= 3 reduces to
    # this exact union once Ellen's own element+faction membership is
    # subtracted out).
    SAME_ATTRIBUTE_OR_FACTION_OR_STUN_IN_TEAM = "same_attribute_or_faction_or_stun_in_team"
    STUN_IN_TEAM = "stun_in_team"
    ANOMALY_IN_TEAM = "anomaly_in_team"
    # Remielle's tiered ATK buff (DESIGN_remielle.md §6.1, Task 17): presence
    # family (team-global, include-owner, same as ANOMALY_IN_TEAM above) but
    # counting rather than merely detecting presence. A deliberate, narrow
    # schema extension, not a reopening of the generic TEAM_COUNT engine
    # D-KV14 rejected — see docs/DECISIONS.md's Task 24 entry for why two
    # named members clear D-KV23's bar where a predicate engine did not.
    ANOMALY_COUNT_2_IN_TEAM = "anomaly_count_2_in_team"
    ANOMALY_COUNT_3_IN_TEAM = "anomaly_count_3_in_team"
    SUPPORT_IN_TEAM = "support_in_team"
    RUPTURE_IN_TEAM = "rupture_in_team"
    ATTACK_IN_TEAM = "attack_in_team"
    DEFENSE_IN_TEAM = "defense_in_team"
    SQUAD_USED_EX_SPECIAL = "squad_used_ex_special"
    SQUAD_TRIGGERED_FREEZE_OR_SHATTER = "squad_triggered_freeze_or_shatter"
    TEAMMATE_USED_EX_SPECIAL = "teammate_used_ex_special"

    # Equipper class/element — auto-injected from agent.specialty / agent.element
    EQUIPPER_IS_ATTACK = "equipper_is_attack"
    EQUIPPER_IS_STUN = "equipper_is_stun"
    EQUIPPER_IS_ANOMALY = "equipper_is_anomaly"
    EQUIPPER_IS_SUPPORT = "equipper_is_support"
    EQUIPPER_IS_DEFENSE = "equipper_is_defense"
    EQUIPPER_IS_RUPTURE = "equipper_is_rupture"
    EQUIPPER_IS_PHYSICAL = "equipper_is_physical"
    EQUIPPER_IS_FIRE = "equipper_is_fire"
    EQUIPPER_IS_ICE = "equipper_is_ice"
    EQUIPPER_IS_ELECTRIC = "equipper_is_electric"
    EQUIPPER_IS_ETHER = "equipper_is_ether"
    # Wind joined the element roster with Velina (Element.WIND, hakushin 205→wind);
    # the condition family predates her and never grew the member, which forced
    # Joyau Dore's wind-equipper gates into approximations. Auto-wired by the same
    # `equipper_is_<element>` derivation as the five above.
    EQUIPPER_IS_WIND = "equipper_is_wind"
    EQUIPPER_IS_LUMIFLUX = "equipper_is_lumiflux"  # Remielle (DESIGN_remielle.md §6.1)
    # Agent-identity gate, injected from the equipper's slugified name. First user:
    # Sol Exuvia (14155), whose Eclipse passive reads "When the equipper is Pyrois".
    # Unlike EQUIPPER_IS_LUMIFLUX (which rides the element string), this family is
    # derived from `agents.name`, so each identity-locked engine needs its member here.
    EQUIPPER_IS_PYROIS = "equipper_is_pyrois"

    # Combat state conditions (user-toggled)
    ENEMY_STUNNED = "enemy_stunned"
    ENEMY_FROZEN = "enemy_frozen"
    ENEMY_BLOCKED = "enemy_blocked"
    ENEMY_BURNING = "enemy_burning"
    # Jane applies Gnawed on hit (10s). Gates her core passive's Assault-CRIT
    # grant and M2's DEF-ignore. Added for #162: those rows are a TEAM-wide
    # anomaly-CRIT buff, so the corpus's usual "approximate an unmodelled status
    # gate as `always`" tolerance (M2's own def_ignore row) would over-credit
    # every teammate's Physical anomaly damage whenever Gnawed is down --
    # far past D-KV17's 2% approximation ceiling.
    ENEMY_GNAWED = "enemy_gnawed"
    ENEMY_SHOCKED = "enemy_shocked"
    ENEMY_HAS_ASSAULT = "enemy_has_assault"
    ENEMY_HAS_ANOMALY = "enemy_has_anomaly"
    # Prismatic (Remielle core passive, DESIGN §6/Task 18): true while the
    # enemy holds >=1 Lumiflux Buildup Point, plus an 8s post-removal linger
    # (DESIGN §7.1's "+8s linger"). Sim-only -- gated on P2's per-enemy pool
    # state (`LumifluxEnemyState`), never user-toggled.
    LUMIFLUX_BUILDUP_ACTIVE = "lumiflux_buildup_active"
    HP_ABOVE_50 = "hp_above_50"
    HP_BELOW_50 = "hp_below_50"
    ATTACKING_FROM_BEHIND = "attacking_from_behind"
    SHIELD_ACTIVE = "shield_active"
    CRIT_RATE_ABOVE_THRESHOLD = "crit_rate_above_threshold"
    CRIT_RATE_GTE_50 = "crit_rate_gte_50"
    POWER_MAX = "power_max"

    # Ether Veil mechanic (White Water Ballad disc set)
    IN_ETHER_VEIL = "in_ether_veil"
    ACTIVATED_ETHER_VEIL = "activated_ether_veil"
    ETHER_VEIL_ACTIVE = "ether_veil_active"

    # Post-action triggers (user-toggled)
    AFTER_EX_OR_ULTIMATE = "after_ex_or_ultimate"
    AFTER_EX_OR_CHAIN = "after_ex_or_chain"
    AFTER_EX_OR_ASSIST = "after_ex_or_assist"
    AFTER_EX_OR_BASIC_HIT = "after_ex_or_basic_hit"
    AFTER_EX_HIT = "after_ex_hit"
    AFTER_EX_CHAIN_OR_ULTIMATE = "after_ex_chain_or_ultimate"
    AFTER_CHAIN_OR_ULTIMATE = "after_chain_or_ultimate"
    AFTER_ULTIMATE = "after_ultimate"
    AFTER_SPECIAL_ACTIVATION = "after_special_activation"
    AFTER_BASIC_HIT = "after_basic_hit"
    AFTER_FREEZE_TRIGGER = "after_freeze_trigger"
    AFTER_ABLOOM_TRIGGER = "after_abloom_trigger"
    AFTER_DEFENSIVE_OR_EVASIVE_ASSIST = "after_defensive_or_evasive_assist"
    ON_CRIT_BASIC_DODGE_EX = "on_crit_basic_dodge_ex"
    ON_SPECIAL_OR_EX = "on_special_or_ex"
    ON_FIRE_CHAIN_OR_ULTIMATE = "on_fire_chain_or_ultimate"
    ON_SWAP_IN = "on_swap_in"
    OFF_FIELD_OR_5S_AFTER_SWAP = "off_field_or_5s_after_swap"
    CHAIN_ULT_USED = "chain_ult_used"
    DODGE_COUNTER_USED = "dodge_counter_used"
    ULTIMATE_USED = "ultimate_used"
    QUICK_ASSIST_ENTRY = "quick_assist_entry"
    ANOMALY_OR_DISORDER_DMG = "anomaly_or_disorder_dmg"
    ASSAULT_TRIGGERED = "assault_triggered"
    CORRUPTION_TRIGGERED = "corruption_triggered"
    # Remielle sim-state conditions (DESIGN_remielle.md §6, Task 17). Both
    # are sim-only -- set from anomaly_simulator state (Task 15's Phase Flow
    # window / Task 11's Refringe hook), never user-toggled directly.
    PHASE_FLOW_ACTIVE = "phase_flow_active"
    REFRINGE_TRIGGERED = "refringe_triggered"  # attributed to the Lumiflux agent, not the trigger
    SPECIAL_OR_EX_VS_ANOMALY_ENEMY = "special_or_ex_vs_anomaly_enemy"
    SAME_ATTRIBUTE_AFTERSHOCK_OR_DASH_HIT = "same_attribute_aftershock_or_dash_hit"

    # Agent-specific mechanic activations
    FIRE_SUPPRESSION_ACTIVE = "fire_suppression_active"  # Soldier 11
    FLASH_FREEZE_CONSUMED = "flash_freeze_consumed"  # Ellen
    QUICK_CHARGE_ACTIVE = "quick_charge_active"  # Ellen
    CHARGED_SCISSORS_HIT = "charged_scissors_hit"  # Ellen
    BASIC_ATTACK_HIT = "basic_attack_hit"
    DASH_ATTACK_HIT = "dash_attack_hit"
    EX_SPECIAL_USED = "ex_special_used"
    CHAIN_ATTACK_USED = "chain_attack_used"
    MALICIOUS_COMPLAINT_ACTIVE = "malicious_complaint_active"  # Dialyn
    AFTERSHOCK_ACTIVE = "aftershock_active"
    BESIEGE_ACTIVE = "besiege_active"
    BLAZING_HEART_ACTIVE = "blazing_heart_active"
    BURST_MODE_ACTIVE = "burst_mode_active"
    CHEER_ON_ACTIVE = "cheer_on_active"
    CLARITY_CONSUMED = "clarity_consumed"
    COLLAPSE_ACTIVE = "collapse_active"
    CORE_SKILL_ACTIVE = "core_skill_active"
    DARK_ABYSS_ACTIVE = "dark_abyss_active"
    ELATION_ACTIVE = "elation_active"
    FLY_THE_FLAG_ACTIVE = "fly_the_flag_active"
    FROSTED_BANNER_ACTIVE = "frosted_banner_active"
    HARMONY_ACTIVE = "harmony_active"
    MEDITATION_ACTIVE = "meditation_active"
    MORALE_BOOST_ACTIVE = "morale_boost_active"
    MORALE_BURST_ACTIVE = "morale_burst_active"
    PASSION_STATE_ACTIVE = "passion_state_active"
    PRESUMPTION_OF_GUILT_ACTIVE = "presumption_of_guilt_active"
    ROARING_RIDE_AP_ROLL = "roaring_ride_ap_roll"
    ROARING_RIDE_ATK_ROLL = "roaring_ride_atk_roll"
    STARLIGHT_STACKS = "starlight_stacks"
    YUNKUI_3_STACKS = "yunkui_3_stacks"
    SUPPRESSIVE_MODE_ACTIVE = "suppressive_mode_active"
    THUNDER_ACTIVE = "thunder_active"
    THUNDER_CONSUMED = "thunder_consumed"
    TOTALIZE_ACTIVE = "totalize_active"
    TRANCE_ACTIVE = "trance_active"
    TRANCE_ENDED = "trance_ended"
    TURBO_BOOST_ACTIVE = "turbo_boost_active"
    VENOM_ACTIVE = "venom_active"
    VEIL_ACTIVE = "veil_active"  # Ye Shunguang — Veil Vulnerability stacks
    ANOMALY_MASTERY_GTE_115 = "anomaly_mastery_gte_115"
    ANOMALY_MASTERY_GTE_150 = "anomaly_mastery_gte_150"
    ANOMALY_PROFICIENCY_GTE_375 = "anomaly_proficiency_gte_375"
    GESSOU_ACTIVE = "gessou_active"  # Yanagi — Gessou stance buildup window
    WINDBITE_CONSUMED = "windbite_consumed"  # Velina — Sweeping Vortex (3rd), arms Core +150%
    ZEROED_IN_ACTIVE = "zeroed_in_active"  # Orphie & Magus — EX Special: Heat Charge laser hit

    # Generic stackable conditions
    STACKS_1 = "stacks_1"
    STACKS_2 = "stacks_2"
    STACKS_3 = "stacks_3"
    STACKS_4 = "stacks_4"
    STACKS_5 = "stacks_5"
    STACKS_6 = "stacks_6"
    STACKS_7 = "stacks_7"
    STACKS_8 = "stacks_8"
    STACKS_9 = "stacks_9"
    STACKS_10 = "stacks_10"


class AttackScope(enum.StrEnum):
    """Which attack types a modifier applies to."""

    ALL = "all"
    BASIC = "basic"
    DASH = "dash"
    DODGE_COUNTER = "dodge_counter"
    SPECIAL = "special"
    EX_SPECIAL = "ex_special"
    CHAIN = "chain"
    ULTIMATE = "ultimate"
    ASSIST_FOLLOWUP = "assist_followup"
    # Aftershock is its own damage category, not a move category. Before this existed
    # both aftershock emission paths resolved with ALL, and the scope gate only filters
    # when the *query* scope is not ALL — so scope filtering was off entirely and every
    # narrow-scoped row leaked onto aftershocks (issue #154). ALL was the permissive
    # fallback where a conservative one was needed.
    AFTERSHOCK = "aftershock"


@dataclass(frozen=True)
class Modifier:
    """A single stat modification with context.

    This is the atomic unit of the buff system. Complex effects are
    represented as multiple Modifiers.

    Example — Ellen's core skill at level F (max):
        Modifier(
            stat="crit_dmg",
            value=6660,  # 66.6% in basis points
            source=ModifierSource.CORE_SKILL,
            source_label="Core Passive: Sharp-Toothed",
            target=ModifierTarget.SELF,
            conditions=[Condition.FLASH_FREEZE_CONSUMED],
            scopes=[AttackScope.DASH, AttackScope.CHAIN, AttackScope.ULTIMATE],
        )

    Example — Deep Sea Visitor R1 (unconditional part):
        Modifier(
            stat="ice_dmg",
            value=2500,  # 25%
            source=ModifierSource.WENGINE_PASSIVE,
            source_label="Deep Sea Visitor R1",
            target=ModifierTarget.SELF,
            conditions=[Condition.ALWAYS],
        )
    """

    # What stat to modify (matches StatType values + damage calc fields)
    stat: str

    # Value in basis points (positive = buff, negative = debuff)
    value: int

    # Context tags
    source: ModifierSource
    source_label: str = ""
    target: ModifierTarget = ModifierTarget.SELF

    # When is this modifier active? ALL conditions must be met (AND logic).
    # Use separate Modifiers for OR conditions.
    conditions: tuple[Condition, ...] = (Condition.ALWAYS,)

    # Which attack types does this apply to? Empty = all attacks.
    scopes: tuple[AttackScope, ...] = (AttackScope.ALL,)

    # For stackable effects: value is per-stack, max_stacks caps total.
    max_stacks: int = 1

    # Mindscape range this row is active for (C2). A mindscape that *upgrades* an
    # existing buff rather than adding a new one is authored as two rows — one
    # `max_mindscape: 1`, one `min_mindscape: 2` — each carrying its own literal,
    # independently citable value, with exactly one ever active. See D-KV2 and
    # `mindscape_allows` below.
    min_mindscape: int = 0
    max_mindscape: int | None = None

    # Which Potential state this row's mechanic belongs to (#90). Mirrors
    # `Attack.potential` deliberately — same three states, same names:
    #   None       -> present in both states (the overwhelming majority)
    #   "base"     -> base kit only; SUPERSEDED once Potential is unlocked
    #   "unlocked" -> exists only once Potential is unlocked
    #
    # Three states rather than a boolean, and not for symmetry's sake: curation found
    # rows whose mechanic exists in BOTH states but with a narrower scope or condition
    # in the base kit (Ellen's Rising Storm team gate, Harumasa's Day Break scope,
    # Nekomata's Catwalk scope). Those are authored as a "base"/"unlocked" PAIR, and a
    # boolean cannot make the pair mutually exclusive — both halves would fire for an
    # unlocked build whose squad satisfies both gates, double-counting the buff. This is
    # the same shape as the mindscape-upgrade pair (min_mindscape/max_mindscape, D-KV2),
    # where exactly one variant is ever live.
    #
    # Absent means "not stated", which is indistinguishable from "not considered": every
    # kit in this corpus was authored between #85 and #90, against Potential-unlocked
    # text. validate_kits' L0 `potential_unstated` rule therefore makes the key mandatory
    # on the agents that HAVE Potential, so silence cannot survive where it matters.
    potential: PotentialTag | None = None

    # Bind this row's VALUE to one of the agent's Potential ramps (#90 Track 2), instead
    # of it being a literal. `potential_param` is an index into
    # `Agent.potential_params`; the live value is `ramp[potential_rank - 1] * scale`.
    #
    # `scale` exists because the ramps store what the source text says — a percentage as
    # a decimal (0.016) and anything else literally (a 10-stack cap, a 576 flat ATK) —
    # while modifier `value`s are basis points for percentage stats and literal for flat
    # ones. Inferring which from the stat name would be a silent 100x when the guess is
    # wrong, so it is stated: 10000 for a percentage stat, 1 for a flat one.
    #
    # A bound row resolves to 0 at rank 0, because the ramp is not indexed at all there.
    # Such rows should also carry `potential="unlocked"` when the mechanic itself is
    # Potential-only; the two are independent, and validate_kits checks the pairing.
    potential_param: int | None = None
    potential_param_scale: int = 10_000

    # For effects that scale with a stat (rare, e.g. "ATK increases by 20% of DEF")
    scaling_stat: str | None = None
    scaling_ratio: float = 0.0  # base_atk: bp÷10000; anomaly_mastery_excess: direct multiplier
    excess_threshold: int = 0  # anomaly_mastery_excess: AM floor; excess = max(0, am − threshold)

    # For HP-scaled team buffs (e.g. support DMG% increases with their own HP).
    # When hp_scale_per_unit > 0, `value` is treated as the cap and the actual
    # value is baked at snapshot build time from the support's computed HP:
    #   baked = clamp(hp_scale_base, value,
    #                 hp_scale_base  # noqa: ERA001
    #                 + floor(max(0, HP - hp_scale_threshold) / hp_scale_per_unit)  # noqa: ERA001
    #                                 * hp_scale_unit)
    hp_scale_base: int = 0  # minimum value in bp
    hp_scale_threshold: int = 0  # HP at which scaling begins (below → use base)
    hp_scale_per_unit: int = 0  # HP per additional hp_scale_unit of value
    hp_scale_unit: int = 0  # bp gained per hp_scale_per_unit HP above threshold

    # For ATK-scaled team buffs (e.g. "SheerForce +X% of support's ATK").
    # When atk_scale_ratio > 0, `value` is the cap; baked =
    #   min(value, floor(ATK * ratio / 10000) + flat_addend).
    atk_scale_ratio: int = 0  # ratio in basis points (1500 = 15% of ATK)
    # Flat term added alongside atk_scale_ratio's percent-of-ATK term, still under
    # the shared `value` cap (Lucy's "Cheer On!": min(cap, 25%*ATK + flat)). Only
    # meaningful paired with atk_scale_ratio — L0 rejects it alone, since on its own
    # it would be a second, cap-bypassing way to author a flat buff.
    flat_addend: int = 0

    # Restrict this modifier to specific damage elements (C7 / D-KV16). None
    # (default) = all elements. A list expresses e.g. "non-Ice" as the other
    # four Element values. Honored ONLY by the res_reduction / res_ignore
    # consumers in buff_resolver — validate_kits L0 hard-fails element_scope
    # on any other stat so a silently-ignored scope can't ship (the same
    # loud-failure discipline as the scaling_stat dispatch check).
    element_scope: tuple[str, ...] | None = None

    # Attribution: which agent produced this modifier (set by snapshot_builder).
    # None for modifiers loaded before owner tracking was added.
    owner_name: str | None = None

    # Provenance: curator citation/rationale for this specific modifier, read
    # from the modifier JSON's `notes` key (DESIGN_explainability.md §2.4).
    # None when the curator hasn't recorded one — the UI simply omits the
    # tooltip rather than treating absence as an error.
    notes: str | None = None


_MINDSCAPE_LABEL_PREFIX = "M"


def mindscape_allows(mod: Modifier, mc_level: int) -> bool:
    """Is *mod* active for an agent at mindscape level *mc_level*?

    Two gates; a row must clear both.

    **Label gate** — a `MINDSCAPE`-source row labelled ``M<n>: …`` needs
    ``mc_level >= n``. This is how every mindscape buff has always been gated, and
    the label remains the only place that level is written.

    **Range gate (C2)** — ``min_mindscape`` / ``max_mindscape``. This exists for the
    mindscapes that *upgrade* an existing buff instead of adding a new one: Astra's M2
    raises her core team-ATK cap 1200 → 1600 and its ratio ×1.19; Caesar's M2 raises his
    to 150% of its original value. Modelled as an independent additive row, such an
    upgrade stacks with the buff it was meant to replace and its "value" (Caesar's +500)
    cites nothing — it is 1500 minus 1000, reverse-engineered. Modelled as two gated
    rows, each variant is a plain literal that L1/L2 can check against a source.

    Callers must apply this wherever they filter by mindscape, so the buff-toggle list
    and the snapshot agree on which variant is live.
    """
    label = mod.source_label
    if (
        mod.source == ModifierSource.MINDSCAPE
        and label.startswith(_MINDSCAPE_LABEL_PREFIX)
        and label[1:2].isdigit()
        and int(label[1]) > mc_level
    ):
        return False
    if mc_level < mod.min_mindscape:
        return False
    return not (mod.max_mindscape is not None and mc_level > mod.max_mindscape)


def potential_allows(mod: Modifier, potential_rank: int) -> bool:
    """Is *mod* active for a build at Potential rank *potential_rank*? (#90)

    Variant selection is binary — every Potential-marked entry in the roster carries the
    full 6-node list, so no mechanic is gated on a subset of nodes — hence the predicate
    is ``>= 1`` rather than a per-rank comparison. The *rank* additionally indexes the
    per-rank value ramps, which is Track 2 and does not change this gate.

    A ``base``/``unlocked`` pair authored for one mechanic is mutually exclusive here:
    exactly one of the two is ever live, which is what lets a row whose scope or
    condition *widens* on unlock be modelled without double-counting.

    Deliberately mirrors `mindscape_allows`: the same "callers must apply this wherever
    they filter" contract, so the buff-toggle list and the snapshot agree on which rows
    are live. A row visible in the toggle list but absent from the snapshot (or the
    reverse) is the bug that shape prevents.
    """
    if mod.potential is None:
        return True
    unlocked = potential_rank >= 1
    return unlocked if mod.potential == PotentialTag.UNLOCKED else not unlocked


def bind_potential_param(
    mod: Modifier,
    potential_rank: int,
    potential_params: list | None,
) -> Modifier:
    """Resolve a ramp-bound modifier's value for this build's Potential level (#90).

    Returns *mod* unchanged when it binds no ramp. Otherwise its ``value`` becomes
    ``ramp[potential_rank - 1] * potential_param_scale``, rounded — the ramps hold what
    the source text says (a decimal for a percentage, a literal for a count or flat stat)
    and ``scale`` converts that to the modifier's own unit.

    Resolves to **0** rather than raising when the ramp is unavailable — rank 0 (the ramp
    is not indexed at all when Potential is not unlocked), an agent with no ramps, or an
    index past the end. Zero is inert, so the failure direction is a missing buff rather
    than a wrong one; `validate_kits` catches a bad index at author time, which is where a
    typo should be caught rather than at calc time.
    """
    if mod.potential_param is None:
        return mod
    ramp = None
    if potential_params and 0 <= mod.potential_param < len(potential_params):
        ramp = potential_params[mod.potential_param]
    index = potential_rank - 1
    if ramp is None or not (0 <= index < len(ramp)):
        return dataclasses.replace(mod, value=0)
    return dataclasses.replace(mod, value=round(ramp[index] * mod.potential_param_scale))


# `ModifierSheet` lived here until 2026-07-28. It was the whole-kit object from the original
# design (b4c9bc3): kits stored as JSONB on a DB model, with per-sheet `version`/`notes`/
# `confidence` read at load time. That design lost to the file-based one — kits are JSON on
# disk under `app/data/modifiers/`, and `modifier_loader` reads them straight into flat
# `Modifier` lists. The class was never instantiated in any commit in this repo's history.
#
# Its `confidence` field is now the kit JSON's own key, enforced by `validate_kits.py`'s LC
# layer (Task 18), not by any runtime type. The name survives in `app/data/modifiers/
# README.md` and in `docs/DESIGN_move_detail_redesign.md` / `DECISIONS.md`, which record
# *why* it was not used for buff attribution — keep those; they are history, not references.


@dataclass
class ActiveConditions:
    """User-toggled condition state for a specific damage calculation.

    The UI presents checkboxes based on which Conditions appear in the
    build's modifier sheets. The user toggles them on/off.
    """

    active: set[Condition] = field(default_factory=lambda: {Condition.ALWAYS})
    stack_counts: dict[str, int] = field(default_factory=dict)
    # key = modifier source_label, value = active stack count (unset = max_stacks)

    def is_met(self, conditions: tuple[Condition, ...]) -> bool:
        """Check if all conditions in the tuple are active."""
        return all(c in self.active for c in conditions)

    def get_stacks(self, source_label: str, max_stacks: int) -> int:
        """Get active stack count for a stackable modifier, capped at max.

        An enabled stackable modifier with no explicit count is assumed
        **fully stacked**. In-game these stacks build from ordinary rotation
        actions (attack hits, field time) and sit at cap for the damage
        window being optimized, so max is the steady state; 0 is a state no
        player is in while the buff is up. Users override per-buff to model
        partial uptime.

        TODO: this is an approximation. The stateful engine should eventually
        derive stack counts from the combo itself — detect each modifier's
        trigger instances (hits landed, EX Specials used, field swaps) and
        follow the stack timeline (gain / decay / expiry) per step, instead of
        assuming a flat steady-state count. Blocked on the trigger-event model
        (see docs/TASKS_kit_validation.md, Task 20).
        """
        return min(self.stack_counts.get(source_label, max_stacks), max_stacks)


# ---------------------------------------------------------------------------
# Custom / stage buffs (issue #64, TASKS_buff_context.md B3)
# ---------------------------------------------------------------------------

#: Prefix every synthesized custom buff's ``source_label`` carries. It is what makes a
#: custom buff addressable by ``disabled_buffs`` and distinguishable in attribution
#: without adding a `ModifierSource` member — `EXTERNAL` is already documented as exactly
#: this concept ("Food buffs, Bangboo, manual overrides"), and a new member would need
#: handling in every match over the enum (DESIGN_buff_context.md §2.3).
CUSTOM_BUFF_PREFIX = "custom:"


def slugify(label: str) -> str:
    """Lowercase + non-alphanumeric → underscore, collapsed and trimmed.

    Lives here rather than in `snapshot_builder` because two callers now need the same
    rule: `buff_id`, which addresses kit modifiers, and `custom_buff_label`, which
    addresses custom ones. A second copy would be a slug that agrees today and drifts
    later, and the whole point of the slug is that it is stable.
    """
    out: list[str] = []
    last_us = True
    for ch in label.lower():
        if ch.isalnum():
            out.append(ch)
            last_us = False
        elif not last_us:
            out.append("_")
            last_us = True
    return "".join(out).strip("_")


def custom_buff_label(label: str) -> str:
    """The `source_label` a custom buff is known by: ``custom:<slug of its label>``.

    Derived from the label rather than assigned, because `disabled_buffs` holds these
    strings **between requests**: a random id would mean a user who toggles a stage buff
    off gets it back on the next calculation, which is the one thing a toggle may not do.
    """
    return f"{CUSTOM_BUFF_PREFIX}{slugify(label)}"


class UnslugifiableCustomBuffError(ValueError):
    """A custom buff's label contains nothing a slug can be built from.

    `min_length=1` on the schema field is not the same guarantee: ``"!!!"`` and ``"🔥"``
    are one character or more and slugify to the empty string, giving every such buff the
    same `source_label` ``"custom:"``. That is the duplicate problem in disguise — an id
    that does not name the buff it belongs to — so it is rejected for the same reason and
    at the same two layers.
    """


class DuplicateCustomBuffError(ValueError):
    """Two custom buffs in one context slugify to the same `source_label`.

    Rejected rather than disambiguated with a suffix. A suffix would make the id depend
    on list order, so reordering the list — which no user thinks of as a semantic change
    — would silently move which buff a `disabled_buffs` entry refers to. That trades a
    visible error for an invisible one, and stability is the property `custom_buff_label`
    exists to provide (TASKS_buff_context.md B3 asks for this decision to be made rather
    than left to chance).
    """


def assert_addressable_custom_buffs(buffs: Sequence[Any]) -> None:
    """Raise unless every custom buff has an id, and its own.

    The one implementation of the rule, called from three layers: the synthesiser below
    (service invariant, surfaces as a 500), the request schemas' ``CustomBuffCarrier``
    and the buff-preset schemas (both surface as a 422 naming the offending labels,
    which is what the user can act on). Three copies of a rule is a rule that agrees
    today and drifts later — the same argument that put `slugify` in one place.

    Raises:
        UnslugifiableCustomBuffError: a label with nothing to slug.
        DuplicateCustomBuffError: two labels sharing one slug.
    """
    seen: dict[str, str] = {}
    for buff in buffs:
        label = custom_buff_label(buff.label)
        if label == CUSTOM_BUFF_PREFIX:
            raise UnslugifiableCustomBuffError(
                f"custom buff {buff.label!r} slugifies to nothing, so it would be "
                f"addressable only as {CUSTOM_BUFF_PREFIX!r}; give it a name containing "
                "at least one letter or digit"
            )
        if label in seen:
            raise DuplicateCustomBuffError(
                f"custom buffs {seen[label]!r} and {buff.label!r} both resolve to "
                f"{label!r}; give them distinguishable names"
            )
        seen[label] = buff.label


def synthesize_custom_buffs(buffs: Sequence[Any]) -> list[Modifier]:
    """Turn user-authored stage buffs into ordinary `Modifier` rows.

    Duck-typed on purpose: the input is `schemas.damage.CustomBuff`, and importing it
    here would be circular — that schema already imports this module for its `Condition`
    and `AttackScope` vocabularies. What this needs is the shape, not the class.

    The output is deliberately unremarkable. Condition gating, scope filtering, stacking,
    attribution, explainability and `disabled_buffs` all then work on custom buffs with
    no additional code anywhere, because they are not a special case — which is the whole
    of DESIGN_buff_context.md §2.3.
    """
    assert_addressable_custom_buffs(buffs)
    modifiers: list[Modifier] = []
    for buff in buffs:
        label = custom_buff_label(buff.label)
        modifiers.append(
            Modifier(
                stat=buff.stat,
                value=buff.value,
                source=ModifierSource.EXTERNAL,
                source_label=label,
                target=ModifierTarget.TEAM if buff.target == "team" else ModifierTarget.SELF,
                conditions=tuple(Condition(c) for c in buff.conditions),
                scopes=tuple(AttackScope(s) for s in buff.scopes),
                max_stacks=buff.max_stacks,
            )
        )
    return modifiers
