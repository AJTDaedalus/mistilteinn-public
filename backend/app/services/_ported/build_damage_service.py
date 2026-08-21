"""Build damage orchestration — stateless functions on value objects.

Takes BuildSnapshot + EnemySnapshot → DamageResult / AnomalyResult.
No DB access, no file I/O — pure computation.

Design note (B-awareness):
    This service is deliberately stateless and operates on snapshots.
    A future rotation engine would call these same functions per-tick,
    varying the ActiveConditions and attack_scope at each timestep.
    The snapshot pattern means the rotation engine just needs to produce
    the right BuildSnapshot at each point in the timeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from typing import TYPE_CHECKING

from app.models.enums import ANOMALY_TO_ELEMENT
from app.models.enums import AnomalyType as ModelAnomalyType
from app.services.attribution import StepAttribution, build_step_attribution
from app.services.buff_resolver import ResolvedBuffs, resolve_modifiers
from app.services.damage_calculator import (
    ANOMALY_BASE,
    AnomalyResult,
    AnomalyType,
    CritMode,
    DamageResult,
    SheerDamageResult,
    calculate_anomaly_damage,
    calculate_sheer_damage,
    calculate_standard_damage,
)
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Modifier,
    ModifierTarget,
)
from app.services.stat_calculator import (
    DiscStats,
    StatInputs,
    TotalStats,
    accumulate_disc_stats,
    compute_total_stats,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.services.kit_formulas import KitFormula

_ANOMALY_TYPES = {t.value: t for t in AnomalyType}

# Universal ATK→SheerForce conversion ratio (basis points). Applies to all Rupture agents.
# Source: ZZZ Stats and Damage Calculation Reference — Sheer Force section.
SHEER_ATK_RATIO = 3000  # 30%

# Per-agent intrinsic HP→SheerForce ratios (basis points).
# Promoted to a DB column when ≥3 Rupture agents ship (see DECISIONS.md).
#
# All three read "every 1 point of Max HP increases Sheer Force by 0.1" in their
# core text, and all three are `core.sheerForce = 0.1` in ZO, applied as
# `ownBuff.initial.sheerForce.add(prod(own.final.hp, core.sheerForce))`. This is not
# an ATK buff: Manato and Yidhari carried it as an HP-scaled `flat_atk` kit modifier,
# which the snapshot builder never baked — so it did nothing at all, and would have
# been wrong by a factor of 0.3 (the ATK→SheerForce ratio) if it had. See D-KV9.
_SHEER_INTRINSIC_HP_RATIOS: dict[str, int] = {
    "Yixuan": 1000,  # +HP×10% (confirmed: ZO Yixuan.ts + references/ZZZ Stats)
    "Manato": 1000,  # +HP×10% (ZO Manato.ts core.sheerForce = 0.1 + DB core text)
    "Yidhari": 1000,  # +HP×10% (ZO Yidhari.ts core.sheerForce = 0.1 + DB core text)
}


def resolve_sheer_force(
    stats: TotalStats,
    snap: BuildSnapshot,
    buffs: ResolvedBuffs,
) -> int:
    """Compute the resolved SheerForce value for a Rupture agent.

    SheerForce = floor(ATK * 30%) + floor(HP * agent_hp_ratio) + flat_sources

    The 30% ATK conversion is universal (all Rupture agents). The HP ratio is
    per-agent (Yixuan: 10%). External flat contributions come from supports
    (Lucia, Pan Yinhu) and W-engine/disc-set buffs via the modifier resolver.
    """
    sf = floor(stats.atk * SHEER_ATK_RATIO / 10000)
    sf += floor(stats.hp * snap.agent_sheer_force_hp_ratio / 10000)
    sf += buffs.sheer_force_flat
    return sf


@dataclass(frozen=True)
class BuildSheerDamageResult:
    """Sheer Damage result bundled with the resolved stats that produced it."""

    damage: SheerDamageResult
    stats: TotalStats
    attribution: StepAttribution | None = None


@dataclass(frozen=True)
class BuildDamageResult:
    """Damage result bundled with the resolved stats that produced it."""

    damage: DamageResult
    stats: TotalStats
    attribution: StepAttribution | None = None


@dataclass(frozen=True)
class BuildAnomalyDamageResult:
    """Anomaly result bundled with resolved stats."""

    damage: AnomalyResult
    stats: TotalStats
    attribution: StepAttribution | None = None


@dataclass(frozen=True)
class BuildSnapshot:
    """All numbers needed for one agent's damage calc.

    Produced by the API layer (from DB models) or by a future rotation
    engine (from timeline state). The service doesn't care which.
    """

    # Agent base stats
    agent_base_hp: int = 0
    agent_base_atk: int = 0
    agent_base_def: int = 0
    agent_crit_rate: int = 500  # basis points
    agent_crit_dmg: int = 5000
    agent_anomaly_proficiency: int = 0
    agent_anomaly_mastery: int = 100
    agent_base_impact: int = 0  # Impact is a base stat (83-120); the % bonuses scale it
    agent_pen_ratio: int = 0
    agent_pen_flat: int = 0

    # W-Engine
    wengine_base_atk: int = 0

    # Agent metadata
    agent_name: str = ""
    agent_element: str = "physical"
    agent_specialty: str = ""
    # Faction is carried purely so the simulator can derive team-composition
    # conditions (#157). Without it the `*_or_faction_in_team` family — 15 of the 28
    # team-gated modifiers in the corpus — is uncomputable outside team_calculator,
    # which the simulator path does not use. 0 means "unknown", which no real
    # faction_id uses, so an unpopulated snapshot simply never matches.
    agent_faction_id: int = 0

    # Potential rank (0 = locked, 1-5 unlocked) (#90). Carried so layers BELOW the
    # repository filter can gate on it too — the modifier and Attack-row gates run at
    # load time, but `moves/agents/*.json` specs are loaded per agent, not per build,
    # and one of their fields (`retag_as_aftershock`) is Potential-gated in the DB text.
    # Defaults to 6 (Level VI) for the same reason the DB column does: an unspecified rank means
    # "as fairy behaved before #90".
    potential_rank: int = 6
    # The agent's `hakushin_id`, as a string — identity, not a derived stat.
    # It is here because the Lumiflux assembler runs over snapshots at all three
    # `simulate()` call sites and needs a key for `load_lumiflux_spec`
    # (DESIGN_remielle.md §13.1's stated exception to "nothing Lumiflux on the
    # snapshot"). `agent_element == "lumiflux"` stays the predicate for "is this
    # a Lumiflux agent"; this is only how the spec is then found. Defaults to ""
    # so every hand-constructed test snapshot stays valid.
    agent_source_id: str = ""
    agent_level: int = 60
    skill_levels: str = "12,12,12,12,12"

    # Energy regen — base passive regen rate in DB basis points (÷100 = energy/s).
    # Default 0 means no passive regen (safe sentinel; real agents have 120 = 1.2/s).
    agent_base_energy_regen: int = 0
    # Agent ER% bonus from kit/W-engine (basis points; stacks additively with disc ER%).
    agent_energy_regen: int = 0

    # Sheer Damage (Rupture specialty) — intrinsic HP→SheerForce ratio in bp.
    # 0 for non-Rupture agents; 1000 for Yixuan (HP×10%).
    # The universal ATK conversion (30%) is in SHEER_ATK_RATIO, not here.
    agent_sheer_force_hp_ratio: int = 0

    # Disc stats as raw dicts (from user inventory)
    disc_stats: list[dict] = field(default_factory=list)

    # All applicable modifiers from every source (agent, W-engine, disc sets)
    modifiers: list[Modifier] = field(default_factory=list)

    # Saved stack counts for conditional modifiers
    stack_counts: dict[str, int] = field(default_factory=dict)

    # Mindscape level (0–6); used to gate mindscape-gated move Abloom triggers.
    mindscape_level: int = 0

    # Custom damage instances from the kit's `formulas[]` block, already resolved
    # against this build's mindscape and core level (see services/kit_formulas.py).
    # The simulator emits one per step whose scope matches.
    kit_formulas: tuple[KitFormula, ...] = ()

    # EX Special energy cost from the DB (Agent.ex_energy_cost).
    # None means the agent has no Energy-based EX (e.g. Decibel-only or non-EX agents).
    ex_energy_cost: int | None = None

    # Every priced action this agent has, from `agent_resource_costs`, as
    # ``cost_key -> (value, per_sec, resource)``. The scalar above is one of these when the
    # agent has exactly one; this carries the rest, which is what lets a move bill its own
    # mode instead of the whole agent's single price (DESIGN_channeled_moves.md 4.5).
    #
    # A plain dict (not a tuple of rows) because every consumer looks a key up. Empty on a
    # DB that has the migration but was never re-seeded -- and empty means "bill the scalar",
    # which is exactly today's behaviour, so an un-seeded box degrades to correct-as-before
    # rather than to free moves.
    resource_costs: dict[str, tuple[float, bool, str]] = field(default_factory=dict)

    # Provenance, not a stat (issue #121). One ``(build_id, agent_name)`` pair
    # per team support whose TEAM/ACTIVE modifiers
    # ``build_snapshot_from_db(support_builds=...)`` folded into ``modifiers``.
    # ``()`` means "this snapshot carries no teammate's contributions".
    #
    # It exists because that distinction is *not* recoverable from ``modifiers``
    # alone: ``owner_name`` is stamped on the primary's own kit, core, W-Engine
    # and disc modifiers too, so an ``owner_name`` scan cannot tell a support's
    # contribution from the DPS's own when the two agents share a name — and
    # deleting on that basis is exactly the bug #97 measured. The ``build_id``
    # half keeps the identity check exact even for a team holding two builds of
    # the same agent.
    #
    # Two consumers have opposite requirements — ``evaluate_steps_total`` /
    # ``score_disc_potential`` need supports present (there is no other route by
    # which a support's buff reaches a score) and
    # ``resolve_stateful_am_step_lists`` needs them absent (the simulator merges
    # every teammate's TEAM/ACTIVE modifier itself, and ``resolve_modifiers``
    # sums duplicates without deduping) — so each guards on this field rather
    # than trusting its caller to have picked the right snapshot.
    folded_supports: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class EnemySnapshot:
    """Enemy stats for a single damage calc."""

    level: int = 60
    base_def: int = 50
    element_res: int = 0  # Fallback resistance when res_map is absent or element is unknown
    stun_dmg_mult: int = 15000  # 10000 + enemy.stun_dmg_taken_ratio
    res_map: dict[str, int] = field(default_factory=dict)


def _resolve_stats(
    build: BuildSnapshot,
    buffs: ResolvedBuffs,
) -> tuple[TotalStats, DiscStats]:
    """Aggregate base + disc + resolved buff stats into TotalStats.

    Returns the disc accumulation alongside so the attribution layer
    can label flat / pct disc contributions per zone without recomputing.
    """
    disc = accumulate_disc_stats(build.disc_stats)

    inputs = StatInputs(
        agent_base_hp=build.agent_base_hp,
        agent_base_atk=build.agent_base_atk,
        agent_base_def=build.agent_base_def,
        wengine_base_atk=build.wengine_base_atk,
        # Disc percentage bonuses
        hp_pct=disc.hp_pct,
        atk_pct=disc.atk_pct,
        def_pct=disc.def_pct,
        # Disc flat bonuses
        flat_hp=disc.flat_hp,
        flat_atk=disc.flat_atk,
        flat_def=disc.flat_def,
        # Combat stats (agent base + disc)
        crit_rate=build.agent_crit_rate + disc.crit_rate,
        crit_dmg=build.agent_crit_dmg + disc.crit_dmg,
        anomaly_proficiency=build.agent_anomaly_proficiency + disc.anomaly_proficiency,
        agent_base_am=build.agent_anomaly_mastery,
        anomaly_mastery=disc.anomaly_mastery,
        agent_base_impact=build.agent_base_impact,
        impact=disc.impact,
        energy_regen=build.agent_energy_regen + disc.energy_regen,
        pen_flat=build.agent_pen_flat + disc.pen_flat,
        pen_ratio=build.agent_pen_ratio + disc.pen_ratio,
        # Elemental DMG from discs
        physical_dmg=disc.physical_dmg,
        fire_dmg=disc.fire_dmg,
        ice_dmg=disc.ice_dmg,
        electric_dmg=disc.electric_dmg,
        ether_dmg=disc.ether_dmg,
    )

    # Layer resolved buff stat bonuses on top
    buffs.apply_to_stat_inputs(inputs)

    return compute_total_stats(inputs), disc


def resolve_build_stats(
    build: BuildSnapshot,
    conditions: ActiveConditions,
    *,
    attack_scope: AttackScope = AttackScope.ALL,
) -> TotalStats:
    """Return the fully-resolved :class:`TotalStats` for a snapshot.

    Runs the same modifier-resolution pipeline as :func:`calculate_build_damage`
    but stops at stat computation — useful for optimizer stat-floor
    pruning, UI inspection, and any caller that needs the stats without
    paying for the damage calculation.
    """
    buffs = resolve_modifiers(
        build.modifiers,
        conditions,
        attack_scope=attack_scope,
        target_filter=ModifierTarget.SELF,
    )
    stats, _disc = _resolve_stats(build, buffs)
    return stats


def out_of_combat_stats(build: BuildSnapshot) -> TotalStats:
    """Stat aggregation with no modifiers applied — Fribbels-style "OoC".

    Includes: agent base (level-scaled + promotion + core tier bonuses
    that flow through the snapshot's base fields), W-Engine base ATK,
    disc main + substats. **Excludes** every :class:`Modifier` —
    mindscape buffs, kit DMG bonuses, set conditional bonuses, support
    team buffs, even unconditional kit bonuses. Pair with
    :func:`resolve_build_stats` to see what kit context adds.
    """
    empty_buffs = ResolvedBuffs()
    stats, _disc = _resolve_stats(build, empty_buffs)
    return stats


@dataclass(frozen=True)
class _CalcContext:
    """Internal container of intermediate values used by both calc paths."""

    buffs: ResolvedBuffs
    stats: TotalStats
    disc: DiscStats
    dmg_bonuses: list[int]
    vuln_bonuses: list[int]
    # Enemy RES for `dmg_element` (Lumiflux dual-tagging's RES-targeting sibling,
    # DESIGN_remielle.md §5.2). 0 when the caller didn't pass `enemy` — the
    # anomaly_simulator.py call sites that only need stats/buffs from this
    # context and resolve their own enemy RES separately via `_get_enemy_stat`.
    enemy_res: int = 0


# Which resolved stat a damage instance scales off. Keys are KitFormula.damage_stat
# (kit_formulas.FORMULA_DAMAGE_STATS); "atk" is every DB move and the default.
_DAMAGE_STAT_READERS: dict[str, Callable[[TotalStats], int]] = {
    "atk": lambda s: s.atk,
    "def": lambda s: s.defense,
    "anomaly_proficiency": lambda s: s.anomaly_proficiency,
}


def _resolve_and_calc(
    build: BuildSnapshot,
    conditions: ActiveConditions,
    attack_scope: AttackScope,
    element: str | None = None,
    enemy: EnemySnapshot | None = None,
) -> _CalcContext:
    """Shared resolution logic — returns the intermediate context.

    ``element`` overrides the agent's own element when picking the elemental DMG%
    bonus. Kit formulas need this: a custom damage instance may be a different
    element than its owner. It is also the Lumiflux dual-tagging choke point
    (DESIGN_remielle.md §5.2): when a Lumiflux build's flux has been resolved
    upstream, the caller passes the fluxed element here as ``element``, and
    ``dmg_element`` becomes that fluxed element for **stat aggregation only**
    (``resolve_modifiers(damage_element=…)`` DMG%-bucket/``element_scope``
    filtering, plus ``stats.elemental_dmg(dmg_element)`` below).
    ``build.agent_element`` is never touched here and stays ``"lumiflux"`` —
    every identity check (``EQUIPPER_IS_<element>``, ``SAME_ELEMENT_IN_TEAM``,
    attribute-count gates) is derived from ``build.agent_element`` upstream, in
    ``conditions``, and this function never looks at ``conditions`` when
    deciding ``dmg_element``, so flux can never leak into an identity check.

    ``enemy``, when provided, resolves this substitution's RES-targeting
    sibling (DESIGN §5.2) the same way: ``enemy.res_map`` is looked up by
    ``dmg_element``, falling back to ``enemy.element_res`` when the element
    isn't a res_map key. That fallback is what makes the no-flux Lumiflux case
    correct for free — ``"lumiflux"`` is never a real res_map key, so an
    unfluxed build's RES contribution is exactly ``enemy.element_res``, which
    is 0 by construction for a Lumiflux agent (``enemy_snapshot_from_db``
    builds ``element_res`` from the same res_map, keyed on the agent's own
    element). ``enemy_res`` is 0 when ``enemy`` is omitted (some
    anomaly_simulator.py call sites only need ``stats``/``buffs`` from this
    context and resolve RES separately).
    """
    dmg_element = element or build.agent_element
    buffs = resolve_modifiers(
        build.modifiers,
        conditions,
        attack_scope=attack_scope,
        target_filter=ModifierTarget.SELF,
        damage_element=dmg_element,
    )
    stats, disc = _resolve_stats(build, buffs)

    dmg_bonuses = list(buffs.dmg_bonuses)
    elem_bonus = stats.elemental_dmg(dmg_element)
    if elem_bonus:
        dmg_bonuses.append(elem_bonus)

    vuln_bonuses: list[int] = []
    if buffs.vulnerability:
        vuln_bonuses.append(buffs.vulnerability)

    enemy_res = 0
    if enemy is not None:
        enemy_res = enemy.res_map.get(dmg_element, enemy.element_res)

    return _CalcContext(
        buffs=buffs,
        stats=stats,
        disc=disc,
        dmg_bonuses=dmg_bonuses,
        vuln_bonuses=vuln_bonuses,
        enemy_res=enemy_res,
    )


def _sheer_to_damage_result(r: SheerDamageResult) -> DamageResult:
    """Convert a SheerDamageResult to a DamageResult for unified serialization.

    Maps SheerForce to effective_atk so callers have a consistent field to
    read the "effective scaling stat". def_mult=10000 (1.0×) signals the
    absent DEF zone. is_sheer=True lets serializers distinguish Sheer hits
    from standard hits for labelling purposes.
    """
    return DamageResult(
        total=r.total,
        base_dmg=r.base_dmg,
        boost_mult=r.boost_mult,
        crit_mult=r.crit_mult,
        def_mult=10000,
        res_mult=r.res_mult,
        vulnerability_mult=r.vulnerability_mult,
        stun_mult=r.stun_mult,
        effective_atk=r.sheer_force,
        level_factor_val=0,
        effective_enemy_def=0,
        stun_base_mult=r.stun_base_mult,
        is_sheer=True,
    )


def calculate_build_damage(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    multiplier: int,
    conditions: ActiveConditions,
    attack_scope: AttackScope,
    crit_mode: CritMode = CritMode.EXPECTED,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    with_attribution: bool = False,
    direct_dmg_bonus: int = 0,
    damage_stat: str = "atk",
    element: str | None = None,
) -> BuildDamageResult:
    """Compute standard damage for a single hit from a build snapshot.

    For Rupture-specialty agents, automatically dispatches to the Sheer
    Damage path (no DEF zone, SheerForce as scaling stat). All callers
    receive a ``DamageResult`` with ``is_sheer=True`` and ``def_mult=10000``
    when the Sheer path is used, so serializers can label correctly.

    ``damage_stat`` picks which resolved stat the multiplier scales off. Every
    move in the DB scales off ATK, but kit formulas do not: Ben's M2 scales off
    DEF and Alice's / Jane's M6 off Anomaly Proficiency. ``element`` likewise
    overrides the agent's own element for the DMG% bucket. Both default to the
    existing behaviour, so no non-formula caller changes.

    Returns damage result + resolved stats (no double-computation needed).
    A future rotation engine would call this per-action. When
    ``with_attribution`` is True, builds the per-zone source breakdown
    used by the UI hover tooltips.
    """
    if build.agent_specialty == "rupture":
        sheer = calculate_build_sheer(
            build=build,
            enemy=enemy,
            multiplier=multiplier,
            conditions=conditions,
            attack_scope=attack_scope,
            crit_mode=crit_mode,
            is_stunned=is_stunned,
            stun_dmg_mult=stun_dmg_mult,
            with_attribution=with_attribution,
        )
        return BuildDamageResult(
            damage=_sheer_to_damage_result(sheer.damage),
            stats=sheer.stats,
            attribution=sheer.attribution,
        )

    ctx = _resolve_and_calc(build, conditions, attack_scope, element, enemy=enemy)

    # MV scaling: some agents scale their motion values by a stat (e.g. YSG
    # core passive: effective_MV = base_MV × (1 + crit_dmg × factor)).
    # mv_crit_scaling is the factor in bp (2500 = 0.25).
    # Scale: 10000 + crit_dmg_bp × factor_bp // 10000 (both in bp → one /10000).
    effective_multiplier = multiplier
    if ctx.buffs.mv_crit_scaling:
        mv_scale = 10000 + ctx.stats.crit_dmg * ctx.buffs.mv_crit_scaling // 10000
        effective_multiplier = multiplier * mv_scale // 10000

    effective_stun_dmg_mult = stun_dmg_mult + ctx.buffs.stun_dmg_mult_bonus

    damage = calculate_standard_damage(
        scaling_stat=_DAMAGE_STAT_READERS[damage_stat](ctx.stats),
        multiplier=effective_multiplier,
        dmg_bonuses=ctx.dmg_bonuses,
        crit_rate=ctx.stats.crit_rate,
        crit_dmg=ctx.stats.crit_dmg,
        crit_mode=crit_mode,
        attacker_level=build.agent_level,
        enemy_base_def=enemy.base_def,
        enemy_level=enemy.level,
        pen_ratio=ctx.stats.pen_ratio,
        pen_flat=ctx.stats.pen_flat,
        def_ignore=ctx.buffs.def_ignore,
        enemy_res=ctx.enemy_res,
        res_reduction=ctx.buffs.res_reduction,
        res_ignore=ctx.buffs.res_ignore,
        vulnerability_bonuses=ctx.vuln_bonuses,
        is_stunned=is_stunned,
        stun_dmg_mult=effective_stun_dmg_mult,
        stun_area_override=ctx.buffs.stun_area_override,
        direct_dmg_bonus=direct_dmg_bonus,
    )

    attribution = (
        build_step_attribution(
            build,
            ctx.stats,
            ctx.disc,
            ctx.buffs,
            damage=damage,
            multiplier=effective_multiplier,
            enemy_res=ctx.enemy_res,
        )
        if with_attribution
        else None
    )
    return BuildDamageResult(damage=damage, stats=ctx.stats, attribution=attribution)


def calculate_build_sheer(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    multiplier: int,
    conditions: ActiveConditions,
    attack_scope: AttackScope,
    crit_mode: CritMode = CritMode.EXPECTED,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    with_attribution: bool = False,
) -> BuildSheerDamageResult:
    """Compute Sheer Damage for a Rupture agent's kit attack.

    Uses the Sheer Damage formula: no DEF zone, sheer_dmg_bonus is a separate
    multiplicative zone. Call this instead of calculate_build_damage when
    build.agent_specialty == "rupture" and the attack is a kit attack (not
    an anomaly proc).

    PEN%, PEN Flat, and DEF Ignore are not passed to calculate_sheer_damage
    because the Sheer path ignores DEF entirely.
    """
    ctx = _resolve_and_calc(build, conditions, attack_scope, enemy=enemy)

    sheer_force = resolve_sheer_force(ctx.stats, build, ctx.buffs)
    effective_stun_dmg_mult = stun_dmg_mult + ctx.buffs.stun_dmg_mult_bonus

    sheer_dmg_bonuses: list[int] = []
    if ctx.buffs.sheer_dmg_bonus:
        sheer_dmg_bonuses.append(ctx.buffs.sheer_dmg_bonus)

    damage = calculate_sheer_damage(
        sheer_force=sheer_force,
        multiplier=multiplier,
        dmg_bonuses=ctx.dmg_bonuses,
        sheer_dmg_bonuses=sheer_dmg_bonuses,
        crit_rate=ctx.stats.crit_rate,
        crit_dmg=ctx.stats.crit_dmg,
        crit_mode=crit_mode,
        enemy_res=ctx.enemy_res,
        res_reduction=ctx.buffs.res_reduction,
        res_ignore=ctx.buffs.res_ignore,
        vulnerability_bonuses=ctx.vuln_bonuses,
        is_stunned=is_stunned,
        stun_dmg_mult=effective_stun_dmg_mult,
    )

    attribution = (
        build_step_attribution(
            build,
            ctx.stats,
            ctx.disc,
            ctx.buffs,
            is_sheer=True,
            damage=damage,
            multiplier=multiplier,
            enemy_res=ctx.enemy_res,
        )
        if with_attribution
        else None
    )
    return BuildSheerDamageResult(damage=damage, stats=ctx.stats, attribution=attribution)


def calculate_build_anomaly(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    anomaly_type: str,
    conditions: ActiveConditions,
    procs: int | None = None,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    with_attribution: bool = False,
    refringe_mult: int = 10000,
) -> BuildAnomalyDamageResult:
    """Compute anomaly damage from a build snapshot.

    ``refringe_mult`` (basis points, 10000 = neutral) is Remielle's Refringe
    Coefficient zone — passed through untouched. Task 11 (the simulator's
    anomaly-trigger hook) resolves the real value; every other caller keeps
    the default and is byte-identical.
    """
    anom = _ANOMALY_TYPES[anomaly_type]

    ctx = _resolve_and_calc(build, conditions, AttackScope.ALL, enemy=enemy)

    effective_stun_dmg_mult = stun_dmg_mult + ctx.buffs.stun_dmg_mult_bonus

    # Add element-specific anomaly DMG bonus (e.g. Grace M4 shock_dmg_bonus for SHOCK).
    elem_anomaly_bonus = ctx.buffs.shock_dmg_bonus if anom.value == "shock" else 0

    # Issue #162: the anomaly-CRIT pool is element-scoped, and it must be filtered
    # against THIS ANOMALY's element, not the agent's. Jane's core grant is
    # Physical (Assault) only, so a fire teammate's Burn must not receive it.
    #
    # Resolved separately rather than by threading the element into
    # `_resolve_and_calc` above: that function's `element` also drives the
    # elemental-DMG% bucket and the enemy-RES lookup, so passing the anomaly's
    # element there would silently re-target both for every existing caller —
    # a far larger behavioural change than this issue, and one that would move
    # crossval fixtures. This second pass reads only the two crit buckets.
    _anom_crit = resolve_modifiers(
        build.modifiers,
        conditions,
        attack_scope=AttackScope.ALL,
        damage_element=ANOMALY_TO_ELEMENT[ModelAnomalyType(anom.value)].value,
    )

    damage = calculate_anomaly_damage(
        anomaly_type=anom,
        atk=ctx.stats.atk,
        anomaly_proficiency=ctx.stats.anomaly_proficiency,
        attacker_level=build.agent_level,
        dmg_bonuses=ctx.dmg_bonuses,
        anomaly_dmg_bonus=ctx.buffs.anomaly_dmg_bonus + elem_anomaly_bonus,
        enemy_base_def=enemy.base_def,
        enemy_level=enemy.level,
        pen_ratio=ctx.stats.pen_ratio,
        pen_flat=ctx.stats.pen_flat,
        def_ignore=ctx.buffs.def_ignore,
        enemy_res=ctx.enemy_res,
        res_reduction=ctx.buffs.res_reduction,
        res_ignore=ctx.buffs.res_ignore,
        vulnerability_bonuses=ctx.vuln_bonuses,
        is_stunned=is_stunned,
        stun_dmg_mult=effective_stun_dmg_mult,
        procs=procs,
        stun_area_override=ctx.buffs.stun_area_override,
        refringe_mult=refringe_mult,
        anomaly_crit_rate=_anom_crit.anomaly_crit_rate,
        anomaly_crit_dmg=_anom_crit.anomaly_crit_dmg,
    )

    attribution = (
        build_step_attribution(
            build,
            ctx.stats,
            ctx.disc,
            ctx.buffs,
            is_anomaly=True,
            damage=damage,
            multiplier=ANOMALY_BASE[anom][0],
            enemy_res=ctx.enemy_res,
        )
        if with_attribution
        else None
    )
    return BuildAnomalyDamageResult(damage=damage, stats=ctx.stats, attribution=attribution)
