"""Damage multiplier zones as DAG nodes.

Ports :mod:`app.services.damage_calculator` to Pando DAG form, one
multiplier zone at a time. The procedural path works in basis points
(``10000 = 100%``); the DAG works in fractional space (``1.0 = 100%``)
so downstream interval arithmetic and monotonicity analysis operate on
well-defined continuous values.

This module exposes the *simple* zones — boost, crit (expected / always /
never), res (with ``[0, 2]`` clamp), vulnerability, stun. The DEF area
and composite ``standard_damage_node`` / ``anomaly_damage_node`` land in
the next increment together with the level-factor subscript table.

Contracts:
* Every node returns a fractional multiplier (``1.0`` = no change).
* Reads use ``sum`` accumulators so empty registrations collapse to ``0``
  (or the neutral identity when wrapped in a ``1 + …`` term).
* Enemy-side inputs (``enemy_res``, ``stun_bonus``) and buffs
  (``res_reduction``, ``vulnerability``) come from the registry — register
  them once per compute via the stats DAG + a future ``register_enemy``
  helper.

Why fractional instead of basis-point DAG: Pando's JIT path (Phase 6.5)
targets ``float64`` arithmetic; keeping basis points would force every
node to carry a ``/ 10000`` shim. The few percent of precision lost at
floor boundaries is acceptable — the procedural path stays authoritative
for the simulator's ``POST /api/v1/damage/calculate`` endpoint.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from app.formula.builder import const, custom, max_, min_, prod_, read_, sum_, sumfrac
from app.formula.tags import Tag
from app.formula.zzz.tags import (
    ELEM,
    Q_ADDITIONAL_MV,
    Q_AGENT_BASE_AM,
    Q_AM_PCT,
    Q_ANOMALY_BUILDUP,
    Q_ANOMALY_DMG_BONUS,
    Q_ANOMALY_MASTERY,
    Q_ANOMALY_PROF,
    Q_ATTACKER_LEVEL,
    Q_ATTACKER_LEVEL_FACTOR,
    Q_BASE_DMG_BONUS_PCT,
    Q_CRIT_DMG,
    Q_CRIT_RATE,
    Q_DEF_IGNORE,
    Q_DISORDER_DMG_BONUS,
    Q_DMG_BONUS,
    Q_ENEMY_ANOMALY_RES,
    Q_ENEMY_BASE_DEF,
    Q_ENEMY_LEVEL_FACTOR,
    Q_ENEMY_RES,
    Q_FLAT_BASE_DMG,
    Q_MAX_DURATION,
    Q_PEN_FLAT,
    Q_PEN_RATIO,
    Q_REMAINING_DURATION,
    Q_RES_IGNORE,
    Q_RES_REDUCTION,
    Q_STUN_BONUS,
    Q_STUN_BUILDUP_BONUS,
    Q_VORTEX_DMG_BONUS,
    Q_VULNERABILITY,
    Q,
    elem_dmg_tag,
    stat_tag,
)

if TYPE_CHECKING:
    from app.formula.nodes import AnyNode
    from app.pando.calculator import NodeRegistry
    from app.services.damage_calculator import AnomalyType, CritMode


# Basis-points → fraction. Kept as a module constant so the cache key for
# ``prod_(<read>, _BP)`` stays stable across calls.
_BP = 0.0001


# ---- Boost area -----------------------------------------------------------


def boost_area_node(element: str) -> AnyNode:
    """``1 + (sum of generic + elemental dmg bonuses) / 10000``.

    Generic ``{q: dmg_bonus}`` contributions and the element-specific
    ``{q: elem_dmg, elem: <element>}`` contributions both add linearly,
    matching :func:`dmg_bonus_multiplier`.
    """
    generic = read_(Tag.of(**{Q: Q_DMG_BONUS}), "sum")
    elemental = read_(elem_dmg_tag(element), "sum")
    return sum_(1, prod_(sum_(generic, elemental), _BP))


# ---- Crit area ------------------------------------------------------------


def crit_area_node(mode: CritMode) -> AnyNode:
    """Crit multiplier under ``mode``.

    * ``EXPECTED``: ``1 + min(crit_rate, 10000) * crit_dmg / 1e8``
    * ``CRIT``: ``1 + crit_dmg / 10000`` (rate ignored)
    * ``NO_CRIT``: ``1.0``
    """
    from app.services.damage_calculator import CritMode  # noqa: PLC0415

    crit_rate = read_(stat_tag(Q_CRIT_RATE), "sum")
    crit_dmg = read_(stat_tag(Q_CRIT_DMG), "sum")

    if mode == CritMode.NO_CRIT:
        return sum_(1)  # pure 1.0, no reads — cache-friendly
    if mode == CritMode.CRIT:
        return sum_(1, prod_(crit_dmg, _BP))
    # EXPECTED: clamp rate to [0, 10000] so >100% crit doesn't over-credit.
    clamped_rate = max_(0, min_(crit_rate, 10000))
    return sum_(1, prod_(clamped_rate, crit_dmg, _BP, _BP))


# ---- RES area -------------------------------------------------------------


def res_area_node() -> AnyNode:
    """``clamp(0, 2, 1 - enemy_res/10000 + res_reduction/10000 + res_ignore/10000)``.

    Enemy RES comes in as basis points (``-2000`` = -20% weakness). The
    formula matches :func:`res_multiplier`, clamped at procedural bounds
    (``0`` to ``2.0``).
    """
    enemy_res = read_(stat_tag(Q_ENEMY_RES), "sum")
    reduction = read_(stat_tag(Q_RES_REDUCTION), "sum")
    ignore = read_(stat_tag(Q_RES_IGNORE), "sum")
    # 1 - enemy_res * BP + reduction * BP + ignore * BP
    # = 1 + (-enemy_res + reduction + ignore) * BP
    raw = sum_(
        1,
        prod_(sum_(prod_(enemy_res, -1), reduction, ignore), _BP),
    )
    return max_(0, min_(raw, 2))


# ---- Vulnerability area ---------------------------------------------------


def vulnerability_area_node() -> AnyNode:
    """``1 + sum(vulnerability_bonuses) / 10000`` — matches :func:`dmg_taken_multiplier`."""
    bonuses = read_(stat_tag(Q_VULNERABILITY), "sum")
    return sum_(1, prod_(bonuses, _BP))


# ---- Stun area ------------------------------------------------------------


def stun_area_node() -> AnyNode:
    """``1 + stun_bonus/10000`` — defaults to ``1.0`` when no stun is registered.

    Register ``Const(stun_dmg_mult - 10000)`` at :data:`Q_STUN_BONUS` to
    activate (e.g. ``Const(5000)`` for the default 1.5x stun window).
    Procedural clamp bounds ``[2000, 50000]`` → fractional ``[0.2, 5.0]``.
    """
    bonus = read_(stat_tag(Q_STUN_BONUS), "sum")
    return max_(0.2, min_(sum_(1, prod_(bonus, _BP)), 5))


# ---- DEF area -------------------------------------------------------------


def def_area_node(def_ignore_bp: int | None = None) -> AnyNode:
    """``atk_factor / (effective_def + atk_factor)`` — mirrors :func:`def_multiplier`.

    ``effective_def = max(0, enemy_def * (1 - def_ignore) * (1 - pen_ratio) - pen_flat)``
    where ``enemy_def = enemy_base_def * enemy_level_factor / 50``.

    Level factors are pre-computed by :func:`register_enemy` so the DAG
    only reads two pre-scaled integers — no in-graph level polynomial
    yet. Promoting attacker level to a DAG variable (so the optimizer
    can sweep it) will require moving level-factor into a subscript.

    ``def_ignore_bp`` replaces the registry read with a baked constant.
    ``None`` — the default, and every caller but Luminize — reads
    :data:`Q_DEF_IGNORE` from the registry exactly as before. Luminize needs
    the override because its DEF-ignore is *Remielle's* while its PEN is the
    scored build's, and the registry read is a ``"sum"``: registering a
    corrective entry would add to the wrong agent's value rather than replace
    it (E-8, ``docs/LOG_remielle.md``).
    """
    atk_factor = read_(stat_tag(Q_ATTACKER_LEVEL_FACTOR), "sum")
    enemy_factor = read_(stat_tag(Q_ENEMY_LEVEL_FACTOR), "sum")
    enemy_base_def = read_(stat_tag(Q_ENEMY_BASE_DEF), "sum")
    pen_ratio = read_(stat_tag(Q_PEN_RATIO), "sum")
    pen_flat = read_(stat_tag(Q_PEN_FLAT), "sum")
    def_ignore = (
        const(def_ignore_bp) if def_ignore_bp is not None else read_(stat_tag(Q_DEF_IGNORE), "sum")
    )

    # enemy_def = enemy_base_def * enemy_factor / 50 (0.02 = 1/50).
    enemy_def = prod_(enemy_base_def, enemy_factor, 0.02)

    # Apply def_ignore and pen_ratio as (1 - x/10000) multipliers
    shredded = prod_(
        enemy_def,
        sum_(1, prod_(def_ignore, -_BP)),
        sum_(1, prod_(pen_ratio, -_BP)),
    )
    # Subtract pen_flat, floor at 0
    effective_def = max_(0, sum_(shredded, prod_(pen_flat, -1)))

    return sumfrac(atk_factor, effective_def)


# ---- Composite --------------------------------------------------------------


def base_damage_node(scaling_stat: AnyNode, multiplier_bp: float) -> AnyNode:
    """``scaling_stat * multiplier_bp / 10000`` — mirrors :func:`base_damage`.

    ``multiplier_bp`` is a compile-time attack constant (e.g. Anby's BA3
    hit = 3120 bp). No floor: the DAG keeps base damage continuous.
    """
    return prod_(scaling_stat, multiplier_bp * _BP)


def standard_damage_node(
    scaling_stat: AnyNode,
    multiplier_bp: float,
    element: str,
    crit_mode: CritMode | None = None,
) -> AnyNode:
    """Composite of the 7 standard-damage zones.

    ``total = base * boost * crit * def * res * vulnerability * stun``

    Matches :func:`calculate_standard_damage` up to floor-div drift; the
    DAG stays float throughout, so values may differ from the procedural
    path by a few units on chained rounding. That's acceptable for the
    optimizer's Pareto ranking (monotonicity is preserved).
    """
    from app.services.damage_calculator import CritMode  # noqa: PLC0415

    mode = crit_mode if crit_mode is not None else CritMode.EXPECTED
    return prod_(
        base_damage_node(scaling_stat, multiplier_bp),
        boost_area_node(element),
        crit_area_node(mode),
        def_area_node(),
        res_area_node(),
        vulnerability_area_node(),
        stun_area_node(),
    )


# ---- Registry population --------------------------------------------------


def register_enemy(
    registry: NodeRegistry,
    *,
    enemy_base_def: int,
    enemy_level: int,
    enemy_res: int,
    attacker_level: int = 60,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    enemy_anomaly_res: dict[str, int] | None = None,
    stun_buildup_multiplier: int = 10000,
) -> None:
    """Populate enemy / damage-context constants for one compute.

    ``stun_dmg_mult`` is ignored when ``is_stunned`` is False. Level
    factors are pre-computed here (calling into the procedural helper)
    to keep the DAG free of the level polynomial — swap this for a
    Subscript table if attacker level becomes a DAG variable.
    """
    from app.services.damage_calculator import level_factor  # noqa: PLC0415

    registry.register(stat_tag(Q_ENEMY_BASE_DEF), const(enemy_base_def))
    registry.register(stat_tag(Q_ENEMY_LEVEL_FACTOR), const(level_factor(enemy_level)))
    registry.register(stat_tag(Q_ATTACKER_LEVEL_FACTOR), const(level_factor(attacker_level)))
    registry.register(stat_tag(Q_ATTACKER_LEVEL), const(attacker_level))
    registry.register(stat_tag(Q_ENEMY_RES), const(enemy_res))
    if is_stunned:
        registry.register(stat_tag(Q_STUN_BONUS), const(stun_dmg_mult - 10000))
        registry.register(stat_tag(Q_STUN_BUILDUP_BONUS), const(stun_buildup_multiplier - 10000))
    if enemy_anomaly_res:
        for element, res in enemy_anomaly_res.items():
            registry.register(
                Tag.of(**{Q: Q_ENEMY_ANOMALY_RES, ELEM: element}),
                const(res),
            )


# ---- Anomaly zones --------------------------------------------------------


def anomaly_proficiency_area_node() -> AnyNode:
    """``clamp(0, 10, anomaly_proficiency / 100)`` — matches
    :func:`anomaly_proficiency_multiplier`.

    Registered ``anomaly_proficiency`` is a raw stat value (not basis
    points), so the divisor is 100 rather than 10000.
    """
    prof = read_(stat_tag(Q_ANOMALY_PROF), "sum")
    return max_(0, min_(prod_(prof, 0.01), 10))


def anomaly_level_area_node() -> AnyNode:
    """``1 + (attacker_level - 1) / 59`` — Level 1 -> 1.0, Level 60 -> 2.0."""
    level = read_(stat_tag(Q_ATTACKER_LEVEL), "sum")
    # (level - 1) / 59 = level/59 - 1/59
    return sum_(1, prod_(sum_(level, -1), 1 / 59))


def anomaly_boost_area_node() -> AnyNode:
    """``1 + anomaly_dmg_bonus / 10000``.

    A pure sum read over :data:`Q_ANOMALY_DMG_BONUS` — this is the
    anomaly-specific parallel to ``boost_area_node``'s dmg_bonus term.
    """
    bonus = read_(stat_tag(Q_ANOMALY_DMG_BONUS), "sum")
    return sum_(1, prod_(bonus, _BP))


def anomaly_damage_node(
    atk_node: AnyNode,
    base_mult_bp: int,
    element: str,
) -> AnyNode:
    """Composite anomaly damage (per-proc, not multiplied by proc count).

    ``per_proc = base * boost * def * res * vulnerability * stun
                    * anomaly_prof * level * anomaly_boost``

    Anomaly damage cannot crit (the agent-specific anomaly-crit passives
    aren't modelled here). ``base_mult_bp`` comes from the anomaly's
    ``ANOMALY_BASE`` table (e.g. 50_000 bp = 500% ATK for Shatter).

    Multiplying by ``procs`` to reach ``total`` happens Python-side —
    no point putting a constant proc count in the graph.
    """
    return prod_(
        base_damage_node(atk_node, base_mult_bp),
        boost_area_node(element),
        def_area_node(),
        res_area_node(),
        vulnerability_area_node(),
        stun_area_node(),
        anomaly_proficiency_area_node(),
        anomaly_level_area_node(),
        anomaly_boost_area_node(),
    )


def luminize_damage_node(
    atk_node: AnyNode,
    effective_mult_bp: int,
    element: str,
    def_ignore_bp: int,
    constant_factor: float,
) -> AnyNode:
    """Composite Luminize damage for one stored Voidflare (Remielle, DESIGN §7.2).

    Deliberately **not** a parameterisation of :func:`anomaly_damage_node`, and
    the difference is the whole point of Task 36 (E-8, ``docs/LOG_remielle.md``).
    Luminize is computed in *Remielle's* context while its scaling stats come
    from the *teammate* whose Refringed anomaly was captured — so the two agents
    own different halves of the chain:

    ``per_instance = base(ATK, effective_mult) * BoostArea(DMG%)
                     * DEFArea(PEN, def_ignore) * AnomalyProfArea(AP)
                     * constant_factor``

    ATK, the element's DMG%, PEN and AP are read live from the registry — in the
    optimizer that registry is the *candidate* build's, which is exactly why a
    ``LuminizeStep`` cannot carry the simulation's frozen numbers: the optimizer
    simulates a disc-stripped DPS, so the frozen values are zero-disc values.

    Everything Remielle owns is candidate-invariant and folds into two baked
    constants:

    - ``constant_factor`` — ``RESArea * VulnArea * StunArea * LevelArea *
      AnomalyBoostArea``, precomputed from the simulation's ``AnomalyResult``.
    - ``def_ignore_bp`` — cannot fold, because DEFArea subtracts it from the
      *scored build's* PEN before a ratio. Passed through to
      :func:`def_area_node`'s override rather than read from the registry,
      which would return the scored agent's DEF-ignore instead of Remielle's.

    ``effective_mult_bp`` is ``luminize_mult_bp`` already folded with Remielle's
    live AP bonus (``AnomalyResult.effective_mult_bp``) — her AP feeds only that
    term, never ``AnomalyProfArea``, which is the captured teammate's (guide line
    104's naming trap; DESIGN §2 OQ-1).

    Always exactly one instance — there is no proc count to multiply by.
    """
    return prod_(
        base_damage_node(atk_node, effective_mult_bp),
        boost_area_node(element),
        def_area_node(def_ignore_bp),
        anomaly_proficiency_area_node(),
        constant_factor,
    )



def luminize_owner_scaled_node(
    frozen_damage: float,
    owner_base_mult_bp: int,
    owner_ap_bonus_bp: int,
    effective_mult_bp_at_stripped_ap: int,
    owner_boost_ratio: float = 1.0,
) -> AnyNode:
    """Luminize damage when the Lumiflux agent is herself the optimized DPS.

    The inverse of :func:`luminize_damage_node`'s ownership split, and the fix
    for P-F2 (hardening Task 15). There, the *teammate* half is read live from
    the registry and Remielle's half is baked. Here the teammate half is the
    baked one — the Voidflare was captured from a support, whose build the
    optimizer never strips, so ``frozen_damage`` is exact for that half — while
    Remielle's half must vary, because she is the build whose discs are being
    enumerated.

    Her half is purely multiplicative, so this rescales rather than recomputes::

        damage = frozen_damage
                 * (owner_base_mult_bp * (1 + owner_ap_bonus_bp * AP / 10000))
                 / effective_mult_bp_at_stripped_ap

    ``AP`` is the only live term, read from the registry, where the optimizer's
    per-candidate disc overlay has already registered it. The expression is
    linear in it — one read and a multiply-add per candidate, which is what
    keeps this inside the optimizer's O(1)-per-combination budget.

    ``effective_mult_bp_at_stripped_ap`` is the same fold already evaluated at
    her disc-stripped AP and folded into ``frozen_damage`` by the simulation, so
    dividing by it is exactly what takes the stale value back out. It is never
    zero in practice (a Luminize with a zero multiplier emits no event), but a
    zero would make the ratio undefined, so callers must not build this node for
    one.

    ``owner_boost_ratio`` corrects the *second* Remielle-owned term the
    simulation froze: her Attribute-Anomaly-DMG% (AnomalyBoostArea), which is
    baked inside ``constant_factor``. It is the live value over the frozen one,
    and unlike the AP fold it is **not** a per-candidate quantity — her
    Anomaly DMG% varies only with the disc SET distribution, which the optimizer
    already resolves once per frame. So it enters as a plain constant and the
    node stays linear in AP. ``1.0`` leaves the frozen value alone.

    Why this matters concretely: Feathered Fate's 4pc grants +15% Attribute
    Anomaly DMG, and the optimizer simulates a disc-stripped build — so without
    this the 4pc's effect on Luminize is invisible, and the optimizer
    under-values her signature set on the damage source that dominates her kit.
    """
    prof = read_(stat_tag(Q_ANOMALY_PROF), "sum")
    live_mult = prod_(owner_base_mult_bp, sum_(1.0, prod_(prof, owner_ap_bonus_bp / 10000)))
    scale = frozen_damage * owner_boost_ratio / effective_mult_bp_at_stripped_ap
    return prod_(live_mult, scale)


def refringe_credit_node(
    frozen_tick_damage: float,
    refringe_mult_at_stripped_ap: int,
    refringe_ap_ratio_bp: int,
    refringe_flat_bonus_bp: int,
) -> AnyNode:
    """The Lumiflux agent's attributable share of a TEAMMATE's anomaly tick (#160).

    Refringe multiplies the anomaly half of a teammate's damage and nothing
    else. That damage belongs to the teammate — but the *uplift* would not exist
    without the Lumiflux agent, and it scales with **her** Anomaly Proficiency,
    so it moves when her discs move. Scoring her build without it is what makes
    the optimizer sell AP to buy CRIT on an agent whose kit barely crits.

    Credits the uplift only, never the whole tick::

        neutral_tick = frozen_tick_damage * 10000 / refringe_mult_at_stripped_ap
        credit(AP)   = neutral_tick * (refringe_flat_bonus_bp
                                       + refringe_ap_ratio_bp * AP) / 10000

    ``frozen_tick_damage`` is the tick as the simulation computed it, which
    already has the simulation's Refringe multiplier baked in — dividing by
    ``refringe_mult_at_stripped_ap`` takes that stale value back out, exactly as
    :func:`luminize_owner_scaled_node` divides out ``effective_mult_bp``. The
    teammate's own half needs no rescaling: the optimizer never strips a
    support's build, so every term the tick scales off is already exact.

    ``AP`` is the only live term, read from the registry where the per-candidate
    disc overlay has already registered it. ``refringe_coefficient`` is
    *exactly* linear in AP (``ap * ratio_bp + flat_bp``, no floor division), so
    this is one read and a multiply-add per candidate — the same O(1) budget
    :func:`luminize_owner_scaled_node` is built to.

    ``refringe_mult_at_stripped_ap`` is never zero in practice: it is
    ``10000 + coefficient_bp`` and the credit is only emitted when Refringe
    actually fired, so it exceeds 10000. Callers must not build this node for a
    tick that carries the neutral multiplier — there is no uplift to attribute.
    """
    prof = read_(stat_tag(Q_ANOMALY_PROF), "sum")
    live_coefficient_bp = sum_(
        float(refringe_flat_bonus_bp), prod_(prof, float(refringe_ap_ratio_bp))
    )
    neutral_tick = frozen_tick_damage * 10000 / refringe_mult_at_stripped_ap
    return prod_(live_coefficient_bp, neutral_tick / 10000)


def abloom_rescaled_node(
    frozen_abloom_damage: float,
    frozen_ap: int,
    ap_scaled: bool,
) -> AnyNode:
    """An Abloom instance the scored build owns, re-scaled to its live AP (#163).

    Abloom fractions an already-resolved anomaly::

        total = original_anomaly_dmg * abloom_mv_bp * ap / 100000 * abloom_boost

    Two agents own the inputs, exactly as they do for Luminize (E-8):
    ``original_anomaly_dmg`` belongs to whoever applied the aura
    (``applier_agent_id``), while ``ap`` is the *acting* agent's — the one the
    event is emitted against, and the one `_owns` already attributes it to
    (``anomaly_simulator.py:683``, ``detail["ap"] = ctx.stats.anomaly_proficiency``).

    So only the AP term is live for the scored build, and the expression is
    linear in it: one read and a multiply, the same budget as
    :func:`refringe_credit_node`.

    ``ap_scaled`` False (Grace, Burnice — kits whose text quotes a fixed
    percentage) removes ``ap`` from the formula entirely, which makes the whole
    instance a constant. Returned as such rather than special-cased at the call
    site, so the caller does not have to know which kits scale.

    **Deliberate under-credit when the scored build applied the aura itself.**
    ``original_anomaly_dmg`` stays frozen either way. That is exact when a
    teammate applied it — the optimizer never strips a support — and an
    under-credit when the scored build did, since its own anomaly would also grow
    with its discs. Rebuilding that half needs the aura's full anomaly context,
    which the event does not carry; an under-credit is the safe direction, and it
    is strictly better than the 100% under-credit of scoring abloom as zero.
    """
    if not ap_scaled or frozen_ap <= 0:
        return sum_(float(frozen_abloom_damage))
    prof = read_(stat_tag(Q_ANOMALY_PROF), "sum")
    return prod_(prof, frozen_abloom_damage / frozen_ap)


def squad_atk_credit_node(
    atk_node: AnyNode,
    frozen_teammate_damage: float,
    teammate_atk_at_sim: int,
    grant_rows: tuple[tuple[int, int], ...],
) -> AnyNode:
    """The scored build's attributable share of a teammate's ATK-scaled damage (#160).

    Remielle's Additional Ability grants the squad flat ATK scaled off **her**
    ATK and capped (rows 0-2: ``atk_scale_ratio`` 600/600/2800, caps 240/240/1120).
    That is her build moving a teammate's damage, so it belongs to her build's
    score — and like the Refringe uplift, it is invisible today because `_owns`
    drops the teammate's damage whole.

    The design classified this as needing a teammate-snapshot rebuild. It does
    not, because **damage is linear in ATK** — ``base_damage(stat, mv) =
    floor(stat * mv / 10000)``, and standard and anomaly paths both route through
    it. So a teammate's damage is proportional to their total ATK::

        grant(ATK) = Σ over rows of  min(cap_i, ratio_i * ATK / 10000)
        credit     = frozen_teammate_damage * grant(ATK) / teammate_atk_at_sim

    ``grant_rows`` is ``((cap, ratio), …)`` for the rows active on this team —
    condition gating (``anomaly_count_3_in_team`` etc.) is resolved by the caller,
    not here, so this node stays a pure function of ATK.

    The per-row cap makes this **piecewise**-linear rather than linear, which was
    the stated reason for rejecting a closed form. It is not an obstacle: the DAG
    already builds that shape (``min_``/``max_`` in :func:`crit_area_node` and
    :func:`res_area_node`), and piecewise-linear is still one node evaluation per
    candidate — inside the same O(1)-per-combination budget as
    :func:`refringe_credit_node`.

    **Caller responsibility that Refringe did not have.** Refringe multiplies the
    anomaly half of the split and nothing else, so its uplift is unambiguous. An
    ATK grant reaches every damage instance the teammate deals, so the caller must
    emit one credit per teammate damage event **and must exclude instances whose
    scaling stat is not ATK** — Sheer damage reads SheerForce
    (``DamageResult.is_sheer``), and HP-scaled kits exist. Crediting those would
    scale something the grant never touched.

    ``teammate_atk_at_sim`` is that teammate's total ATK as the simulation
    resolved it, i.e. already including whatever grant the target's *disc-stripped*
    build produced. Dividing by it is what takes the stale value out, exactly as
    :func:`refringe_credit_node` divides out its stripped-AP multiplier. Never
    zero in practice — a build with no ATK deals no damage, and the caller only
    emits this for events carrying damage.
    """
    grant = sum_(
        *[min_(float(cap), prod_(atk_node, float(ratio) / 10000)) for cap, ratio in grant_rows]
    )
    return prod_(grant, frozen_teammate_damage / teammate_atk_at_sim)


# ---- Buildup, Disorder, and Vortex DAG Nodes ---------------------------------


def buildup_node(
    move_buildup: AnyNode | float | int,
    element: str,
) -> AnyNode:
    """Calculate buildup points applied to enemy gauge per hit in DAG.

    buildup = move_buildup * (1 + anomaly_buildup_bonus/10000)
              * (anomaly_mastery/100) * (1 - enemy_anomaly_res/10000)
              * (stun_buildup_multiplier/10000 if is_stunned else 1.0)

    anomaly_mastery = agent_base_am * (1 + am_pct/10000) + anomaly_mastery_flat,
    mirroring stat_calculator.compute_total_stats — % AM bonuses (Vivian M2,
    disc sets) apply to the base stat only, flat AM adds after.
    """
    base = const(move_buildup) if isinstance(move_buildup, (int, float)) else move_buildup

    # Anomaly buildup bonus: generic + element-specific
    generic_buildup = read_(stat_tag(Q_ANOMALY_BUILDUP), "sum")
    elemental_buildup = read_(stat_tag(f"{element}_anomaly_buildup"), "sum")
    buildup_bonus_area = sum_(1, prod_(sum_(generic_buildup, elemental_buildup), _BP))

    # Anomaly Mastery: base_am * (1 + am_pct) + flat accumulator, /100 for the area
    base_am = read_(stat_tag(Q_AGENT_BASE_AM), "sum")
    am_pct = read_(stat_tag(Q_AM_PCT), "sum")
    am_flat = read_(stat_tag(Q_ANOMALY_MASTERY), "sum")
    mastery = sum_(prod_(base_am, sum_(1, prod_(am_pct, _BP))), am_flat)
    mastery_area = prod_(mastery, 0.01)

    # Enemy Anomaly RES: 1 - res/10000
    enemy_anomaly_res = read_(Tag.of(**{Q: Q_ENEMY_ANOMALY_RES, ELEM: element}), "sum")
    res_area = sum_(1, prod_(enemy_anomaly_res, -_BP))

    # Stun buildup factor: 1 + stun_buildup_bonus/10000
    stun_buildup_bonus = read_(stat_tag(Q_STUN_BUILDUP_BONUS), "sum")
    stun_area = sum_(1, prod_(stun_buildup_bonus, _BP))

    return prod_(
        base,
        buildup_bonus_area,
        mastery_area,
        res_area,
        stun_area,
    )


def disorder_boost_area_node() -> AnyNode:
    """``1 + disorder_dmg_bonus / 10000``."""
    bonus = read_(stat_tag(Q_DISORDER_DMG_BONUS), "sum")
    return sum_(1, prod_(bonus, _BP))


def disorder_mv_node(
    anomaly_type: str | AnomalyType,
    t_node: AnyNode,
    additional_mv_node: AnyNode,
) -> AnyNode:
    """Calculate disorder move value node based on anomaly type.

    Mirrors :func:`app.services.damage_calculator.calculate_disorder_damage`:
    Burn and Corruption tick-quantize to 0.5s boundaries (Leifa's ``[t / 0.5]``
    bracket = floor); Shock, Ice-Freeze (Shatter), and Assault are continuous
    in ``t`` (see F-03 / F-24 in RESEARCH_math_review.md).
    """
    from app.services.damage_calculator import AnomalyType  # noqa: PLC0415

    # If it is a string representation of the enum, resolve it
    if isinstance(anomaly_type, str):
        with contextlib.suppress(ValueError):
            anomaly_type = AnomalyType(anomaly_type)

    if anomaly_type in (AnomalyType.BURN, AnomalyType.CORRUPTION):
        # Tick-quantized to 0.5s boundaries (Leifa's [t/0.5] bracket = floor).
        tick_rate = 5000 if anomaly_type == AnomalyType.BURN else 6250
        ticks = custom("floor", prod_(t_node, 2.0))
        return sum_(45000, additional_mv_node, prod_(ticks, tick_rate))
    if anomaly_type == AnomalyType.SHOCK:
        return sum_(45000, additional_mv_node, prod_(t_node, 12500))
    if anomaly_type == AnomalyType.SHATTER:
        # Ice-Freeze: 450% + t*7.5% (Leifa). 600% (Frost-Freeze's base) was
        # wrongly paired with Ice's slope here — F-24.
        return sum_(45000, additional_mv_node, prod_(t_node, 750))
    if anomaly_type == AnomalyType.ASSAULT:
        return sum_(45000, additional_mv_node, prod_(t_node, 750))
    if anomaly_type == AnomalyType.WINDSWEPT:
        return sum_(10000, additional_mv_node)
    return sum_(45000, additional_mv_node)


def disorder_damage_node(
    atk_node: AnyNode,
    anomaly_type: str | AnomalyType,
    element: str,
) -> AnyNode:
    """Composite disorder damage.

    Disorder DMG = BaseDMG(using ATK and Disorder MV) * BoostArea * DEFArea * RESArea
                   * VulnerabilityArea * StunArea
                   * AnomalyProfArea * LevelArea * AnomalyBoostArea * DisorderBoostArea

    BaseDMG = (ATK * MV) * (1 + base_dmg_bonus_pct) + flat_base_dmg — the
    Yanagi Polarity Disorder hooks (mirrors
    :func:`app.services.damage_calculator.calculate_disorder_damage`).
    """
    remaining_duration = read_(stat_tag(Q_REMAINING_DURATION), "sum")
    max_duration = read_(stat_tag(Q_MAX_DURATION), "sum")
    additional_mv = read_(stat_tag(Q_ADDITIONAL_MV), "sum")
    base_dmg_bonus_pct = read_(stat_tag(Q_BASE_DMG_BONUS_PCT), "sum")
    flat_base_dmg = read_(stat_tag(Q_FLAT_BASE_DMG), "sum")

    # Clamped remaining duration t
    t = max_(0, min_(max_duration, remaining_duration))

    # Base MV node
    mv = disorder_mv_node(anomaly_type, t, additional_mv)

    # Base damage node: atk_node * mv / 10000 * (1 + base_dmg_bonus_pct) + flat_base_dmg
    base = prod_(atk_node, mv, _BP)
    base = sum_(prod_(base, sum_(1, prod_(base_dmg_bonus_pct, _BP))), flat_base_dmg)

    return prod_(
        base,
        boost_area_node(element),
        def_area_node(),
        res_area_node(),
        vulnerability_area_node(),
        stun_area_node(),
        anomaly_proficiency_area_node(),
        anomaly_level_area_node(),
        anomaly_boost_area_node(),
        disorder_boost_area_node(),
    )


def vortex_boost_area_node() -> AnyNode:
    """``1 + vortex_dmg_bonus / 10000``."""
    bonus = read_(stat_tag(Q_VORTEX_DMG_BONUS), "sum")
    return sum_(1, prod_(bonus, _BP))


def vortex_mv_node(
    vortex_kind: str,
    t_node: AnyNode,
    additional_mv_node: AnyNode,
) -> AnyNode:
    """Calculate vortex move value node based on vortex kind."""
    if vortex_kind == "burn":
        return sum_(90000, additional_mv_node, prod_(t_node, 10000))
    if vortex_kind in ("shock", "corruption"):
        return sum_(65000, additional_mv_node, prod_(t_node, 12500))
    if vortex_kind == "ice_freeze":
        return sum_(130000, additional_mv_node, prod_(t_node, 750))
    if vortex_kind == "frost_freeze":
        return sum_(additional_mv_node, prod_(t_node, 7500))
    if vortex_kind == "assault":
        return sum_(65000, additional_mv_node, prod_(t_node, 750))
    return sum_(65000, additional_mv_node)


def vortex_damage_node(
    atk_node: AnyNode,
    vortex_kind: str,
    element: str,
) -> AnyNode:
    """Composite vortex damage.

    Vortex DMG = BaseDMG(using ATK and Vortex MV) * BoostArea * DEFArea * RESArea
                 * VulnerabilityArea * StunArea
                 * AnomalyProfArea * LevelArea * AnomalyBoostArea * VortexBoostArea
    """
    remaining_duration = read_(stat_tag(Q_REMAINING_DURATION), "sum")
    max_duration = read_(stat_tag(Q_MAX_DURATION), "sum")
    additional_mv = read_(stat_tag(Q_ADDITIONAL_MV), "sum")

    # Clamped remaining duration t
    t = max_(0, min_(max_duration, remaining_duration))

    # Base MV node
    mv = vortex_mv_node(vortex_kind, t, additional_mv)

    # Base damage node: atk_node * mv / 10000
    base = prod_(atk_node, mv, _BP)

    return prod_(
        base,
        boost_area_node(element),
        def_area_node(),
        res_area_node(),
        vulnerability_area_node(),
        stun_area_node(),
        anomaly_proficiency_area_node(),
        anomaly_level_area_node(),
        anomaly_boost_area_node(),
        vortex_boost_area_node(),
    )
