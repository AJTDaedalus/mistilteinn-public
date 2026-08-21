"""Disc optimizer (Phase 6.3a MVP) — pure-function exhaustive search.

Given a user inventory of :class:`DiscCandidate` instances, a base
``BuildSnapshot`` (agent + W-Engine + kit modifiers, *without* disc
stats or disc-set modifiers), and a combo to score against, this
returns the top-N disc assignments by DAG-computed combo total.

Search strategy (MVP):
    1. Bucket inventory by slot.
    2. Apply locked-slot constraints (reduce any locked slot to a single option).
    3. Enumerate the Cartesian product across slots 1-6.
    4. For each combination, check required-set piece-count constraints.
    5. Build a snapshot with per-combo disc stats + applicable 2pc/4pc
       set modifiers, score via the disc-overlay fast path, push into a
       min-heap keyed by ``-total_damage`` to keep the top-N.

Scope notes:
    * Exhaustive product is fine for unit-test-sized inventories. Real-world
      inventories (hundreds of discs) need Phase 6.3c's set-partition
      search + stat-bound pruning.
    * Substats are treated as fixed values on the candidate — reroll
      probability modelling lives in the disc scorer (Phase 7).
    * ``conditions`` applies uniformly across the combo (no rotation timing).
"""

from __future__ import annotations

import heapq
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, fields, replace
from itertools import permutations, product
from typing import TYPE_CHECKING

