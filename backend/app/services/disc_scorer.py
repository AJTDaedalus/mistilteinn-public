"""Disc potential scorer (Phase 7a) — DAG-driven probability distribution.

Given a disc and the build/combo/enemy it would be used with, this
projects the *distribution* of damage improvements the disc can
deliver as it levels to its rarity's max roll count. The damage
function is the full Pando DAG, so non-linearities (the 100% CRIT
Rate cap, ATK% diminishing returns, anomaly vs standard paths,
DEFArea, RES, etc.) are honored exactly.

ZZZ disc roll mechanics (the model):

* Rarity caps total rolls placed in substats: S = 9, A = 5, B = 3.
* A disc starts with 3 or 4 substats. A-rank and B-rank stay at 3
  forever. S-rank that starts with 3 unlocks its 4th substat on
  the first level-up — choice weighted by the substat's appearance
  rate. ZZZ does NOT pre-reveal that 4th substat.
* Once 4 substats are present, every level-up is uniform 1/4 over
  the four existing substats. There is no per-roll value variance
  (unlike Genshin) — each roll adds exactly the substat's base.

Because ZZZ has no roll-value variance, the upgrade distribution
is purely combinatorial — a multinomial over which substats catch
which rolls. We enumerate the full PMF rather than approximating
with a Gaussian Mixture (that's the simplification that the GO
Genshin upgrade-optimizer trades for speed; we don't need it at
S-rank's ≤56 multinomial cells).

Outputs:

* ``current_damage`` — combo damage with the disc as it stands now
  in its slot (no leveling applied).
* ``baseline_damage`` — what improvements are measured against.
  Defaults to ``current_damage``; callers can pass an explicit
  baseline (e.g. the build's current 6-disc damage with the
  *currently-equipped* disc in the target slot) to compare a
  candidate disc against the player's real current state.
* ``max_improvement`` — best-case ceiling (favorable RNG to the cap).
* ``mean_improvement`` — expected damage gain over the full PMF.
* ``stddev_improvement`` — spread of the damage-gain distribution.
* ``p10 / p50 / p90`` — convenience percentiles.
* ``distribution`` — the full PMF as ``[(improvement, probability), …]``,
  sorted ascending by improvement, for callers who want to plot or
  derive their own statistics.

The caller supplies ``base_build`` with the other five disc slots
already filled and any applicable disc-set modifiers applied. The
scorer only mutates the target disc's substats, so set bonuses
(set_id-keyed) are constant and caller-managed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from itertools import product
from math import factorial
from typing import TYPE_CHECKING

from app.services.am_variants import _set_id_of, resolve_coarse_am_from_counts
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
    build_abloom_context,
    build_damage_step_context,
    build_luminize_step_context,
    build_refringe_credit_context,
    build_squad_atk_credit_context,
    calculate_build_anomaly_dag,
    compute_damage_with_accumulated_disc,
    compute_luminize_with_accumulated_disc,
)
from app.services.disc_constants import SUBSTAT_BASE_PER_ROLL_BY_RARITY
from app.services.disc_constants import compute_rolls as _compute_rolls
from app.services.stat_calculator import accumulate_disc_stats

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.models.disc import Disc
    from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
    from app.services.combo_types import Step
    from app.services.disc_optimizer import DiscCandidate
    from app.services.modifiers import ActiveConditions, Modifier
    from app.services.rank_pipeline import PlainBuildDisc

# Per-roll base value for each substat, S-rank row (units the stat
# calculator expects: basis points for percentages, absolute for flats).
# Alias onto the canonical rarity-aware table (`disc_constants`) rather than
# a second hardcoded copy — issue #65 found this file's own S-rank-only
# table disagreeing with `disc_constants.compute_rolls` on A/B-rank discs.
BASE_VALUES: dict[str, int] = SUBSTAT_BASE_PER_ROLL_BY_RARITY["S"]

# Total rolls per rarity (initial substats counted, plus level-ups).
# S = 4 initial + 5 level-ups, A = 3 initial + 2, B = 3 initial.
MAX_ROLLS_BY_RARITY: dict[str, int] = {"S": 9, "A": 5, "B": 3}

# Number of substats each rarity ends with at max level.
MAX_SUBSTATS_BY_RARITY: dict[str, int] = {"S": 4, "A": 3, "B": 3}

# Appearance weights for the 4th-substat unlock on a 3-sub S-rank
# disc. ZZZ uses uniform probability across all eligible substats
# (each non-main substat is equally likely to be the 4th roll) —
# this is a deliberate divergence from Genshin / HSR, which weight
# crit stats lower than flat stats. Callers can still override via
# ``substat_weights`` for hypothetical analysis.
DEFAULT_SUBSTAT_WEIGHTS: dict[str, int] = dict.fromkeys(BASE_VALUES, 1)

_SLOT_6 = 6


def _slot_int(disc: object) -> int:
    s = getattr(disc, "slot", 0)
    return int(s.value if hasattr(s, "value") else s)


@dataclass(frozen=True)
class DiscScoreResult:
    """Upgrade-potential breakdown for a disc.

    ``current_damage`` is what the build does with the target disc
    equipped *as it stands now*. ``baseline_damage`` is the comparison
    point — by default the same as ``current_damage`` (i.e.
    improvements measure leveling potential intrinsic to the disc),
    but callers can override it (e.g. to compare against the build's
    *currently-equipped* state when scoring an unequipped candidate).
    All improvement / percentile / distribution values are deltas
    against ``baseline_damage``.
    """

    current_damage: float
    max_improvement: float
    mean_improvement: float
    stddev_improvement: float
    p10: float
    p50: float
    p90: float
    distribution: list[tuple[float, float]] = field(default_factory=list)
    rolls_used: int = 0
    remaining_rolls: int = 0
    baseline_damage: float = 0.0


def score_disc_potential(  # noqa: PLR0915
    *,
    base_build: BuildSnapshot,
    enemy: EnemySnapshot,
    combo_steps: list[Step] | dict[int, list[Step]],
    disc: DiscCandidate,
    disc_rarity: str,
    conditions: ActiveConditions,
    crit_mode: CritMode = CritMode.EXPECTED,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    substat_weights: dict[str, int] | None = None,
    baseline_damage: float | None = None,
    build_discs: list[Disc] | list[PlainBuildDisc] | None = None,
    am_2pc_sets: dict[int, list[Modifier]] | None = None,
) -> DiscScoreResult:
    """Project a disc's full upgrade distribution at max level.

    See module docstring for the underlying probability model.

    ``baseline_damage`` controls what improvements are measured
    against. ``None`` (the default) uses the disc's current as-is
    damage, so improvements describe the *leveling potential* of
    that disc in isolation. Pass an explicit value (typically the
    damage of the build with its currently-equipped disc in this
    slot) to measure improvements against the player's actual
    current build instead — answering "if I swap in and level
    this disc, how much better off am I?".
    """
    max_rolls = MAX_ROLLS_BY_RARITY.get(disc_rarity)
    if max_rolls is None:
        msg = f"Unknown disc rarity: {disc_rarity!r}"
        raise ValueError(msg)
    target_subs = MAX_SUBSTATS_BY_RARITY[disc_rarity]
    weights = substat_weights or DEFAULT_SUBSTAT_WEIGHTS

    # Sentinel: dict[int, list[Step]] → AM-value-keyed map; list[Step] → single path.
    is_am_multiplexed = isinstance(combo_steps, dict)

    def _partition(steps: list) -> tuple[list, list, list, float]:  # noqa: PLR0912
        """Split one step list into what the per-candidate loop needs.

        Standard hits and Luminize instances become pre-built DAG contexts (the
        disc layout is overlaid per candidate); anomaly steps are kept as steps
        and re-evaluated; support-captured Luminize instances collapse into a
        single constant.

        The dispatch is exhaustive on purpose — an unknown step type raises here,
        at the site that failed to handle it, rather than reaching
        ``step.multiplier`` and dying with an AttributeError further in
        (E-8 acceptance item 4, ``docs/LOG_remielle.md``).
        """
        std_ctxs: list = []
        anom_steps: list = []
        lum_ctxs: list = []
        lum_constant = 0.0
        current_stun = is_stunned
        for step in steps:
            if isinstance(step, StunTriggerStep):
                current_stun = True
            elif isinstance(step, StunEndStep):
                current_stun = False
            elif isinstance(step, AnomalyStep):
                anom_steps.append(step)
            elif isinstance(step, LuminizeStep):
                # frozen_damage set → captured from a support, whose build the
                # optimizer never strips and never varies. Exact as-is, and a
                # constant addend cannot change ranking. Otherwise it was
                # captured from the build being scored and every DPS-derived
                # term has to be rebuilt against the candidate (E-8 Finding 2).
                if step.frozen_damage is not None:
                    lum_constant += step.frozen_damage
                else:
                    lum_ctxs.append(
                        build_luminize_step_context(
                            build=base_build,
                            enemy=enemy,
                            step=step,
                            conditions=conditions,
                        )
                    )
            elif isinstance(step, TeammateDamageStep):
                lum_constant += step.frozen_damage
            elif isinstance(step, AbloomStep):
                lum_ctxs.append(
                    build_abloom_context(
                        build=base_build, enemy=enemy, step=step, conditions=conditions
                    )
                )
            elif isinstance(step, SquadAtkCreditStep):
                # #160 A4 -- same context shape, so it rides `lum_ctxs` too.
                lum_ctxs.append(
                    build_squad_atk_credit_context(
                        build=base_build,
                        enemy=enemy,
                        step=step,
                        conditions=conditions,
                    )
                )
            elif isinstance(step, RefringeCreditStep):
                # #160. The ranker shares `resolve_stateful_am_step_lists` and
                # `score_owner_id="dps"` with the optimizer, so it receives the
                # same credit steps and must value them the same way or the two
                # surfaces disagree on one build (Task A5).
                #
                # Rides `lum_ctxs` rather than a parallel list because
                # `build_refringe_credit_context` returns a
                # LuminizeDAGStepContext and the loop below already scores those
                # with `compute_luminize_with_accumulated_disc` — the same
                # per-candidate AP overlay this needs.
                lum_ctxs.append(
                    build_refringe_credit_context(
                        build=base_build,
                        enemy=enemy,
                        step=step,
                        conditions=conditions,
                    )
                )
            elif isinstance(step, ComboStep):
                std_ctxs.append(
                    build_damage_step_context(
                        build=base_build,
                        enemy=enemy,
                        multiplier=step.multiplier,
                        conditions=conditions,
                        attack_scope=step.scope,
                        crit_mode=crit_mode,
                        is_stunned=current_stun,
                        stun_dmg_mult=stun_dmg_mult,
                        include_active=not step.off_field,
                    )
                )
            else:
                raise TypeError(f"score_disc: unhandled step type {type(step).__name__}")
        return std_ctxs, anom_steps, lum_ctxs, lum_constant

    per_am_standard_ctxs: dict[int, list] = {}
    per_am_anomaly_steps: dict[int, list] = {}
    per_am_luminize_ctxs: dict[int, list] = {}
    per_am_luminize_constant: dict[int, float] = {}

    if is_am_multiplexed:
        for am_val, steps in combo_steps.items():
            (
                per_am_standard_ctxs[am_val],
                per_am_anomaly_steps[am_val],
                per_am_luminize_ctxs[am_val],
                per_am_luminize_constant[am_val],
            ) = _partition(steps)
    else:
        (
            standard_ctxs_global,
            anomaly_steps_global,
            luminize_ctxs_global,
            luminize_constant_global,
        ) = _partition(list(combo_steps))

    def evaluate(candidate: DiscCandidate) -> float:
        if is_am_multiplexed:
            locked = [d for d in (build_discs or []) if _slot_int(d) != candidate.slot]
            all_discs = [candidate, *locked]
            set_counts: dict[int, int] = Counter(_set_id_of(d) for d in all_discs)
            slot6_am_flat = 0
            for d in all_discs:
                if _slot_int(d) == _SLOT_6:
                    if getattr(d, "main_stat_type", "") == "anomaly_mastery":
                        slot6_am_flat = int(getattr(d, "main_stat_value", 0))
                    break
            coarse_am = resolve_coarse_am_from_counts(
                base_build.agent_anomaly_mastery,
                slot6_am_flat,
                set_counts,
                am_2pc_sets or {},
            )
            if coarse_am not in per_am_standard_ctxs:
                coarse_am = min(per_am_standard_ctxs, key=lambda k: abs(k - coarse_am))
            standard_ctxs = per_am_standard_ctxs[coarse_am]
            anomaly_steps = per_am_anomaly_steps[coarse_am]
            luminize_ctxs = per_am_luminize_ctxs[coarse_am]
            luminize_constant = per_am_luminize_constant[coarse_am]
        else:
            standard_ctxs = standard_ctxs_global
            anomaly_steps = anomaly_steps_global
            luminize_ctxs = luminize_ctxs_global
            luminize_constant = luminize_constant_global

        disc_stats = [*base_build.disc_stats, candidate.to_stat_dict()]
        disc = accumulate_disc_stats(disc_stats)
        total = luminize_constant

        for ctx in standard_ctxs:
            total += compute_damage_with_accumulated_disc(ctx, disc)  # type: ignore[arg-type]
        for lum_ctx in luminize_ctxs:
            total += compute_luminize_with_accumulated_disc(lum_ctx, disc)
        if anomaly_steps:
            snap = replace(base_build, disc_stats=disc_stats)
            for step in anomaly_steps:
                anom = calculate_build_anomaly_dag(
                    build=snap,
                    enemy=enemy,
                    anomaly_type=step.anomaly_type,
                    conditions=conditions,
                    procs=step.procs_override,
                    is_stunned=is_stunned,
                    stun_dmg_mult=stun_dmg_mult,
                )
                total += anom.total
        return total

    rolls_used = _count_rolls(disc, disc_rarity)
    remaining = max(0, max_rolls - rolls_used)
    current_damage = evaluate(disc)

    existing = _existing_substats(disc)
    if not (target_subs - 1 <= len(existing) <= target_subs):
        msg = (
            f"{disc_rarity}-rank disc must have {target_subs - 1} or "
            f"{target_subs} legal substats; got {len(existing)}"
        )
        raise ValueError(msg)

    pmf: list[tuple[float, float]] = list(
        _enumerate_outcomes(
            disc=disc,
            existing=existing,
            remaining=remaining,
            target_subs=target_subs,
            weights=weights,
            evaluate=evaluate,
            disc_rarity=disc_rarity,
        ),
    )

    baseline = baseline_damage if baseline_damage is not None else current_damage
    deltas = sorted((dmg - baseline, prob) for dmg, prob in pmf)
    return _summarize(
        deltas=deltas,
        current_damage=current_damage,
        baseline_damage=baseline,
        rolls_used=rolls_used,
        remaining=remaining,
    )


def _enumerate_outcomes(
    *,
    disc: DiscCandidate,
    existing: list[str],
    remaining: int,
    target_subs: int,
    weights: dict[str, int],
    evaluate: Callable[[DiscCandidate], float],
    disc_rarity: str,
) -> list[tuple[float, float]]:
    """Return ``[(damage, probability), …]`` covering all upgrade outcomes."""
    if remaining == 0 or len(existing) == target_subs:
        # Already at the target sub count; rolls are uniform-multinomial
        # over the existing substats (or there are no rolls to place).
        return _multinomial_outcomes(disc, existing, remaining, evaluate, disc_rarity)

    # 3-sub disc that will unlock its 4th on the first remaining roll
    # (S-rank only). The 4th substat is drawn from the eligible pool
    # weighted by its appearance rate. After unlock, the remaining
    # rolls are uniform-multinomial over the now-4 substats.
    eligible = [
        stat
        for stat in BASE_VALUES
        if stat != disc.main_stat_type and stat not in existing and weights.get(stat, 0) > 0
    ]
    total_weight = sum(weights[stat] for stat in eligible)
    if total_weight == 0:
        # Pathological — no candidate substat can roll. Score as-is.
        return [(evaluate(disc), 1.0)]

    outcomes: list[tuple[float, float]] = []
    for new_stat in eligible:
        p_new = weights[new_stat] / total_weight
        unlocked = _add_one_roll(disc, new_stat, disc_rarity)
        unlocked_existing = [*existing, new_stat]
        for damage, prob in _multinomial_outcomes(
            unlocked,
            unlocked_existing,
            remaining - 1,
            evaluate,
            disc_rarity,
        ):
            outcomes.append((damage, p_new * prob))
    return outcomes


def _multinomial_outcomes(
    disc: DiscCandidate,
    existing: list[str],
    remaining: int,
    evaluate: Callable[[DiscCandidate], float],
    disc_rarity: str,
) -> list[tuple[float, float]]:
    """Enumerate uniform-multinomial outcomes over the existing substats."""
    if remaining == 0:
        return [(evaluate(disc), 1.0)]
    if not existing:
        return [(evaluate(disc), 1.0)]

    k = len(existing)
    outcomes: list[tuple[float, float]] = []
    for partition in _compositions(remaining, k):
        prob = _multinomial_probability(remaining, partition, k)
        upgraded = _apply_partition(disc, existing, partition, disc_rarity)
        outcomes.append((evaluate(upgraded), prob))
    return outcomes


def _compositions(n: int, k: int) -> list[tuple[int, ...]]:
    """All non-negative integer tuples of length k summing to n."""
    if k == 1:
        return [(n,)]
    return [partition for partition in product(range(n + 1), repeat=k) if sum(partition) == n]


def _multinomial_probability(
    n: int,
    partition: tuple[int, ...],
    k: int,
) -> float:
    """Probability of `partition` from n uniform draws over k options."""
    coeff = factorial(n)
    for x in partition:
        coeff //= factorial(x)
    return coeff / (k**n)


def _apply_partition(
    disc: DiscCandidate,
    existing: list[str],
    partition: tuple[int, ...],
    disc_rarity: str,
) -> DiscCandidate:
    """Return a copy of disc with `partition[i]` extra rolls added to existing[i]."""
    upgraded = disc
    for stat, count in zip(existing, partition, strict=True):
        for _ in range(count):
            upgraded = _add_one_roll(upgraded, stat, disc_rarity)
    return upgraded


def _add_one_roll(disc: DiscCandidate, stat: str, disc_rarity: str) -> DiscCandidate:
    """Add one rarity-scaled base-value roll of ``stat`` to the disc's substats."""
    base = SUBSTAT_BASE_PER_ROLL_BY_RARITY[disc_rarity][stat]
    substats = [dict(s) for s in (disc.substats or [])]
    for entry in substats:
        if entry.get("stat") == stat:
            entry["value"] = int(entry.get("value", 0)) + base
            break
    else:
        substats.append({"stat": stat, "value": base})
    return replace(disc, substats=substats)


