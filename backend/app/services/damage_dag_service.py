"""DAG-backed damage service — parity adapter onto the Pando graph.

Takes the same :class:`BuildSnapshot` / :class:`EnemySnapshot` value
objects the procedural service consumes and produces a damage number by
running the Pando DAG. This is the bridge between the existing snapshot
API surface and the graph path that the optimizer and JIT (Phase 6.5)
will target.

The DAG works in fractional space throughout (1.0 = 100%) with no
per-zone flooring, so ``total`` may differ from
:func:`calculate_build_damage` by up to ~1% on reasonable inputs. That
drift is acceptable for optimizer Pareto ranking — monotonicity is
preserved. A future "exact mode" using ``custom('floor', ...)`` at zone
boundaries would match procedural to the unit.

Design: modifier resolution is delegated to :func:`resolve_modifiers` so
routing semantics stay identical across the two services. The buckets it
produces map onto DAG tags:

* Stat bonuses land on ``StatInputs`` (including ``<element>_dmg`` which
  :func:`register_base_stats` writes to ``elem_dmg_tag``), feeding the
  stats DAG and the boost zone's element term.
* Generic / skill-type ``dmg_bonus`` values are registered individually
  under ``{q: dmg_bonus}`` — the translator collapses scope here (see
  :mod:`app.pando.translator`).
* Combat-path bonuses (res_reduction, res_ignore, def_ignore,
  vulnerability, anomaly_dmg_bonus) are registered directly under their
  ``stat_tag`` so the damage zones can read them.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as _replace
from typing import TYPE_CHECKING

from app.formula.builder import const
from app.formula.tags import Tag
from app.formula.zzz.damage import (
    abloom_rescaled_node,
    anomaly_damage_node,
    luminize_damage_node,
    luminize_owner_scaled_node,
    refringe_credit_node,
    register_enemy,
    squad_atk_credit_node,
    standard_damage_node,
)
from app.formula.zzz.stats import Q_ATK_NODE, register_base_stats
from app.formula.zzz.tags import (
    ELEMENTS,
    Q_ANOMALY_DMG_BONUS,
    Q_ANOMALY_MASTERY,
    Q_ANOMALY_PROF,
    Q_ATK_PCT,
    Q_CRIT_DMG,
    Q_CRIT_RATE,
    Q_DEF_IGNORE,
    Q_DEF_PCT,
    Q_DMG_BONUS,
    Q_ENERGY_REGEN,
    Q_FLAT_ATK,
    Q_FLAT_DEF,
    Q_FLAT_HP,
    Q_HP_PCT,
    Q_IMPACT,
    Q_PEN_FLAT,
    Q_PEN_RATIO,
    Q_RES_IGNORE,
    Q_RES_REDUCTION,
    Q_VULNERABILITY,
    Q,
    elem_dmg_tag,
    stat_tag,
)
from app.pando.calculator import Calculator, NodeRegistry
from app.services.buff_resolver import resolve_modifiers
from app.services.damage_calculator import (
    ANOMALY_BASE,
    AnomalyType,
    CritMode,
)
from app.services.modifiers import AttackScope, ModifierTarget
from app.services.stat_calculator import (
    DiscStats,
    StatInputs,
    accumulate_disc_stats,
    compute_total_stats,
)

if TYPE_CHECKING:
    from app.services.buff_resolver import ResolvedBuffs
    from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
    from app.services.combo_types import (
        AbloomStep,
        LuminizeStep,
        RefringeCreditStep,
        SquadAtkCreditStep,
    )
    from app.services.modifiers import ActiveConditions
    from app.services.stat_calculator import TotalStats

_RUPTURE_SPECIALTY = "rupture"

_ANOMALY_TYPES = {t.value: t for t in AnomalyType}


@dataclass(frozen=True)
class BuildDamageDAGResult:
    """DAG-computed standard damage bundled with resolved stats."""

    total: float
    stats: TotalStats


@dataclass(frozen=True)
class BuildAnomalyDAGResult:
    """DAG-computed anomaly damage (per-proc * procs) with resolved stats.

    ``procs`` is effective proc-equivalents and may be fractional — see
    :class:`combo_types.AnomalyStep`.
    """

    total: float
    per_proc: float
    procs: float
    stats: TotalStats


def _snapshot_inputs(build: BuildSnapshot) -> StatInputs:
    """Mirror :func:`build_damage_service._resolve_stats` StatInputs assembly."""
    disc = accumulate_disc_stats(build.disc_stats)
    return StatInputs(
        agent_base_hp=build.agent_base_hp,
        agent_base_atk=build.agent_base_atk,
        agent_base_def=build.agent_base_def,
        wengine_base_atk=build.wengine_base_atk,
        hp_pct=disc.hp_pct,
        atk_pct=disc.atk_pct,
        def_pct=disc.def_pct,
        flat_hp=disc.flat_hp,
        flat_atk=disc.flat_atk,
        flat_def=disc.flat_def,
        crit_rate=build.agent_crit_rate + disc.crit_rate,
        crit_dmg=build.agent_crit_dmg + disc.crit_dmg,
        anomaly_proficiency=build.agent_anomaly_proficiency + disc.anomaly_proficiency,
        agent_base_am=build.agent_anomaly_mastery,
        anomaly_mastery=disc.anomaly_mastery,
        agent_base_impact=build.agent_base_impact,
        impact=disc.impact,
        energy_regen=disc.energy_regen,
        pen_flat=build.agent_pen_flat + disc.pen_flat,
        pen_ratio=build.agent_pen_ratio + disc.pen_ratio,
        physical_dmg=disc.physical_dmg,
        fire_dmg=disc.fire_dmg,
        ice_dmg=disc.ice_dmg,
        electric_dmg=disc.electric_dmg,
        ether_dmg=disc.ether_dmg,
    )


def _build_registry(
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    conditions: ActiveConditions,
    attack_scope: AttackScope,
    *,
    is_stunned: bool,
    stun_dmg_mult: int,
    damage_element: str | None = None,
    include_active: bool = True,
) -> tuple[NodeRegistry, ResolvedBuffs, TotalStats]:
    """Populate a fresh registry matching the procedural resolve path.

    Returns the registry plus the resolved buffs and aggregated
    :class:`TotalStats` — the callers bundle ``stats`` into their results
    for UI inspection parity with :func:`calculate_build_damage`.

    ``damage_element`` filters `element_scope`-restricted rows in
    :data:`ELEMENT_SCOPE_HONORED_STATS` (issue #164). This path used to omit it,
    which `resolve_modifiers`' own docstring flagged as the "DAG parity path"
    keeping pre-C7 behaviour — i.e. **every scoped row applied to every
    element**. That is 23 `res_ignore` / `res_reduction` rows across ~20 agents
    over-crediting on the optimizer and simulator paths: Miyabi's Ice RES-ignore
    reaching a Fire teammate's damage, and so on. RESArea is a full
    multiplicative zone, so this was not a rounding-level error.

    Callers pass the element the damage instance is already tagged as — the same
    one handed to the damage node — so `element_scope` filtering and the
    `<element>_dmg` bucket agree by construction rather than by coincidence.
    ``None`` keeps the unfiltered behaviour for callers with no element context.
    """
    buffs = resolve_modifiers(
        build.modifiers,
        conditions,
        attack_scope=attack_scope,
        target_filter=ModifierTarget.SELF,
        damage_element=damage_element,
        include_active=include_active,
    )

    inputs = _snapshot_inputs(build)
    buffs.apply_to_stat_inputs(inputs)
    stats = compute_total_stats(inputs)

    reg = NodeRegistry()
    register_base_stats(reg, inputs)
    register_enemy(
        reg,
        enemy_base_def=enemy.base_def,
        enemy_level=enemy.level,
        enemy_res=enemy.element_res,
        attacker_level=build.agent_level,
        is_stunned=is_stunned,
        stun_dmg_mult=stun_dmg_mult,
    )

    # Dmg-bonus aggregate (scope already filtered by resolve_modifiers).
    for value in buffs.dmg_bonuses:
        reg.register(Tag.of(**{Q: Q_DMG_BONUS}), const(value))

    # Combat-path contributions — zones read these directly.
    combat_map = (
        (Q_RES_REDUCTION, buffs.res_reduction),
        (Q_RES_IGNORE, buffs.res_ignore),
        (Q_DEF_IGNORE, buffs.def_ignore),
        (Q_VULNERABILITY, buffs.vulnerability),
        (Q_ANOMALY_DMG_BONUS, buffs.anomaly_dmg_bonus),
    )
    for quantity, value in combat_map:
        if value:
            reg.register(stat_tag(quantity), const(value))

    return reg, buffs, stats


def calculate_build_damage_dag(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    multiplier: int,
    conditions: ActiveConditions,
    attack_scope: AttackScope,
    crit_mode: CritMode = CritMode.EXPECTED,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    include_active: bool = True,
) -> BuildDamageDAGResult:
    """Compute standard damage via the Pando DAG.

    Parity with :func:`calculate_build_damage` within ~1% relative tolerance.
    Uses :data:`Q_ATK_NODE` for scaling; DEF / HP-scaling agents will need
    per-sheet routing (Phase 6.2i+).

    For Rupture-specialty agents, falls back to the procedural Sheer path
    because the DAG does not yet model SheerForce or the DEF-absent zone.
    """
    if build.agent_specialty == _RUPTURE_SPECIALTY:
        from app.services.build_damage_service import calculate_build_sheer  # noqa: PLC0415

        sheer = calculate_build_sheer(
            build=build,
            enemy=enemy,
            multiplier=multiplier,
            conditions=conditions,
            attack_scope=attack_scope,
            crit_mode=crit_mode,
            is_stunned=is_stunned,
            stun_dmg_mult=stun_dmg_mult,
        )
        return BuildDamageDAGResult(total=float(sheer.damage.total), stats=sheer.stats)

    reg, _buffs, stats = _build_registry(
        build,
        enemy,
        conditions,
        attack_scope,
        is_stunned=is_stunned,
        stun_dmg_mult=stun_dmg_mult,
        damage_element=build.agent_element,
        include_active=include_active,
    )
    node = standard_damage_node(
        Q_ATK_NODE,
        float(multiplier),
        build.agent_element,
        crit_mode,
    )
    total = Calculator(reg).compute(node)
    return BuildDamageDAGResult(total=total, stats=stats)


def calculate_build_anomaly_dag(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    anomaly_type: str,
    conditions: ActiveConditions,
    procs: float | None = None,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
) -> BuildAnomalyDAGResult:
    """Compute anomaly damage via the DAG (per-proc * proc count).

    The base multiplier and default proc count come from
    :data:`ANOMALY_BASE`. Callers can override ``procs`` for e.g. Disorder
    triggering mid-anomaly. Agent-specific anomaly-crit passives are not
    modelled here — anomaly damage cannot crit in the base path.
    """
    anom = _ANOMALY_TYPES[anomaly_type]
    base_mult_bp, default_procs = ANOMALY_BASE[anom]
    n_procs = procs if procs is not None else default_procs

    reg, _buffs, stats = _build_registry(
        build,
        enemy,
        conditions,
        AttackScope.ALL,
        is_stunned=is_stunned,
        stun_dmg_mult=stun_dmg_mult,
        damage_element=build.agent_element,
    )
    node = anomaly_damage_node(
        Q_ATK_NODE,
        base_mult_bp,
        element=build.agent_element,
    )
    per_proc = Calculator(reg).compute(node)
    return BuildAnomalyDAGResult(
        total=per_proc * n_procs,
        per_proc=per_proc,
        procs=n_procs,
        stats=stats,
    )


# ---- Disc-overlay fast path ------------------------------------------------
# The disc scorer evaluates the same (build, enemy, combo step, conditions)
# tuple against many disc-substat layouts. The bulk of the per-call work in
# _build_registry — modifier resolution, enemy/dmg-bonus/combat-path node
# registration, and base-stat registration of buff contributions — is
# invariant across those layouts. Pre-build a step context once, then for
# each disc layout overlay only the disc-derived Const() entries onto the
# registry, evaluate, and truncate the registry back. accumulate_disc_stats
# is purely additive (every field setattr is += against zero), so a Read
# with sum accumulator over the union of static + overlay entries equals a
# fresh registry built with disc contributions baked into StatInputs.

_DISC_STAT_TAGS: tuple[tuple[str, str], ...] = (
    ("hp_pct", Q_HP_PCT),
    ("atk_pct", Q_ATK_PCT),
    ("def_pct", Q_DEF_PCT),
    ("flat_hp", Q_FLAT_HP),
    ("flat_atk", Q_FLAT_ATK),
    ("flat_def", Q_FLAT_DEF),
    ("crit_rate", Q_CRIT_RATE),
    ("crit_dmg", Q_CRIT_DMG),
    ("anomaly_proficiency", Q_ANOMALY_PROF),
    ("anomaly_mastery", Q_ANOMALY_MASTERY),
    ("impact", Q_IMPACT),
    ("energy_regen", Q_ENERGY_REGEN),
    ("pen_flat", Q_PEN_FLAT),
    ("pen_ratio", Q_PEN_RATIO),
)
_DISC_ELEMENTS: tuple[str, ...] = ELEMENTS


@dataclass(frozen=True)
class DamageDAGStepContext:
    """Pre-built DAG state for repeated disc-stat evaluations.

    Captures the per-step static portion of the calculation: resolved
    buffs, enemy/dmg-bonus/combat-path node registrations, and the
    pre-built standard or anomaly damage node. The disc-derived stat
    contributions are NOT registered. Use
    :func:`compute_damage_with_disc_overlay` to evaluate against a
    specific disc layout — it overlays disc Const() entries on the
    registry, computes, then truncates.

    The overlay mutation makes a context single-threaded: serial reuse
    is fine; concurrent compute is not.
    """

    registry: NodeRegistry
    base_entry_count: int
    damage_node: object  # AnyNode at runtime, kept opaque for frozen dataclass


def build_damage_step_context(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    multiplier: int,
    conditions: ActiveConditions,
    attack_scope: AttackScope,
    crit_mode: CritMode = CritMode.EXPECTED,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    include_active: bool = True,
) -> DamageDAGStepContext:
    """Pre-build the static portion of a standard-damage DAG step.

    Reproduces :func:`_build_registry` but with the build's ``disc_stats``
    treated as empty so disc contributions can be overlaid per call.

    ``include_active=False`` drops ACTIVE-target modifiers, for a step the
    agent deals while OFF-FIELD (a Phase Flow tick). Default ``True`` keeps
    every other caller byte-identical.
    """
    no_disc = _replace(build, disc_stats=[])
    reg, _buffs, _stats = _build_registry(
        no_disc,
        enemy,
        conditions,
        attack_scope,
        is_stunned=is_stunned,
        stun_dmg_mult=stun_dmg_mult,
        damage_element=build.agent_element,
        include_active=include_active,
    )
    node = standard_damage_node(
        Q_ATK_NODE,
        float(multiplier),
        build.agent_element,
        crit_mode,
    )
    return DamageDAGStepContext(
        registry=reg,
        base_entry_count=len(reg._entries),  # noqa: SLF001 — overlay impl
        damage_node=node,
    )


def compute_damage_with_accumulated_disc(
    ctx: DamageDAGStepContext,
    disc: DiscStats,
) -> float:
    """Evaluate a pre-built step context against already-accumulated disc stats.

    Overlays disc-derived contributions onto ``ctx.registry``, runs a
    fresh :class:`Calculator` against ``ctx.damage_node``, and truncates
    the registry back to its static base. Numerically identical to
    calling :func:`calculate_build_damage_dag` with the same disc stats
    baked into the build snapshot. Callers that loop over many steps for
    the same disc layout should call :func:`accumulate_disc_stats` once
    and use this function per step.
    """
    reg = ctx.registry
    pre = ctx.base_entry_count
    try:
        for field_name, quantity in _DISC_STAT_TAGS:
            value = getattr(disc, field_name, 0)
            if value:
                reg.register(stat_tag(quantity), const(value))
        for element in _DISC_ELEMENTS:
            value = getattr(disc, f"{element}_dmg", 0)
            if value:
                reg.register(elem_dmg_tag(element), const(value))
        return float(Calculator(reg).compute(ctx.damage_node))
    finally:
        del reg._entries[pre:]  # noqa: SLF001 — overlay impl


def compute_damage_with_disc_overlay(
    ctx: DamageDAGStepContext,
    disc_stats: list[dict],
) -> float:
    """Evaluate a pre-built step context against a raw disc-stat list.

    Convenience wrapper: accumulates ``disc_stats`` then delegates to
    :func:`compute_damage_with_accumulated_disc`. Prefer the accumulated
    variant when the same disc layout is evaluated across many steps.
    """
    return compute_damage_with_accumulated_disc(ctx, accumulate_disc_stats(disc_stats))


# ---- Anomaly overlay fast path --------------------------------------------


@dataclass(frozen=True)
class AnomalyDAGStepContext:
    """Pre-built DAG state for repeated disc-stat anomaly evaluations.

    Analogous to :class:`DamageDAGStepContext` for anomaly damage.
    The anomaly node and proc count are fixed at build time; disc-derived
    stats are overlaid per call via :func:`compute_anomaly_with_disc_overlay`.

    Single-threaded reuse only — the overlay mutates the registry.
    """

    registry: NodeRegistry
    base_entry_count: int
    damage_node: object  # AnyNode at runtime, kept opaque for frozen dataclass
    n_procs: float  # effective proc-equivalents; fractional — see AnomalyStep


def build_anomaly_step_context(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    anomaly_type: str,
    conditions: ActiveConditions,
    procs: float | None = None,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
) -> AnomalyDAGStepContext:
    """Pre-build the static portion of an anomaly-damage DAG step.

    Mirrors :func:`build_damage_step_context` for anomaly calculations.
    ``disc_stats`` are excluded so they can be overlaid per call.
    """
    anom = _ANOMALY_TYPES[anomaly_type]
    base_mult_bp, default_procs = ANOMALY_BASE[anom]
    n_procs = procs if procs is not None else default_procs

    no_disc = _replace(build, disc_stats=[])
    reg, _buffs, _stats = _build_registry(
        no_disc,
        enemy,
        conditions,
        AttackScope.ALL,
        is_stunned=is_stunned,
        stun_dmg_mult=stun_dmg_mult,
        damage_element=build.agent_element,
    )
    node = anomaly_damage_node(
        Q_ATK_NODE,
        base_mult_bp,
        element=build.agent_element,
    )
    return AnomalyDAGStepContext(
        registry=reg,
        base_entry_count=len(reg._entries),  # noqa: SLF001 — overlay impl
        damage_node=node,
        n_procs=n_procs,
    )


def compute_anomaly_with_accumulated_disc(
    ctx: AnomalyDAGStepContext,
    disc: DiscStats,
) -> float:
    """Evaluate a pre-built anomaly context against already-accumulated disc stats.

    Overlays disc contributions onto ``ctx.registry``, computes per-proc
    damage, multiplies by ``ctx.n_procs``, and truncates the registry.
    Callers that loop over many steps for the same disc layout should call
    :func:`accumulate_disc_stats` once and use this function per step.
    """
    reg = ctx.registry
    pre = ctx.base_entry_count
    try:
        for field_name, quantity in _DISC_STAT_TAGS:
            value = getattr(disc, field_name, 0)
            if value:
                reg.register(stat_tag(quantity), const(value))
        for element in _DISC_ELEMENTS:
            value = getattr(disc, f"{element}_dmg", 0)
            if value:
                reg.register(elem_dmg_tag(element), const(value))
        per_proc = float(Calculator(reg).compute(ctx.damage_node))
        return per_proc * ctx.n_procs
    finally:
        del reg._entries[pre:]  # noqa: SLF001 — overlay impl


def compute_anomaly_with_disc_overlay(
    ctx: AnomalyDAGStepContext,
    disc_stats: list[dict],
) -> float:
    """Evaluate a pre-built anomaly context against a raw disc-stat list.

    Convenience wrapper: accumulates ``disc_stats`` then delegates to
    :func:`compute_anomaly_with_accumulated_disc`. Prefer the accumulated
    variant when the same disc layout is evaluated across many steps.
    """
    return compute_anomaly_with_accumulated_disc(ctx, accumulate_disc_stats(disc_stats))


@dataclass(frozen=True)
class LuminizeDAGStepContext:
    """Pre-built DAG state for repeated disc-stat Luminize evaluations.

    Analogous to :class:`AnomalyDAGStepContext`, with one deliberate
    difference: the node is built by :func:`luminize_damage_node`, **not** by
    parameterising the anomaly node. Six of Luminize's inputs (``def_ignore``,
    ``res_reduction``, ``res_ignore``, vulnerability, the stun bonus and
    AnomalyBoostArea) belong to Remielle rather than to the build being scored,
    and the anomaly node reads every one of them from the registry — which here
    holds the *scored* build. Those reads are ``"sum"`` reads, so overriding
    them by registering a corrective entry would add to the wrong agent's value
    instead of replacing it. See E-8 in ``docs/LOG_remielle.md``.

    Single-threaded reuse only — the overlay mutates the registry.
    """

    registry: NodeRegistry
    base_entry_count: int
    damage_node: object  # AnyNode at runtime, kept opaque for frozen dataclass


def build_luminize_step_context(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    step: LuminizeStep,
    conditions: ActiveConditions,
) -> LuminizeDAGStepContext:
    """Pre-build the static portion of a Luminize step for ``build``.

    ``build`` is the agent whose Voidflare was captured — in the optimizer, the
    build being enumerated. ``disc_stats`` are excluded so they can be overlaid
    per call, exactly as for the standard and anomaly contexts.

    Takes no stun arguments, unlike the other two context builders. The stun
    zone is already inside ``step.constant_factor``, resolved from the
    simulation's own stun state at the moment Luminize fired; registering it
    again here would square it. The registry is therefore built unstunned.
    """
    no_disc = _replace(build, disc_stats=[])
    reg, _buffs, _stats = _build_registry(
        no_disc,
        enemy,
        conditions,
        AttackScope.ALL,
        is_stunned=False,
        stun_dmg_mult=10000,  # inert: is_stunned=False, and the zone is in constant_factor
        damage_element=step.voidflare_element,
    )
    node = luminize_damage_node(
        Q_ATK_NODE,
        step.effective_mult_bp,
        step.voidflare_element,
        step.def_ignore,
        step.constant_factor,
    )
    return LuminizeDAGStepContext(
        registry=reg,
        base_entry_count=len(reg._entries),  # noqa: SLF001 — overlay impl
        damage_node=node,
    )


def build_luminize_owner_scaled_context(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    step: LuminizeStep,
    conditions: ActiveConditions,
) -> LuminizeDAGStepContext:
    """Pre-build a Luminize step whose *Remielle* half varies per candidate.

    P-F2 / hardening Task 15. ``build`` here is the Lumiflux agent herself —
    she is the optimized DPS — so the registry's live Anomaly Proficiency is
    hers, which is exactly the term the node needs. The captured teammate's
    half stays frozen inside ``step.frozen_damage``.

    Mirrors :func:`build_luminize_step_context` in shape (disc stats excluded so
    they can be overlaid per call, registry built unstunned because the stun
    zone is already inside the frozen damage), but wires a different node.
    """
    no_disc = _replace(build, disc_stats=[])
    reg, buffs, _stats = _build_registry(
        no_disc,
        enemy,
        conditions,
        AttackScope.ALL,
        is_stunned=False,
        stun_dmg_mult=10000,  # inert: the whole zone is inside frozen_damage
        # Same element as the sibling context (#164). Only her AP and Anomaly
        # DMG% are read live here, neither of which is element-scoped — but
        # filtering on the Luminize's own element keeps the two Luminize
        # contexts resolving the same modifier set, so a future element-scoped
        # stat cannot behave differently between them.
        damage_element=step.voidflare_element,
    )
    # Her AnomalyBoostArea, live for THIS frame. `build` here is `frame_snap`,
    # which carries the frame's disc-set modifiers — so a 4pc Feathered Fate
    # frame resolves +15% Attribute Anomaly DMG that the simulation's
    # disc-stripped run could not have seen. Resolved once per frame, not per
    # candidate, because that is the grain at which it actually varies.
    frozen_boost = step.owner_anomaly_boost_mult
    boost_ratio = 1.0
    if frozen_boost:
        boost_ratio = (10000 + buffs.anomaly_dmg_bonus) / frozen_boost
    node = luminize_owner_scaled_node(
        float(step.frozen_damage or 0.0),
        int(step.owner_base_mult_bp or 0),
        int(step.owner_ap_bonus_bp or 0),
        step.effective_mult_bp,
        boost_ratio,
    )
    return LuminizeDAGStepContext(
        registry=reg,
        base_entry_count=len(reg._entries),  # noqa: SLF001 — overlay impl
        damage_node=node,
    )


def build_refringe_credit_context(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    step: RefringeCreditStep,
    conditions: ActiveConditions,
) -> LuminizeDAGStepContext:
    """Pre-build the scored build's attributable slice of a teammate's tick (#160).

    Reuses :class:`LuminizeDAGStepContext` rather than introducing a parallel
    type: the two have identical shape — a registry with disc stats excluded so
    they can be overlaid per candidate, plus one damage node whose only live
    term is Anomaly Proficiency. The overlay helpers are therefore shared too.

    Built unstunned with an inert stun multiplier for the same reason the
    owner-scaled Luminize context is: every zone except her coefficient is
    already inside ``step.frozen_tick_damage``, which the simulator computed
    against the *teammate's* build. Re-resolving any of it here would be
    re-scoring the teammate's damage with the target's stats — the error #112
    fixed.
    """
    no_disc = _replace(build, disc_stats=[])
    reg, _buffs, _stats = _build_registry(
        no_disc,
        enemy,
        conditions,
        AttackScope.ALL,
        is_stunned=False,
        stun_dmg_mult=10000,  # inert: every zone is inside frozen_tick_damage
        # #164: filter element-scoped rows against the element this damage is
        # tagged as, matching every sibling context builder. Nothing this node
        # reads is element-scoped today, so it changes no number -- threaded for
        # consistency, so a future element-scoped stat cannot behave differently
        # here than in the contexts beside it.
        damage_element=build.agent_element,
    )
    node = refringe_credit_node(
        step.frozen_tick_damage,
        step.refringe_mult_at_stripped_ap,
        step.refringe_ap_ratio_bp,
        step.refringe_flat_bonus_bp,
    )
    return LuminizeDAGStepContext(
        registry=reg,
        base_entry_count=len(reg._entries),  # noqa: SLF001 — overlay impl
        damage_node=node,
    )


def build_abloom_context(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    step: AbloomStep,
    conditions: ActiveConditions,
) -> LuminizeDAGStepContext:
    """Pre-build an Abloom instance whose AP term varies per candidate (#163).

    Same shape as the credit contexts — one node, disc stats excluded so they
    overlay per candidate, built unstunned because every zone except the AP term
    is already inside ``step.frozen_abloom_damage``.
    """
    no_disc = _replace(build, disc_stats=[])
    reg, _buffs, _stats = _build_registry(
        no_disc,
        enemy,
        conditions,
        AttackScope.ALL,
        is_stunned=False,
        stun_dmg_mult=10000,  # inert: every zone is inside frozen_abloom_damage
        # #164: filter element-scoped rows against the element this damage is
        # tagged as, matching every sibling context builder. Nothing this node
        # reads is element-scoped today, so it changes no number -- threaded for
        # consistency, so a future element-scoped stat cannot behave differently
        # here than in the contexts beside it.
        damage_element=build.agent_element,
    )
    node = abloom_rescaled_node(step.frozen_abloom_damage, step.frozen_ap, step.ap_scaled)
    return LuminizeDAGStepContext(
        registry=reg,
        base_entry_count=len(reg._entries),  # noqa: SLF001 — overlay impl
        damage_node=node,
    )


def build_squad_atk_credit_context(
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    step: SquadAtkCreditStep,
    conditions: ActiveConditions,
) -> LuminizeDAGStepContext:
    """Pre-build the target's share of a teammate's ATK-scaled damage (#160, A4).

    Same shape and same reasoning as :func:`build_refringe_credit_context` — one
    node, disc stats excluded so they overlay per candidate — except the live
    term is the target's total ATK rather than their Anomaly Proficiency, so the
    registry's ``Q_ATK_NODE`` is what varies.

    Built unstunned with an inert stun multiplier because every zone except the
    grant is already inside ``step.frozen_teammate_damage``, which the simulator
    computed against the TEAMMATE's build.
    """
    no_disc = _replace(build, disc_stats=[])
    reg, _buffs, _stats = _build_registry(
        no_disc,
        enemy,
        conditions,
        AttackScope.ALL,
        is_stunned=False,
        stun_dmg_mult=10000,  # inert: every zone is inside frozen_teammate_damage
        # #164: element-scoped rows filter against the element this damage is
        # tagged as, matching every sibling context builder.
        damage_element=build.agent_element,
    )
    node = squad_atk_credit_node(
        Q_ATK_NODE,
        step.frozen_teammate_damage,
        step.teammate_atk_at_sim,
        step.grant_rows,
    )
    return LuminizeDAGStepContext(
        registry=reg,
        base_entry_count=len(reg._entries),  # noqa: SLF001 — overlay impl
        damage_node=node,
    )


def compute_luminize_with_accumulated_disc(
    ctx: LuminizeDAGStepContext,
    disc: DiscStats,
) -> float:
    """Evaluate a pre-built Luminize context against already-accumulated disc stats.

    Mirrors :func:`compute_anomaly_with_accumulated_disc`; there is no proc
    count to multiply by (Luminize is always exactly one instance).
    """
    reg = ctx.registry
    pre = ctx.base_entry_count
    try:
        for field_name, quantity in _DISC_STAT_TAGS:
            value = getattr(disc, field_name, 0)
            if value:
                reg.register(stat_tag(quantity), const(value))
        for element in _DISC_ELEMENTS:
            value = getattr(disc, f"{element}_dmg", 0)
            if value:
                reg.register(elem_dmg_tag(element), const(value))
        return float(Calculator(reg).compute(ctx.damage_node))
    finally:
        del reg._entries[pre:]  # noqa: SLF001 — overlay impl


def compute_luminize_with_disc_overlay(
    ctx: LuminizeDAGStepContext,
    disc_stats: list[dict],
) -> float:
    """Evaluate a pre-built Luminize context against a raw disc-stat list."""
    return compute_luminize_with_accumulated_disc(ctx, accumulate_disc_stats(disc_stats))


def evaluate_steps_total(  # noqa: PLR0912 — one branch per step kind; the
    # dispatch is deliberately flat so `test_step_dispatch_coverage` can read it.
    *,
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    steps: list,
    conditions: ActiveConditions,
    crit_mode: CritMode = CritMode.EXPECTED,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
) -> float:
    """Return total damage for a pre-resolved step list via the DAG.

    Thin replacement for evaluate_combo_dag(...).total_damage — used in
    baseline-damage computations where only the scalar total is needed.
    Skips StunTriggerStep / StunEndStep markers silently.
    """
    from app.services.combo_types import (  # noqa: PLC0415
        AbloomStep,
        AnomalyStep,
        ComboStep,
        LuminizeStep,
        RefringeCreditStep,
        SquadAtkCreditStep,
        StunEndStep,
        StunTriggerStep,
        TeammateDamageStep,
    )

    total: float = 0.0
    for step in steps:
        if isinstance(step, (StunTriggerStep, StunEndStep)):
            continue
        if isinstance(step, TeammateDamageStep):
            # Pure constant — no candidate moves it. Included so the total
            # means TEAM damage; excluded from the target's attributed share.
            total += step.frozen_damage
            continue
        if isinstance(step, AnomalyStep):
            total += calculate_build_anomaly_dag(
                build=build,
                enemy=enemy,
                anomaly_type=step.anomaly_type,
                conditions=conditions,
                procs=step.procs_override,
                is_stunned=is_stunned,
                stun_dmg_mult=stun_dmg_mult,
            ).total
        elif isinstance(step, LuminizeStep):
            # Order matters, and it mirrors `optimize_discs` deliberately.
            # `is_owner_scaled` MUST be tested before `frozen_damage`: for the
            # P-F2 shape (the Lumiflux agent is herself the scored build) BOTH
            # are set, and there `frozen_damage` is the rescale BASE, not the
            # answer -- it was computed against her DISC-STRIPPED snapshot. This
            # branch used to test `frozen_damage` first and add that stale value,
            # so her live Anomaly Proficiency moved her own Luminize by exactly
            # zero on the baseline path while the optimizer rescaled it
            # correctly. The two paths disagreed, and since `current_build_damage`
            # comes from here, it understated the build AP is supposed to scale.
            if step.is_owner_scaled:
                total += compute_luminize_with_disc_overlay(
                    build_luminize_owner_scaled_context(
                        build=build, enemy=enemy, step=step, conditions=conditions
                    ),
                    build.disc_stats,
                )
            elif step.frozen_damage is not None:
                # Captured from a support: a build the optimizer never strips and
                # never varies, so the simulation's number is exact.
                total += step.frozen_damage
            else:
                ctx = build_luminize_step_context(
                    build=build,
                    enemy=enemy,
                    step=step,
                    conditions=conditions,
                )
                total += compute_luminize_with_disc_overlay(ctx, build.disc_stats)
        elif isinstance(step, AbloomStep):
            total += compute_luminize_with_disc_overlay(
                build_abloom_context(
                    build=build, enemy=enemy, step=step, conditions=conditions
                ),
                build.disc_stats,
            )
        elif isinstance(step, SquadAtkCreditStep):
            total += compute_luminize_with_disc_overlay(
                build_squad_atk_credit_context(
                    build=build,
                    enemy=enemy,
                    step=step,
                    conditions=conditions,
                ),
                build.disc_stats,
            )
        elif isinstance(step, RefringeCreditStep):
            total += compute_luminize_with_disc_overlay(
                build_refringe_credit_context(
                    build=build,
                    enemy=enemy,
                    step=step,
                    conditions=conditions,
                ),
                build.disc_stats,
            )
        elif isinstance(step, ComboStep):
            total += calculate_build_damage_dag(
                build=build,
                enemy=enemy,
                multiplier=step.multiplier,
                conditions=conditions,
                attack_scope=step.scope,
                crit_mode=crit_mode,
                is_stunned=is_stunned,
                stun_dmg_mult=stun_dmg_mult,
                include_active=not step.off_field,
            ).total
        else:
            # Explicit rather than an `else` that assumes ComboStep: a new step
            # type used to reach `step.multiplier` and die with an AttributeError
            # pointing at this line instead of at the type that was never wired
            # up (E-8 acceptance item 4).
            raise TypeError(f"evaluate_steps_total: unhandled step type {type(step).__name__}")
    return total