from app.formula.zzz.tags import ELEMENTS
from app.schemas.optimizer import BuildStatsSummary
from app.services.am_variants import resolve_coarse_am_from_counts
from app.services.build_damage_service import resolve_build_stats
from app.services.combo_types import (
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
from app.services.damage_calculator import CritMode
from app.services.damage_dag_service import (
    AnomalyDAGStepContext,
    DamageDAGStepContext,
    LuminizeDAGStepContext,
    build_abloom_context,
    build_anomaly_step_context,
    build_damage_step_context,
    build_luminize_owner_scaled_context,
    build_luminize_step_context,
    build_refringe_credit_context,
    build_squad_atk_credit_context,
    compute_anomaly_with_accumulated_disc,
    compute_damage_with_accumulated_disc,
    compute_luminize_with_accumulated_disc,
)
from app.services.modifiers import AttackScope
from app.services.snapshot_builder import applicable_set_modifiers
from app.services.stat_calculator import DiscStats, accumulate_disc_stats

if TYPE_CHECKING:
    from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
    from app.services.combo_types import Step
    from app.services.modifiers import ActiveConditions, Modifier
    from app.services.stat_calculator import TotalStats

# Step kinds for the weighted-context discriminator. Small ints rather than a
# str/Enum: this is the innermost scoring loop and the compare runs per step per
# candidate. Was a bare ``is_standard: bool`` until Luminize needed a third and
# fourth case (Task 36 / E-8, docs/LOG_remielle.md).
_KIND_STANDARD = 0
_KIND_ANOMALY = 1
_KIND_LUMINIZE = 2  # ctx is a LuminizeDAGStepContext — rescored per candidate
_KIND_LUMINIZE_CONST = 3  # ctx is a float — a support-captured Voidflare's exact damage
# ctx is a LuminizeDAGStepContext whose node rescales a frozen teammate half by
# the Lumiflux agent's OWN live AP — she is the optimized DPS (P-F2, Task 15).
_KIND_LUMINIZE_OWNER = 4
# #160: the scored build's attributable slice of a TEAMMATE's anomaly tick.
# ctx is a LuminizeDAGStepContext — same shape (one node, AP the only live
# term), so it rides the same overlay helpers.
_KIND_REFRINGE_CREDIT = 5
# #160 A4: the same shape for the OTHER stat-driven team buff -- her ATK
# grant to the squad. Live term is total ATK rather than AP.
_KIND_SQUAD_ATK_CREDIT = 6
# #163: an Abloom instance, rescaled to the scored build's live AP.
_KIND_ABLOOM = 7

# Weighted step context: (count, kind, is_ex, ctx).
# Consolidation collapses steps sharing a signature into one entry with count > 1.
# The scoring inner loop multiplies compute_*(ctx, disc) by count — exact for linear sums.
# ``is_ex`` flags EX-Special standard steps so energy gating can credit them separately.
_WeightedStepCtx = tuple[
    int,
    int,
    bool,
    DamageDAGStepContext | AnomalyDAGStepContext | LuminizeDAGStepContext | float,
]

# Step signature: all fields that produce byte-identical DAG contexts under a given frame.
# Ordering contract (forward-compat for timed buffs): consolidation runs on fully-resolved
# per-step contexts as the LAST transform before the scoring loop — downstream of timeline
# rendering. Buff magnitude (disc-dependent) stays OUT; membership/window state goes IN.
# Today conditions and is_stunned are uniform across the combo (disc_optimizer.py invariant),
# so all steps share _cond_key → maximum consolidation. When per-step conditions arrive they
# annotate the resolved context before grouping; this signature structure is unchanged.
_StepSig = tuple[
    int,  # one of the _KIND_* constants above
    object,  # scope (ComboStep) | anomaly_type (AnomalyStep) | voidflare_element (Luminize)
    object,  # multiplier bp | procs_override | (effective_mult_bp, def_ignore, factor)
    bool,  # in_stun (per-step; today equals the uniform is_stunned arg)
    frozenset,  # frozenset(conditions.active)
    frozenset,  # frozenset(conditions.stack_counts.items())
    None,  # buff_window_state (always None today; future: timed-buff window id)
]


_ALL_SLOTS = (1, 2, 3, 4, 5, 6)
_SLOT_COUNT = 6
_MIN_2PC = 2
_MIN_4PC = 4

# Progress/cancellation cadence (Task 2, G2+G3). The scoring loop emits a progress
# snapshot — and thereby lets the callback raise OptimizerCancelled — every
# PROGRESS_TICK_EVERY combos considered OR every PROGRESS_TICK_SECONDS of wall clock,
# whichever comes first. This decouples progress/cancel latency from the slot-1 chunk
# size, so a single huge slot-1 chunk (e.g. a locked slot 1) stays visible and stoppable.
PROGRESS_TICK_EVERY: int = 256
PROGRESS_TICK_SECONDS: float = 2.0

# Auto-prefilter tuning (P1a). PREFILTER_EXACT is a sentinel value for prefilter_top_k
# that forces exact exhaustive search, bypassing auto-K selection.
PREFILTER_EXACT: int = -1

# Time-denominated combo budget (Task 6c). Per-combo cost is proportional to n_ctx — the
# number of unique weighted step contexts the hot loop iterates (Σ over step lists of
# len(unique contexts) from _build_frame_contexts) — not raw combo/step length. RATE_CTX
# and RATE_CTX_OVERHEAD_S are the CP7 fit (docs/LOG_optimizer_granularity.md, Task 6b):
# time/combo ≈ RATE_CTX_OVERHEAD_S + n_ctx / RATE_CTX (R²=0.9999 on the overlay fast path).
# Wall-clock target raised 90s -> 300s (5 min) per user direction (2026-07-03, Task 7
# follow-up) — not a re-measurement of CP7's rate, just a wider time budget.
COMBO_BUDGET_TIME_S: float = 300.0
RATE_CTX: float = 4213.0
RATE_CTX_OVERHEAD_S: float = 51.3e-6
# Deprecated derived alias (n_ctx=1 case) for pre-6c call sites/tests that pinned a raw
# combo-count budget. New code should go through _effective_combo_budget(n_ctx) instead.
COMBO_BUDGET: int = int(COMBO_BUDGET_TIME_S / (RATE_CTX_OVERHEAD_S + 1.0 / RATE_CTX))
UNION_STAT_KEEP: int = 3   # top-m per synergy stat added to the union (P1b)
UNION_PRODUCT_CAP: float = 1.5  # max post-union estimate as a multiple of COMBO_BUDGET
# Element DMG% stat fields eligible for the union keep (Task 5d) — derived from
# the canonical ELEMENTS list (F-26); agent_element values outside this set are
# treated as unknown.
_ELEMENT_DMG_FIELDS = {f"{element}_dmg" for element in ELEMENTS}
# "base" = score against bare base build (legacy); "full" = F-a (full-build baseline) +
# F-b (per-set_id context). Flipped to "full" after CP3+CP4 passed on real data (Task 6b) —
# CP6 showed "base"'s union tie-breaking misses discs F-a would correctly retain (see
# docs/LOG_optimizer_granularity.md, Task 6b entry). "base" stays selectable for A/B.
PREFILTER_BASELINE: str = "full"

# Dimensions of the Pareto-dominance comparison (Task 5e, P1d) — every DiscStats field
# except set_bonuses (a list, not a scalar; discs carry no chained bonuses of their own).
# All of these are weakly monotone in damage across every damage path (standard, anomaly,
# sheer) in this codebase, which is what makes dropping a dominated disc lossless.
_PARETO_STAT_FIELDS: tuple[str, ...] = tuple(
    f.name for f in fields(DiscStats) if f.name != "set_bonuses"
)


@dataclass(frozen=True)
class OptimizerProgress:
    """Snapshot pushed to the progress callback at each set-assignment boundary."""

    assignments_done: int
    assignments_total: int
    evaluated: int
    pruned_sets: int
    pruned_stats: int
    elapsed_seconds: float


class OptimizerCancelled(Exception):  # noqa: N818
    """Cooperative cancellation signal raised by the progress callback."""


ProgressCallback = Callable[[OptimizerProgress], None]


@dataclass(frozen=True)
class SetFrame:
    """A declared set-count distribution over the six disc slots.

    ``counts`` maps ``set_id → piece_count`` and must sum to 6. When a
    list of frames is passed via :class:`OptimizerConstraints.allowed_frames`,
    the optimizer enumerates only slot-to-set assignments matching a
    declared frame instead of the full Cartesian product. This is the
    standard pruning trick for real-world ZZZ inventories, where users
    typically know which set distributions they'd accept (e.g. a 4pc
    damage set paired with a 2pc stat set).
    """

    counts: dict[int, int]

    def __post_init__(self) -> None:
        total = sum(self.counts.values())
        if total != _SLOT_COUNT:
            msg = f"SetFrame counts must sum to 6, got {total}: {self.counts}"
            raise ValueError(msg)


@dataclass(frozen=True)
class DiscCandidate:
    """One concrete disc from user inventory, ready for the optimizer.

    Stats match the schema :func:`accumulate_disc_stats` consumes:
    ``main_stat_type`` is one of the keys in its ``stat_map``, and each
    substat is ``{"stat": <type>, "value": <basis_points>}``.
    """

    disc_id: str
    slot: int  # 1-6
    set_id: int  # hakushin disc_set id (for 2pc/4pc matching)
    main_stat_type: str = ""
    main_stat_value: int = 0
    substats: list[dict] = field(default_factory=list)

    def to_stat_dict(self) -> dict:
        """Convert to the dict shape `accumulate_disc_stats` expects, for stat resolution."""
        return {
            "main_stat_type": self.main_stat_type,
            "main_stat_value": self.main_stat_value,
            "substats": self.substats,
        }


@dataclass(frozen=True)
class OptimizerConstraints:
    """Search constraints.

    ``locked_slots``: ``{slot: disc_id}`` forces a specific candidate.
    ``required_sets``: ``{set_id: min_pieces}`` rejects combos below the count.
    ``min_stats``: ``{TotalStats field: min_value}`` — combos whose resolved
        stats fall below any floor are skipped before DAG evaluation. Keys
        match :class:`TotalStats` field names (e.g. ``crit_rate``, ``crit_dmg``,
        ``atk``, ``anomaly_proficiency``, ``pen_ratio``). Values are basis
        points for percentages, absolute for flats — matching the field's
        unit. Unknown keys raise ``KeyError`` at evaluation time.
    ``allowed_frames``: optional list of :class:`SetFrame`. When set, the
        optimizer only evaluates combos whose set-count distribution
        matches one of the declared frames (e.g. ``[{1: 4, 2: 2}]``).
        Default ``None`` triggers exhaustive Cartesian search. Frames that
        fail ``required_sets`` are skipped and counted in ``pruned_sets``.
    ``top_n``: how many ranked builds to return.
    ``prefilter_top_k``: optional heuristic accelerator. When set, each
        ``(slot, set_id)`` bucket is reduced to its top-K candidates by a
        cheap solo marginal-damage score before enumeration. ``None``
        (default) keeps exhaustive search. ``K >= group size`` is exact
        (no candidate dropped). See DESIGN_optimizer_er_cleanup.md for the
        soundness argument — grouping by set preserves set formation, and
        when energy gating is active the highest-ER disc per group is kept.
    ``rotation_energy_cost``: optional total Energy the rotation's EX-Special
        casts require. When set (and > 0), each build's ``total_damage``
        credits EX damage by an energy-feasibility factor derived from the
        build's ER (base + disc) over ``rotation_duration_s``. ``None``
        (default) sums all EX damage unconditionally (current behavior).
    ``rotation_duration_s``: wall-clock seconds over which passive energy
        regen accrues; only used when ``rotation_energy_cost`` is set.
    """

    locked_slots: dict[int, str] = field(default_factory=dict)
    required_sets: dict[int, int] = field(default_factory=dict)
    min_stats: dict[str, int] = field(default_factory=dict)
    allowed_frames: list[SetFrame] | None = None
    top_n: int = 10
    prefilter_top_k: int | None = None
    rotation_energy_cost: float | None = None
    rotation_duration_s: float = 0.0


@dataclass(frozen=True)
class OptimizerBuildResult:
    """One candidate build the optimizer produced."""

    total_damage: float
    disc_ids: list[str]  # ordered by slot 1..6
    set_counts: dict[int, int]
    snapshot: BuildSnapshot
    total_stats: BuildStatsSummary = field(default_factory=BuildStatsSummary)
    per_combo_damage: tuple[float, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OptimizerResult:
    """Top-N results plus search diagnostics."""

    builds: list[OptimizerBuildResult]
    evaluated: int  # combinations scored (passed pruning)
    pruned_sets: int  # combinations rejected by required-set constraints
    pruned_stats: int  # combinations rejected by min_stats floor
    prefiltered: int = 0  # inventory candidates removed by prefilter_top_k
    auto_prefilter_k: int | None = None  # K_dmg used when budget auto-K fired; None otherwise
    pareto_removed: int = 0  # inventory candidates removed by the lossless Pareto layer (P1d)


def _build_ref_disc_stats(slot_candidates: dict[int, list[DiscCandidate]]) -> list[dict]:
    """Build one pseudo-disc dict representing the average contribution of 5 discs.

    Averages raw stat values (main + substat) across all discs in all slots, then
    scales by 5/N so that accumulate_disc_stats([result]) equals the expected disc-stat
    contribution of five average inventory discs.  Used by PREFILTER_BASELINE="full"
    (P1c F-a) to shift the scoring baseline to a realistic operating point.
    """
    raw_sums: dict[str, float] = {}
    total = 0
    for slot in _ALL_SLOTS:
        for d in slot_candidates[slot]:
            total += 1
            if d.main_stat_type:
                raw_sums[d.main_stat_type] = (
                    raw_sums.get(d.main_stat_type, 0.0) + d.main_stat_value
                )
            for sub in d.substats:
                key = sub.get("stat", "")
                if key:
                    raw_sums[key] = raw_sums.get(key, 0.0) + sub.get("value", 0)
    if not total:
        return []
    scale = 5.0 / total
    substats = [
        {"stat": k, "value": int(v * scale)} for k, v in raw_sums.items() if v > 0 and k
    ]
    return [{"main_stat_type": "", "main_stat_value": 0, "substats": substats}]


def optimize_discs(  # noqa: PLR0912, PLR0915
    *,
    base_build: BuildSnapshot,
    enemy: EnemySnapshot,
    combo_steps: list[Step],
    combo_steps_set: list[list[Step]] | None = None,
    event_log_by_am: dict[int, list[Step]] | None = None,
    am_2pc_sets: dict[int, list[Modifier]] | None = None,
    inventory: list[DiscCandidate],
    disc_set_modifiers: dict[int, list[Modifier]],
    constraints: OptimizerConstraints,
    conditions: ActiveConditions,
    crit_mode: CritMode = CritMode.EXPECTED,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    progress_callback: ProgressCallback | None = None,
    fluxed_element: str | None = None,
) -> OptimizerResult:
    """Enumerate disc assignments from inventory and return the top-N.

    ``base_build`` is the **scorer's** disc-stripped snapshot — supports folded
    in (``SnapshotSplit.scoring_base``, issue #121). This function re-scores
    every candidate against it, so a support's team buff has no other route into
    an optimizer score. Do not pass the simulator's ``sim_base``.

    ``fluxed_element``: the resolved Attribute Flux target (DESIGN_remielle.md
    §5.3/Task 8), used *only* to pick which ``<element>_dmg`` disc stat the
    top-K prefilter's synergy-stat union keeps alongside the damage-ranked
    top-K (see ``_prefilter``). ``None`` (the default, and the only sensible
    value for a non-Lumiflux build) falls back to ``base_build.agent_element``
    — byte-identical to the pre-Task-8 behavior. Passing the fluxed element
    for a Lumiflux build is what makes the union keep the discs that actually
    matter (e.g. ``physical_dmg`` for a Physical-fluxed Remielle) instead of
    silently unioning nothing, since ``lumiflux_dmg`` is never a real stat
    bucket (DESIGN §4.2).

    Fast path (F1+F2+F4): step contexts are pre-built once per unique
    set-modifier configuration (once per SetFrame in the frames path,
    or once per unique set distribution in the exhaustive path). The
    per-combo hot loop calls the disc-overlay primitives from
    :mod:`damage_dag_service` instead of re-running :func:`_build_registry`.

    When ``combo_steps_set`` is provided it takes precedence over
    ``combo_steps``. Each step list is evaluated; ``total_damage`` is the
    max across them and per-list damages are recorded in
    ``OptimizerBuildResult.per_combo_damage`` (positionally aligned).
    """
    # event_log_by_am (dict sentinel) takes precedence; fall back to combo_steps_set or single.
    if event_log_by_am is not None:
        am_value_order: list[int] = list(event_log_by_am.keys())
        all_step_lists: list[list[Step]] = list(event_log_by_am.values())
    elif combo_steps_set is not None:
        am_value_order = []
        all_step_lists = combo_steps_set
    else:
        am_value_order = []
        all_step_lists = [combo_steps]
    am_value_to_idx: dict[int, int] = {v: i for i, v in enumerate(am_value_order)}

    slot_candidates = _bucket_by_slot(inventory, constraints.locked_slots)
    if any(not slot_candidates[s] for s in _ALL_SLOTS):
        return OptimizerResult(builds=[], evaluated=0, pruned_sets=0, pruned_stats=0)

    # Conditions key: hashable representation for the signature (uniform across the combo).
    _cond_key: tuple[frozenset, frozenset] = (
        frozenset(conditions.active),
        frozenset(conditions.stack_counts.items()),
    )

    # Energy gating: credit EX damage by a feasibility factor derived from the build's ER.
    # Mirrors anomaly_simulator's passive-regen formula (base_regen/100 * er_mult * seconds).
    _gating = (
        constraints.rotation_energy_cost is not None and constraints.rotation_energy_cost > 0
    )

    def _energy_feasibility(disc_energy_regen: int) -> float:
        er_mult = 1.0 + (base_build.agent_energy_regen + disc_energy_regen) / 10_000.0
        energy_gen = (
            base_build.agent_base_energy_regen / 100.0
        ) * er_mult * constraints.rotation_duration_s
        return min(1.0, energy_gen / constraints.rotation_energy_cost)  # type: ignore[operator]

    def _build_frame_contexts(  # noqa: PLR0912, PLR0915 — one branch per step kind;
        # splitting the dispatch would separate each kind's signature from its
        # context build, which is the pairing the step-dispatch coverage test relies on.
        frame_set_mods: list[Modifier],
    ) -> tuple[BuildSnapshot, list[list[_WeightedStepCtx]]]:
        """Pre-build consolidated weighted step contexts for a given set of set modifiers.

        Groups steps sharing the same signature into a single weighted entry — exact for
        linear damage sums. One ctx per unique signature; inner loop becomes
        ``total += count * compute_*(ctx, disc)``.
        """
        frame_snap = replace(
            base_build,
            disc_stats=[],
            modifiers=[*base_build.modifiers, *frame_set_mods],
        )
        per_list: list[list[_WeightedStepCtx]] = []
        for steps in all_step_lists:
            # sig -> (kind, is_ex, ctx) map; preserves first-seen insertion order.
            sig_to_ctx: dict[_StepSig, tuple[int, bool, object]] = {}
            sig_counts: Counter[_StepSig] = Counter()

            for step in steps:
                if isinstance(step, ComboStep):
                    sig: _StepSig = (
                        _KIND_STANDARD,
                        (step.scope, step.off_field),
                        step.multiplier,
                        is_stunned,
                        *_cond_key,
                        None,
                    )
                    sig_counts[sig] += 1
                    if sig not in sig_to_ctx:
                        ctx = build_damage_step_context(
                            build=frame_snap,
                            enemy=enemy,
                            multiplier=step.multiplier,
                            conditions=conditions,
                            attack_scope=step.scope,
                            crit_mode=crit_mode,
                            is_stunned=is_stunned,
                            stun_dmg_mult=stun_dmg_mult,
                            include_active=not step.off_field,
                        )
                        sig_to_ctx[sig] = (
                            _KIND_STANDARD,
                            step.scope == AttackScope.EX_SPECIAL,
                            ctx,
                        )
                elif isinstance(step, AnomalyStep):
                    sig = (
                        _KIND_ANOMALY,
                        step.anomaly_type,
                        step.procs_override,
                        is_stunned,
                        *_cond_key,
                        None,
                    )
                    sig_counts[sig] += 1
                    if sig not in sig_to_ctx:
                        ctx = build_anomaly_step_context(
                            build=frame_snap,
                            enemy=enemy,
                            anomaly_type=step.anomaly_type,
                            conditions=conditions,
                            procs=step.procs_override,
                            is_stunned=is_stunned,
                            stun_dmg_mult=stun_dmg_mult,
                        )
                        sig_to_ctx[sig] = (_KIND_ANOMALY, False, ctx)
                elif isinstance(step, LuminizeStep):
                    # Task 36 (E-8). A support-captured Voidflare froze a build
                    # the optimizer never strips and never varies, so its damage
                    # is exact and rides as a constant. A DPS-captured one froze
                    # a *disc-stripped* build, so every term it scales off has to
                    # be rebuilt against each candidate.
                    if step.is_owner_scaled:
                        # P-F2: frozen teammate half, live Remielle half. The
                        # signature keys on the rescale inputs, so two steps
                        # that differ only in those cannot share a context.
                        sig = (
                            _KIND_LUMINIZE_OWNER,
                            None,
                            (
                                step.frozen_damage,
                                step.owner_base_mult_bp,
                                step.owner_ap_bonus_bp,
                                step.effective_mult_bp,
                                step.owner_anomaly_boost_mult,
                            ),
                            is_stunned,
                            *_cond_key,
                            None,
                        )
                        sig_counts[sig] += 1
                        if sig not in sig_to_ctx:
                            sig_to_ctx[sig] = (
                                _KIND_LUMINIZE_OWNER,
                                False,
                                build_luminize_owner_scaled_context(
                                    build=frame_snap,
                                    enemy=enemy,
                                    step=step,
                                    conditions=conditions,
                                ),
                            )
                    elif step.frozen_damage is not None:
                        sig = (
                            _KIND_LUMINIZE_CONST,
                            None,
                            step.frozen_damage,
                            is_stunned,
                            *_cond_key,
                            None,
                        )
                        sig_counts[sig] += 1
                        if sig not in sig_to_ctx:
                            sig_to_ctx[sig] = (
                                _KIND_LUMINIZE_CONST,
                                False,
                                step.frozen_damage,
                            )
                    else:
                        sig = (
                            _KIND_LUMINIZE,
                            step.voidflare_element,
                            (step.effective_mult_bp, step.def_ignore, step.constant_factor),
                            is_stunned,
                            *_cond_key,
                            None,
                        )
                        sig_counts[sig] += 1
                        if sig not in sig_to_ctx:
                            ctx = build_luminize_step_context(
                                build=frame_snap,
                                enemy=enemy,
                                step=step,
                                conditions=conditions,
                            )
                            sig_to_ctx[sig] = (_KIND_LUMINIZE, False, ctx)
                elif isinstance(step, TeammateDamageStep):
                    # A3: reuses the existing float-ctx kind — a pure constant is
                    # exactly what `_KIND_LUMINIZE_CONST` already scores.
                    sig = (
                        _KIND_LUMINIZE_CONST,
                        None,
                        step.frozen_damage,
                        is_stunned,
                        *_cond_key,
                        None,
                    )
                    sig_counts[sig] += 1
                    if sig not in sig_to_ctx:
                        sig_to_ctx[sig] = (_KIND_LUMINIZE_CONST, False, step.frozen_damage)
                elif isinstance(step, AbloomStep):
                    sig = (
                        _KIND_ABLOOM,
                        None,
                        (step.frozen_abloom_damage, step.frozen_ap, step.ap_scaled),
                        is_stunned,
                        *_cond_key,
                        None,
                    )
                    sig_counts[sig] += 1
                    if sig not in sig_to_ctx:
                        sig_to_ctx[sig] = (
                            _KIND_ABLOOM,
                            False,
                            build_abloom_context(
                                build=frame_snap,
                                enemy=enemy,
                                step=step,
                                conditions=conditions,
                            ),
                        )
                elif isinstance(step, SquadAtkCreditStep):
                    # #160 A4. Keyed on the rescale inputs, like the Refringe
                    # credit; `grant_rows` is already a tuple so it hashes.
                    sig = (
                        _KIND_SQUAD_ATK_CREDIT,
                        None,
                        (
                            step.frozen_teammate_damage,
                            step.teammate_atk_at_sim,
                            step.grant_rows,
                        ),
                        is_stunned,
                        *_cond_key,
                        None,
                    )
                    sig_counts[sig] += 1
                    if sig not in sig_to_ctx:
                        sig_to_ctx[sig] = (
                            _KIND_SQUAD_ATK_CREDIT,
                            False,
                            build_squad_atk_credit_context(
                                build=frame_snap,
                                enemy=enemy,
                                step=step,
                                conditions=conditions,
                            ),
                        )
                elif isinstance(step, RefringeCreditStep):
                    # #160. The teammate's tick itself was dropped by `_owns`;
                    # this is only the uplift the scored build's Refringe
                    # Coefficient put on it. Keyed on the rescale inputs so two
                    # credits differing in any of them cannot share a context.
                    # Scored through the Luminize overlay helpers because the
                    # context shape is identical — one node, AP the only live
                    # term (see `build_refringe_credit_context`).
                    sig = (
                        _KIND_REFRINGE_CREDIT,
                        None,
                        (
                            step.frozen_tick_damage,
                            step.refringe_mult_at_stripped_ap,
                            step.refringe_ap_ratio_bp,
                            step.refringe_flat_bonus_bp,
                        ),
                        is_stunned,
                        *_cond_key,
                        None,
                    )
                    sig_counts[sig] += 1
                    if sig not in sig_to_ctx:
                        sig_to_ctx[sig] = (
                            _KIND_REFRINGE_CREDIT,
                            False,
                            build_refringe_credit_context(
                                build=frame_snap,
                                enemy=enemy,
                                step=step,
                                conditions=conditions,
                            ),
                        )
                elif not isinstance(step, (StunTriggerStep, StunEndStep)):
                    # Markers carry no damage node; anything else is a step type
                    # that was never wired into this loop and must not be scored
                    # as zero (E-8 acceptance item 4).
                    raise TypeError(
                        f"optimize_discs: unhandled step type {type(step).__name__}"
                    )

            step_ctxs: list[_WeightedStepCtx] = [
                (sig_counts[sig], kind, is_ex, ctx)
                for sig, (kind, is_ex, ctx) in sig_to_ctx.items()
            ]
            per_list.append(step_ctxs)
        return frame_snap, per_list

    # Pareto-dominance prefilter (P1d + P1d-2), applied BEFORE bucket sizes / auto-K /
    # the budget-K prefilter — it changes bucket sizes the estimator sees, so it must run
    # first. Projects the comparison onto probe-derived live dims (Task 5f stage 1) and
    # collapses the (slot, set_id, main_stat_type) grouping to (slot, set_id) (stage 2):
    # once the vector is projected, a dead main stat contributes nothing, so different
    # mains become directly comparable.
    _, _pareto_probe_ctxs = _build_frame_contexts([])
    _pareto_fields = _effective_pareto_fields(
        slot_candidates,
        _pareto_probe_ctxs,
        constraints,
        _gating,
        union_element=fluxed_element or base_build.agent_element,
    )
    slot_candidates, _pareto_removed = _pareto_filter(
        slot_candidates, _pareto_fields, collapse_main=True
    )

    # n_ctx (Task 6c): the number of unique weighted step contexts the hot loop iterates
    # per combo — already computed above for the Pareto probe, since _build_frame_contexts
    # collapses to the same signature dedup regardless of frame_set_mods (modifiers affect
    # context *values*, not which signatures exist). Drives the time-denominated budget.
    _n_ctx = sum(len(step_ctxs) for step_ctxs in _pareto_probe_ctxs)
    _effective_budget = _effective_combo_budget(_n_ctx)

    _bucket_sizes = _extract_bucket_sizes(slot_candidates)
    _effective_k = _compute_effective_k(_bucket_sizes, constraints, _effective_budget)

    # Min-heap of (score, tiebreaker, result). heapq keeps smallest — invert
    # the score so the smallest entry on the heap is the worst of the top-N.
    top: list[tuple[float, tuple[str, ...], OptimizerBuildResult]] = []
    counters = {"evaluated": 0, "pruned_sets": 0, "pruned_stats": 0}

    # Context cache: frozenset(set_counts.items()) → (frame_snap, per_list_weighted_ctxs).
    # Avoids rebuilding registry for combos that share the same set distribution.
    _ctx_cache: dict[frozenset, tuple[BuildSnapshot, list[list[_WeightedStepCtx]]]] = {}

    def _get_contexts(
        set_counts: dict[int, int],
    ) -> tuple[BuildSnapshot, list[list[_WeightedStepCtx]]]:
        key = frozenset(set_counts.items())
        if key not in _ctx_cache:
            mods = applicable_set_modifiers(
            set_counts,
            disc_set_modifiers,
            equipper_specialty=base_build.agent_specialty,
            equipper_element=base_build.agent_element,
            equipper_name=base_build.agent_name,
        )
            _ctx_cache[key] = _build_frame_contexts(mods)
        return _ctx_cache[key]

    def _solo_score(
        candidate: DiscCandidate,
        score_ctxs: list[list[_WeightedStepCtx]],
        ref_disc_stats: list[dict] | None = None,
    ) -> float:
        """Cheap marginal-damage heuristic for prefilter ranking.

        When ``ref_disc_stats`` is provided (PREFILTER_BASELINE="full", P1c F-a), those
        disc stats are accumulated alongside the candidate so the score reflects a
        realistic operating point (e.g. the CR×CD cross-term is evaluated near actual
        crit values) rather than at the bare zero-disc baseline.
        """
        all_dicts = [candidate.to_stat_dict()]
        if ref_disc_stats:
            all_dicts.extend(ref_disc_stats)
        disc = accumulate_disc_stats(all_dicts)
        best = 0.0
        for step_ctxs in score_ctxs:
            tot = 0.0
            for count, kind, _is_ex, ctx in step_ctxs:
                if kind == _KIND_STANDARD:
                    tot += count * compute_damage_with_accumulated_disc(ctx, disc)  # type: ignore[arg-type]
                elif kind == _KIND_ANOMALY:
                    tot += count * compute_anomaly_with_accumulated_disc(ctx, disc)  # type: ignore[arg-type]
                elif kind in (
                    _KIND_LUMINIZE,
                    _KIND_LUMINIZE_OWNER,
                    _KIND_REFRINGE_CREDIT,
                    _KIND_SQUAD_ATK_CREDIT,
                    _KIND_ABLOOM,
                ):
                    tot += count * compute_luminize_with_accumulated_disc(ctx, disc)  # type: ignore[arg-type]
                else:  # _KIND_LUMINIZE_CONST — ctx is the damage itself
                    tot += count * ctx  # type: ignore[operator]
            best = max(best, tot)
        return best

    def _prefilter(  # noqa: PLR0912, PLR0915
        slot_cands: dict[int, list[DiscCandidate]],
    ) -> tuple[dict[int, list[DiscCandidate]], int, int | None]:
        """Reduce each (slot, set_id) bucket via solo-damage top-K ∪ synergy-stat union.

        Grouping by set preserves set-formation ability; K >= group size is exact.
        Returns (filtered_candidates, removed_count, k_dmg_used).
        k_dmg_used is the damage-sort keep count after any product-cap trimming.
        """
        k = _effective_k
        if k is None:
            return slot_cands, 0, None

        # Build scoring contexts based on PREFILTER_BASELINE (P1c).
        # "full" (F-a + F-b):
        #   F-a: _ref_disc_stats is accumulated alongside each candidate in _solo_score so
        #        that CR×CD interactions are evaluated near a realistic operating point.
        #        Note: build_damage_step_context always strips disc_stats from the context
        #        (overlay fast path), so the reference must be in the _solo_score call, not
        #        in the context build.
        #   F-b: per-set_id contexts include each bucket's own set modifiers.
        # "base": bare base build, no reference (current behavior).
        _ref_disc_stats: list[dict] | None = None
        _bucket_ctxs: dict[int, list[list[_WeightedStepCtx]]] = {}
        if PREFILTER_BASELINE == "full":
            _ref_disc_stats = _build_ref_disc_stats(slot_cands)
            all_set_ids = {d.set_id for slot in _ALL_SLOTS for d in slot_cands[slot]}
            for sid in all_set_ids:
                set_mods = applicable_set_modifiers(
                    {sid: 4}, disc_set_modifiers,
                    equipper_specialty=base_build.agent_specialty,
                    equipper_element=base_build.agent_element,
                    equipper_name=base_build.agent_name,
                )
                if not set_mods:
                    set_mods = applicable_set_modifiers(
                        {sid: 2}, disc_set_modifiers,
                        equipper_specialty=base_build.agent_specialty,
                        equipper_element=base_build.agent_element,
                        equipper_name=base_build.agent_name,
                    )
                _, _bucket_ctxs[sid] = _build_frame_contexts(set_mods)
            _, _base_ctxs = _build_frame_contexts([])
        else:
            _, _base_ctxs = _build_frame_contexts([])

        def _score_ctxs(set_id: int) -> list[list[_WeightedStepCtx]]:
            if PREFILTER_BASELINE == "full":
                return _bucket_ctxs.get(set_id, _base_ctxs)
            return _base_ctxs

        # Synergy stats for the union keep (P1b).
        union_fields: list[str] = ["crit_rate", "crit_dmg"]
        if _gating:
            union_fields.append("energy_regen")
        # A live (DPS-captured) LuminizeStep runs AnomalyProfArea off the scored
        # build's AP just as an AnomalyStep does, so it makes AP a synergy stat
        # even on a team whose rotation materialises no anomaly of its own
        # (Task 36 / E-8). A frozen one does not — it is a constant.
        if any(
            isinstance(s, AnomalyStep)
            or (
                isinstance(s, LuminizeStep)
                and (s.frozen_damage is None or s.is_owner_scaled)
            )
            for steps in all_step_lists
            for s in steps
        ):
            union_fields.append("anomaly_proficiency")
        # Union the *fluxed* element's DMG% stat when one was resolved (Task 8):
        # a Lumiflux build's own agent_element ("lumiflux") never has a real
        # `<element>_dmg` bucket (DESIGN §4.2), so falling back to it here would
        # silently union nothing for a Lumiflux build with no override.
        _union_element = fluxed_element or base_build.agent_element
        _element_dmg_field = f"{_union_element}_dmg"
        if _union_element and _element_dmg_field in _ELEMENT_DMG_FIELDS:
            union_fields.append(_element_dmg_field)

        # Pre-score every candidate once: damage ranking + accumulated stats.
        # Keyed by disc_id (str) because DiscCandidate.substats is a list → unhashable.
        rankings: dict[tuple[int, int], list[tuple[float, DiscCandidate]]] = {}
        acc_cache: dict[str, dict[str, float]] = {}
        for slot in _ALL_SLOTS:
            for d in slot_cands[slot]:
                key = (slot, d.set_id)
                if key not in rankings:
                    rankings[key] = []
                acc = accumulate_disc_stats([d.to_stat_dict()])
                rankings[key].append((_solo_score(d, _score_ctxs(d.set_id), _ref_disc_stats), d))
                acc_cache[d.disc_id] = {f: float(getattr(acc, f)) for f in union_fields}

        for entries in rankings.values():
            entries.sort(key=lambda x: -x[0])

        cap_limit = UNION_PRODUCT_CAP * _effective_budget
        m = UNION_STAT_KEEP
        k_dmg = k
        union_keep: dict[tuple[int, int], set[str]] = {}  # (slot, set_id) → set of disc_ids

        for trial_k in range(k, 0, -1):
            union_keep = {}
            for key, ranking in rankings.items():
                kept: set[str] = {d.disc_id for _, d in ranking[:trial_k]}
                for stat_field in union_fields:
                    by_stat = sorted(
                        ranking, key=lambda x, f=stat_field: -acc_cache[x[1].disc_id][f]
                    )
                    for _, d in by_stat[:m]:
                        kept.add(d.disc_id)
                union_keep[key] = kept
            union_sizes = {key: len(ids) for key, ids in union_keep.items()}
            est = _estimate_combo_count(
                union_sizes, constraints.allowed_frames, constraints.required_sets, k=None
            )
            if est <= cap_limit:
                k_dmg = trial_k
                break
        else:
            k_dmg = 1  # minimum; union_keep already set for trial_k=1

        out: dict[int, list[DiscCandidate]] = {}
        removed = 0
        for slot in _ALL_SLOTS:
            slot_kept = [
                d for d in slot_cands[slot]
                if d.disc_id in union_keep.get((slot, d.set_id), set())
            ]
            removed += len(slot_cands[slot]) - len(slot_kept)
            out[slot] = slot_kept
        return out, removed, k_dmg

    slot_candidates, _prefiltered, _k_dmg_used = _prefilter(slot_candidates)
    _auto_prefilter_k = (
        _k_dmg_used if (constraints.prefilter_top_k is None and _effective_k is not None) else None
    )

    # Heap stores (total_damage, disc_id_tuple, frame_snap, disc_stats, set_counts, per_combo).
    # resolve_build_stats is deferred to post-processing so it runs only top_n times,
    # not once per competitive combo. When min_stats is set we must run stats in the loop.
    _need_stats_in_loop = bool(constraints.min_stats)

    def score(
        combo: tuple[DiscCandidate, ...],
        set_counts: dict[int, int],
    ) -> None:
        frame_snap, per_list_ctxs = _get_contexts(set_counts)
        disc_stats = [d.to_stat_dict() for d in combo]

        # --- Damage via overlay (fast path) ---
        per_combo: list[float] = [0.0] * len(per_list_ctxs)

        # Sentinel: event_log_by_am non-None means value-keyed AM map.
        is_am_multiplexed = event_log_by_am is not None
        am_idx = 0
        if is_am_multiplexed:
            s6 = combo[5]
            slot6_am_flat = s6.main_stat_value if s6.main_stat_type == "anomaly_mastery" else 0
            coarse_am = resolve_coarse_am_from_counts(
                base_build.agent_anomaly_mastery,
                slot6_am_flat,
                set_counts,
                am_2pc_sets or {},
            )
            am_idx = am_value_to_idx.get(coarse_am, 0)

        indices_to_evaluate = [am_idx] if is_am_multiplexed else range(len(per_list_ctxs))

        disc = accumulate_disc_stats(disc_stats)
        feasibility = _energy_feasibility(disc.energy_regen) if _gating else 1.0
        for idx in indices_to_evaluate:
            step_ctxs = per_list_ctxs[idx]
            ex_total = 0.0
            nonex_total = 0.0
            for count, kind, is_ex, ctx in step_ctxs:
                if kind == _KIND_STANDARD:
                    value = count * compute_damage_with_accumulated_disc(
                        ctx,
                        disc,  # type: ignore[arg-type]
                    )
                elif kind == _KIND_ANOMALY:
                    value = count * compute_anomaly_with_accumulated_disc(
                        ctx,
                        disc,  # type: ignore[arg-type]
                    )
                elif kind in (
                    _KIND_LUMINIZE,
                    _KIND_LUMINIZE_OWNER,
                    _KIND_REFRINGE_CREDIT,
                    _KIND_SQUAD_ATK_CREDIT,
                    _KIND_ABLOOM,
                ):
                    value = count * compute_luminize_with_accumulated_disc(
                        ctx,
                        disc,  # type: ignore[arg-type]
                    )
                else:  # _KIND_LUMINIZE_CONST — ctx is the damage itself
                    value = count * ctx  # type: ignore[operator]
                if is_ex:
                    ex_total += value
                else:
                    nonex_total += value
            # Energy gating credits EX damage by feasibility (1.0 when gating is off).
            per_combo[idx] = nonex_total + ex_total * feasibility

        total = max(per_combo)

        # Early exit: skip combos that cannot displace the current worst top-N entry.
        if len(top) >= constraints.top_n and total <= top[0][0]:
            counters["evaluated"] += 1
            return

        # Stat-floor check: only when min_stats constraints are active.
        if _need_stats_in_loop:
            snapshot = replace(frame_snap, disc_stats=disc_stats)
            stats = resolve_build_stats(snapshot, conditions, attack_scope=AttackScope.ALL)
            if not _meets_stat_floors(stats, constraints.min_stats):
                counters["pruned_stats"] += 1
                return

        # Store a placeholder result; total_stats computed post-search for top-N only.
        result = OptimizerBuildResult(
            total_damage=total,
            disc_ids=[d.disc_id for d in combo],
            set_counts=set_counts,
            snapshot=replace(frame_snap, disc_stats=disc_stats),
            total_stats=BuildStatsSummary(),
            per_combo_damage=tuple(per_combo),
        )
        counters["evaluated"] += 1
        _heap_push_top_n(top, result, cap=constraints.top_n)

    # Progress tracking setup (G1+G2+G3). Ticking is per-combo on a bounded
    # count/time cadence, so progress and cooperative cancellation stay responsive
    # regardless of how large any single slot-1 chunk is.
    if progress_callback is not None:
        _start = time.perf_counter()
        _total = _compute_exact_combo_total(slot_candidates, constraints)
        _done = 0
        _pending = 0
        _last_emit = _start

        def _emit() -> None:
            progress_callback(  # type: ignore[misc]  # may raise OptimizerCancelled
                OptimizerProgress(
                    assignments_done=_done,
                    assignments_total=_total,
                    evaluated=counters["evaluated"],
                    pruned_sets=counters["pruned_sets"],
                    pruned_stats=counters["pruned_stats"],
                    elapsed_seconds=time.perf_counter() - _start,
                )
            )

        # Emit initial snapshot before the loop so the client has a denominator (G1).
        _emit()

        def _tick(n: int = 1) -> None:
            """Count n combos considered; emit on the combo/time cadence (G2+G3).

            Fires the callback (which may raise OptimizerCancelled) every
            PROGRESS_TICK_EVERY combos OR every PROGRESS_TICK_SECONDS, whichever
            comes first — decoupling progress/cancel latency from slot-1 chunk size.
            """
            nonlocal _done, _pending, _last_emit
            _done += n
            _pending += n
            now = time.perf_counter()
            if _pending >= PROGRESS_TICK_EVERY or (now - _last_emit) >= PROGRESS_TICK_SECONDS:
                _pending = 0
                _last_emit = now
                _emit()

        def _flush() -> None:
            """Final emit so the client observes done == total and a last cancel check runs."""
            nonlocal _pending, _last_emit
            _pending = 0
            _last_emit = time.perf_counter()
            _emit()

    if constraints.allowed_frames is None:
        if progress_callback is not None:
            # Tick per combo considered (scored + set-pruned) so cadence is independent
            # of slot-1 chunk size — a single huge slot-1 chunk still ticks internally.
            for combo in product(*(slot_candidates[s] for s in _ALL_SLOTS)):
                set_counts = _count_sets(combo)
                if not _meets_required_sets(set_counts, constraints.required_sets):
                    counters["pruned_sets"] += 1
                else:
                    score(combo, set_counts)
                _tick()
            _flush()
        else:
            for combo in product(*(slot_candidates[s] for s in _ALL_SLOTS)):
                set_counts = _count_sets(combo)
                if not _meets_required_sets(set_counts, constraints.required_sets):
                    counters["pruned_sets"] += 1
                    continue
                score(combo, set_counts)
    else:
        for frame in constraints.allowed_frames:
            if not _meets_required_sets(frame.counts, constraints.required_sets):
                counters["pruned_sets"] += 1
                continue
            frame_counts = dict(frame.counts)
            for assignment in _enumerate_slot_assignments(frame):
                filtered = _filter_by_assignment(slot_candidates, assignment)
                if any(not filtered[s] for s in _ALL_SLOTS):
                    continue  # 0 combos; not counted in _total, no tick needed
                for combo in product(*(filtered[s] for s in _ALL_SLOTS)):
                    score(combo, frame_counts)
                    if progress_callback is not None:
                        _tick()
        if progress_callback is not None:
            _flush()

    # Sort top-N descending by damage, then compute full stats for each retained build.
    # resolve_build_stats runs only top_n times regardless of inventory size.
    ranked_raw = sorted(top, key=lambda e: -e[0])
    ranked: list[OptimizerBuildResult] = []
    for entry in ranked_raw:
        b = entry[2]
        stats = resolve_build_stats(b.snapshot, conditions, attack_scope=AttackScope.ALL)
        ranked.append(replace(b, total_stats=_extract_stats(stats)))
    return OptimizerResult(
        builds=ranked,
        evaluated=counters["evaluated"],
        pruned_sets=counters["pruned_sets"],
        pruned_stats=counters["pruned_stats"],
        prefiltered=_prefiltered,
        auto_prefilter_k=_auto_prefilter_k,
        pareto_removed=_pareto_removed,
    )


def _bucket_by_slot(
    inventory: list[DiscCandidate],
    locked: dict[int, str],
) -> dict[int, list[DiscCandidate]]:
    buckets: dict[int, list[DiscCandidate]] = {s: [] for s in _ALL_SLOTS}
    for d in inventory:
        if d.slot in buckets:
            buckets[d.slot].append(d)
    # Enforce locks: if a slot is locked, keep only the matching disc (if any).
    for slot, locked_id in locked.items():
        if slot not in buckets:
            continue
        buckets[slot] = [d for d in buckets[slot] if d.disc_id == locked_id]
    return buckets


def _disc_stat_vector(
    disc: DiscCandidate, fields: tuple[str, ...] = _PARETO_STAT_FIELDS
) -> tuple[int, ...]:
    """Accumulated stat vector (main + substats) over `fields`, fixed order."""
    stats = accumulate_disc_stats([disc.to_stat_dict()])
    return tuple(getattr(stats, name) for name in fields)


def _pareto_dominates(
    v_a: tuple[int, ...],
    v_b: tuple[int, ...],
    id_a: str,
    id_b: str,
) -> bool:
    """True if disc A's vector makes disc B's redundant.

    Strict dominance (A >= B in every dim, > in at least one) always qualifies. An exact
    tie (identical vectors — cannot differ in damage) qualifies too, with the lower
    ``disc_id`` treated as the survivor so ties collapse to exactly one keeper.
    """
    if not all(a >= b for a, b in zip(v_a, v_b, strict=True)):
        return False
    if any(a > b for a, b in zip(v_a, v_b, strict=True)):
        return True
    return id_a < id_b


def _pareto_filter(
    slot_candidates: dict[int, list[DiscCandidate]],
    fields: tuple[str, ...] = _PARETO_STAT_FIELDS,
    *,
    collapse_main: bool = False,
) -> tuple[dict[int, list[DiscCandidate]], int]:
    """Drop discs whose stat vector (over `fields`) is dominated within their group.

    Lossless (P1d): every comparison dimension is weakly monotone in damage, so a dominated
    disc can never appear in an optimal build — no error bound needed, unlike the budget-K
    prefilter. Grouping is ``(slot, set_id, main_stat_type)`` by default — different main
    stats are incomparable trade-offs under the full-vector comparator. When
    ``collapse_main`` is True (Task 5f stage 2, P1d-2), grouping drops to
    ``(slot, set_id)``: once the comparison is projected onto ``fields``, a dead main stat
    contributes nothing to the vector, so different mains become directly comparable and a
    disc with a genuinely weaker main+substat combination can be pruned.
    """
    groups: dict[tuple[int, int] | tuple[int, int, str], list[DiscCandidate]] = {}
    for slot, cands in slot_candidates.items():
        for d in cands:
            key = (slot, d.set_id) if collapse_main else (slot, d.set_id, d.main_stat_type)
            groups.setdefault(key, []).append(d)

    dominated: set[str] = set()
    for group in groups.values():
        vectors = {d.disc_id: _disc_stat_vector(d, fields) for d in group}
        for d in group:
            v_d = vectors[d.disc_id]
            if any(
                _pareto_dominates(vectors[e.disc_id], v_d, e.disc_id, d.disc_id)
                for e in group
                if e.disc_id != d.disc_id
            ):
                dominated.add(d.disc_id)

    out: dict[int, list[DiscCandidate]] = {}
    removed = 0
    for slot, cands in slot_candidates.items():
        kept = [d for d in cands if d.disc_id not in dominated]
        removed += len(cands) - len(kept)
        out[slot] = kept
    return out, removed


# Maps a constraint's TotalStats field name to the DiscStats field(s) that feed it, for
# composite base stats where the constraint name isn't itself a disc field — ATK/HP/DEF
# are computed from a %+flat pair, not stored as a single disc-contributed field. Any key
# that already matches a DiscStats field name (e.g. "crit_rate", "physical_dmg") needs no
# alias and passes through _constraint_stat_fields unchanged.
_CONSTRAINT_STAT_ALIASES: dict[str, tuple[str, ...]] = {
    "atk": ("flat_atk", "atk_pct"),
    "hp": ("flat_hp", "hp_pct"),
    "defense": ("flat_def", "def_pct"),
}


def _constraint_stat_fields(min_stats_keys: Iterable[str]) -> set[str]:
    """DiscStats fields that must survive projection because a constraint depends on them.

    Biased toward inclusion (P1d-2): a constraint key with no known mapping to a DiscStats
    field is simply not addable here — there's nothing concrete to over-include for it.
    """
    out: set[str] = set()
    for key in min_stats_keys:
        if key in _PARETO_STAT_FIELDS:
            out.add(key)
        else:
            out.update(_CONSTRAINT_STAT_ALIASES.get(key, ()))
    return out


def _max_achievable_stats(
    slot_candidates: dict[int, list[DiscCandidate]],
) -> dict[str, int]:
    """Generous per-field upper bound on total disc contribution (P1d-2 probe input).

    Sums, for each field, the best single-disc value seen in each slot. This ignores
    set-id/main-stat compatibility across slots — a deliberate over-estimate. P1d-2's bias
    rule is that an over-included dim only weakens the filter, never breaks losslessness,
    so a loose bound here is fine and cheap to compute.
    """
    maxima: dict[str, int] = dict.fromkeys(_PARETO_STAT_FIELDS, 0)
    for slot in _ALL_SLOTS:
        cands = slot_candidates.get(slot) or []
        if not cands:
            continue
        vectors = [_disc_stat_vector(d) for d in cands]
        for i, field_name in enumerate(_PARETO_STAT_FIELDS):
            maxima[field_name] += max(v[i] for v in vectors)
    return maxima


def _probe_score(
    field_values: dict[str, int],
    score_ctxs: list[list[_WeightedStepCtx]],
) -> float:
    """Score a synthetic accumulated-stat vector (P1d-2 probe primitive).

    Mirrors `_solo_score`'s evaluation core directly against a `DiscStats` instance (built
    from ``field_values``, all other fields defaulting to 0), so the probe can test
    hypothetical stat combinations that no single disc in the pool carries.
    """
    disc = DiscStats(**field_values)
    best = 0.0
    for step_ctxs in score_ctxs:
        tot = 0.0
        for count, kind, _is_ex, ctx in step_ctxs:
            if kind == _KIND_STANDARD:
                tot += count * compute_damage_with_accumulated_disc(ctx, disc)
            elif kind == _KIND_ANOMALY:
                tot += count * compute_anomaly_with_accumulated_disc(ctx, disc)
            elif kind in (
                    _KIND_LUMINIZE,
                    _KIND_LUMINIZE_OWNER,
                    _KIND_REFRINGE_CREDIT,
                    _KIND_SQUAD_ATK_CREDIT,
                    _KIND_ABLOOM,
                ):
                tot += count * compute_luminize_with_accumulated_disc(ctx, disc)
            else:  # _KIND_LUMINIZE_CONST — ctx is the damage itself
                tot += count * ctx  # type: ignore[operator]
        best = max(best, tot)
    return best


def _effective_pareto_fields(
    slot_candidates: dict[int, list[DiscCandidate]],
    score_ctxs: list[list[_WeightedStepCtx]],
    constraints: OptimizerConstraints,
    er_gate_active: bool,
    union_element: str | None = None,
) -> tuple[str, ...]:
    """Probe-derived objective dims ∪ constraint stats (Task 5f, P1d-2).

    A dim is excluded from the Pareto comparison only if probing it at its
    max-achievable-from-discs value changes the score by exactly zero in BOTH the
    others-at-base and others-at-max contexts — proof, by weak monotonicity, that the dim
    is constant over its entire reachable range for every scoring context in the payload.
    Constraint stats (`min_stats` keys; `energy_regen` under the ER gate) are always
    retained regardless of the probe result — the probe alone can't see them (ER feasibility
    and stat floors are applied outside this scoring function).

    ``union_element``'s ``<element>_dmg`` field is force-kept the same way (Task 8): for an
    unfluxed Lumiflux build the probe correctly finds every `<element>_dmg` field dead
    (``agent_element="lumiflux"`` never reads one), so without this override this lossless
    Pareto layer would prune a fluxed-element-relevant disc *before* `_prefilter`'s
    union-field fix ever runs on it — silently defeating that fix for exactly the build it
    targets.
    """
    maxima = _max_achievable_stats(slot_candidates)
    live: set[str] = set()
    for field_name in _PARETO_STAT_FIELDS:
        max_val = maxima[field_name]
        if max_val == 0:
            continue
        others_max = {f: v for f, v in maxima.items() if f != field_name}
        base_delta = _probe_score({field_name: max_val}, score_ctxs) - _probe_score(
            {}, score_ctxs
        )
        at_max_low = _probe_score(others_max, score_ctxs)
        at_max_high = _probe_score({field_name: max_val, **others_max}, score_ctxs)
        if base_delta != 0 or (at_max_high - at_max_low) != 0:
            live.add(field_name)

    keep = live | _constraint_stat_fields(constraints.min_stats.keys())
    if er_gate_active:
        keep.add("energy_regen")
    if union_element:
        union_field = f"{union_element}_dmg"
        if union_field in _PARETO_STAT_FIELDS:
            keep.add(union_field)
    return tuple(f for f in _PARETO_STAT_FIELDS if f in keep)


def _count_sets(combo: tuple[DiscCandidate, ...]) -> dict[int, int]:
    return dict(Counter(d.set_id for d in combo))


def _enumerate_slot_assignments(frame: SetFrame) -> set[tuple[int, ...]]:
    """Distinct slot-to-set_id assignments that realize a frame.

    Expands the frame's counts into a flat list of set_ids and returns
    the set of all length-6 permutations. Duplicates from repeated
    set_ids collapse automatically via the set.
    """
    flat = [sid for sid, count in frame.counts.items() for _ in range(count)]
    return set(permutations(flat))


def _filter_by_assignment(
    slot_candidates: dict[int, list[DiscCandidate]],
    assignment: tuple[int, ...],
) -> dict[int, list[DiscCandidate]]:
    """Keep only candidates whose set matches the slot's assigned set_id."""
    return {
        slot: [d for d in slot_candidates[slot] if d.set_id == assignment[i]]
        for i, slot in enumerate(_ALL_SLOTS)
    }


def _extract_bucket_sizes(
    slot_candidates: dict[int, list[DiscCandidate]],
) -> dict[tuple[int, int], int]:
    """Return {(slot, set_id): candidate_count} for every non-empty bucket."""
    sizes: dict[tuple[int, int], int] = {}
    for slot, cands in slot_candidates.items():
        for d in cands:
            key = (slot, d.set_id)
            sizes[key] = sizes.get(key, 0) + 1
    return sizes


def _estimate_combo_count(
    bucket_sizes: dict[tuple[int, int], int],
    frames: list[SetFrame] | None,
    required_sets: dict[int, int],
    k: int | None,
) -> int:
    """Estimate total combos with each (slot, set_id) bucket capped to at most k.

    k=None means uncapped (exact bucket sizes). Used by the budget-driven K search
    to find the largest K whose estimated combo count stays within COMBO_BUDGET.

    Exhaustive path (frames=None): product over slots of the sum of per-set-id
    sizes (capped at k) in that slot.
    Frames path: sum over frames × assignments of per-slot products, skipping any
    assignment that has an empty slot for its assigned set_id.
    """
    if frames is None:
        total = 1
        for slot in _ALL_SLOTS:
            per_slot = 0
            for (s, _sid), count in bucket_sizes.items():
                if s == slot:
                    per_slot += min(k, count) if k is not None else count
            total *= per_slot
        return total
    total = 0
    for frame in frames:
        if not _meets_required_sets(frame.counts, required_sets):
            continue
        for assignment in _enumerate_slot_assignments(frame):
            combo = 1
            skip = False
            for i, slot in enumerate(_ALL_SLOTS):
                set_id = assignment[i]
                size = bucket_sizes.get((slot, set_id), 0)
                if size == 0:
                    skip = True
                    break
                combo *= min(k, size) if k is not None else size
            if not skip:
                total += combo
    return total


def _effective_combo_budget(n_ctx: int) -> int:
    """Time-denominated combo budget for this run's context cost (Task 6c).

    `budget = COMBO_BUDGET_TIME_S / (RATE_CTX_OVERHEAD_S + n_ctx / RATE_CTX)`. n_ctx is
    the number of unique weighted step contexts the hot loop actually iterates per combo —
    a stateful/anomaly combo with heavy AM fan-out has a much larger n_ctx than a plain
    multiplicative combo, so it gets a proportionally smaller K for the same wall-clock.
    """
    n = max(n_ctx, 1)
    return int(COMBO_BUDGET_TIME_S / (RATE_CTX_OVERHEAD_S + n / RATE_CTX))


def _compute_effective_k(
    bucket_sizes: dict[tuple[int, int], int],
    constraints: OptimizerConstraints,
    budget: int,
) -> int | None:
    """Resolve the effective prefilter keep-count for a run.

    Priority order:
    1. PREFILTER_EXACT sentinel → None (exact search, no prefilter).
    2. Explicit positive prefilter_top_k → use as-is.
    3. None (auto): if uncapped estimate ≤ budget → None; else binary-search
       for the largest K with estimate(K) ≤ budget.
    """
    caller_k = constraints.prefilter_top_k
    if caller_k == PREFILTER_EXACT:
        return None
    if caller_k is not None:
        return caller_k
    uncapped = _estimate_combo_count(
        bucket_sizes, constraints.allowed_frames, constraints.required_sets, k=None
    )
    if uncapped <= budget:
        return None
    max_k = max(bucket_sizes.values(), default=1)
    lo, hi = 1, max_k
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if (
            _estimate_combo_count(
                bucket_sizes, constraints.allowed_frames, constraints.required_sets, k=mid
            )
            <= budget
        ):
            lo = mid
        else:
            hi = mid - 1
    return lo


def _compute_exact_combo_total(
    slot_candidates: dict[int, list[DiscCandidate]],
    constraints: OptimizerConstraints,
) -> int:
    """Exact number of combos the scoring loop will enumerate.

    Exhaustive path: product of per-slot candidate counts.
    Frames path: sum over non-empty assignments of their per-slot products.
    Matches the loop's actual enumeration so _done reaches _total exactly.
    """
    if constraints.allowed_frames is None:
        total = 1
        for s in _ALL_SLOTS:
            total *= len(slot_candidates[s])
        return total
    total = 0
    for frame in constraints.allowed_frames:
        if not _meets_required_sets(frame.counts, constraints.required_sets):
            continue
        for assignment in _enumerate_slot_assignments(frame):
            filtered = _filter_by_assignment(slot_candidates, assignment)
            if any(not filtered[s] for s in _ALL_SLOTS):
                continue
            n = 1
            for s in _ALL_SLOTS:
                n *= len(filtered[s])
            total += n
    return total


def _meets_required_sets(
    counts: dict[int, int],
    required: dict[int, int],
) -> bool:
    return all(counts.get(set_id, 0) >= need for set_id, need in required.items())


def _meets_stat_floors(
    stats: TotalStats,
    min_stats: dict[str, int],
) -> bool:
    return all(getattr(stats, field_name) >= floor for field_name, floor in min_stats.items())


def _extract_stats(stats: TotalStats) -> BuildStatsSummary:
    """Map TotalStats fields onto the typed BuildStatsSummary response model."""
    return BuildStatsSummary(
        hp=stats.hp,
        atk=stats.atk,
        defense=stats.defense,
        crit_rate=stats.crit_rate,
        crit_dmg=stats.crit_dmg,
        pen_flat=stats.pen_flat,
        pen_ratio=stats.pen_ratio,
        anomaly_mastery=stats.anomaly_mastery,
        anomaly_proficiency=stats.anomaly_proficiency,
        impact=stats.impact,
        energy_regen=stats.energy_regen,
        physical_dmg=stats.physical_dmg,
        fire_dmg=stats.fire_dmg,
        ice_dmg=stats.ice_dmg,
        electric_dmg=stats.electric_dmg,
        ether_dmg=stats.ether_dmg,
    )


def _heap_push_top_n(
    heap: list[tuple[float, tuple[str, ...], OptimizerBuildResult]],
    result: OptimizerBuildResult,
    *,
    cap: int,
) -> None:
    entry = (result.total_damage, tuple(result.disc_ids), result)
    if len(heap) < cap:
        heapq.heappush(heap, entry)
    elif result.total_damage > heap[0][0]:
        heapq.heapreplace(heap, entry)