def _count_rolls(disc: DiscCandidate, disc_rarity: str) -> int:
    """Sum roll count across the disc's current legal substats.

    Uses the same rarity-scaled bases and rounding rule as
    ``disc_constants.compute_rolls`` — the two counters used to disagree on
    A/B-rank discs (issue #65): this one floor-divided against the S-rank
    base unconditionally, undercounting (sometimes to zero) whenever the
    disc's real per-roll base for a stat is smaller than S-rank's.
    """
    table = SUBSTAT_BASE_PER_ROLL_BY_RARITY.get(disc_rarity, SUBSTAT_BASE_PER_ROLL_BY_RARITY["S"])
    rolls = 0
    for entry in disc.substats or []:
        stat = entry.get("stat", "")
        if stat == disc.main_stat_type or stat not in table:
            continue
        raw = int(entry.get("value", 0))
        if raw <= 0:
            continue
        rolls += _compute_rolls(stat, raw, disc_rarity)
    return rolls


def _existing_substats(disc: DiscCandidate) -> list[str]:
    """Legal (non-main, known) substat keys present on the disc, deduped."""
    seen: list[str] = []
    for entry in disc.substats or []:
        stat = entry.get("stat", "")
        if stat == disc.main_stat_type:
            continue
        if stat in BASE_VALUES and stat not in seen:
            seen.append(stat)
    return seen


def _summarize(
    *,
    deltas: list[tuple[float, float]],
    current_damage: float,
    baseline_damage: float,
    rolls_used: int,
    remaining: int,
) -> DiscScoreResult:
    """Reduce a sorted ``[(delta, prob), …]`` PMF to summary statistics."""
    if not deltas:
        return DiscScoreResult(
            current_damage=current_damage,
            baseline_damage=baseline_damage,
            max_improvement=0.0,
            mean_improvement=0.0,
            stddev_improvement=0.0,
            p10=0.0,
            p50=0.0,
            p90=0.0,
            distribution=[],
            rolls_used=rolls_used,
            remaining_rolls=remaining,
        )

    max_delta = max(d for d, _ in deltas)
    mean = sum(d * p for d, p in deltas)
    var = sum(p * (d - mean) ** 2 for d, p in deltas)
    stddev = var**0.5

    return DiscScoreResult(
        current_damage=current_damage,
        baseline_damage=baseline_damage,
        max_improvement=max_delta,
        mean_improvement=mean,
        stddev_improvement=stddev,
        p10=_percentile(deltas, 0.10),
        p50=_percentile(deltas, 0.50),
        p90=_percentile(deltas, 0.90),
        distribution=deltas,
        rolls_used=rolls_used,
        remaining_rolls=remaining,
    )


def _percentile(sorted_pmf: list[tuple[float, float]], q: float) -> float:
    """Return the q-percentile delta from a sorted ``[(delta, prob), …]`` PMF."""
    cumulative = 0.0
    for delta, prob in sorted_pmf:
        cumulative += prob
        if cumulative >= q:
            return delta
    return sorted_pmf[-1][0]
