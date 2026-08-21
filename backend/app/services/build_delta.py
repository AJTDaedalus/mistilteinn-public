"""Delta decomposition between two attributed combo evaluations (Task B4).

DESIGN_explainability.md §3.2 / DECISIONS.md D-EXPL-1: evaluate a "from"
build (e.g. the team member's currently-equipped discs) and a "to" build
(a candidate) through the same attributed path (``evaluate_combo_attributed``),
then decompose the change in total damage into exact per-zone shares.
Because a damage step's total is ``base_dmg`` times a product of zone
multipliers, ``ln(total)`` is additive across zones — each zone's
``Δln(zone) / Δln(total)`` is its exact fractional share of the overall
log-space gain, so shares sum to 100% with no fudge (never approximated by
pretending zone deltas add linearly in linear space).

Scope: exact when every damage-bearing step shares the same zone_formulas
value per zone across the run (true whenever the two runs differ only by
discs on one build under one static set of active_conditions/stack_counts —
the keystone endpoint's use case; the "base" zone is the one exception,
correctly summed across steps since BaseDMG genuinely varies per move).
Combos where a zone's value legitimately differs across same-type steps
within one run (e.g. a stun window covering only part of the combo) take the
first occurrence as representative — flagged as a follow-up in
LOG_explainability.md rather than solved generally here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.combo_types import StepResult

# Mirrors damage_calculator.py's own multiplicative chains exactly
# (calculate_standard_damage / _sheer / _anomaly / _disorder): each of those
# applies a subsequence of this order, so skipping zones absent for a given
# step reproduces every path's real order. "sheer_force" is excluded — it is
# presentational only (it feeds the "base" zone's scaling stat, not a
# separate multiplicative term in the calculator's own total formula).
CANONICAL_ZONE_ORDER = (
    "base",
    "boost",
    "crit",
    "def",
    "res",
    "vulnerability",
    "stun",
    "anomaly_prof",
    "anomaly_level",
    "anomaly_boost",
    "disorder_boost",
    "sheer_boost",
)


@dataclass(frozen=True)
class ZoneDelta:
    """One zone's before/after multiplier + its share of the total log-gain."""

    zone: str
    from_bp: int
    to_bp: int
    ratio: float
    gain_share_pct: float


@dataclass(frozen=True)
class BuildDelta:
    """Result of :func:`compute_build_delta`.

    ``is_exact`` is ``True`` when the log-space decomposition is exact for
    this run pair (every non-base zone holds one value across all steps, so
    ``total = base_total x prod(zones)`` factorises cleanly) and ``False``
    when a zone legitimately varies across same-type steps (e.g. a stun
    window covering only part of the combo, or standard+anomaly steps mixed)
    — there the per-zone ``gain_share_pct`` uses a first-occurrence
    representative and shares are approximate. Callers/UI should caveat the
    breakdown when this is ``False`` (see module docstring scope note).
    """

    from_total: int
    to_total: int
    pct_change: float
    zone_deltas: list[ZoneDelta] = field(default_factory=list)
    is_exact: bool = True


def _damage_steps(steps: list[StepResult]) -> list[StepResult]:
    return [
        s
        for s in steps
        if getattr(s, "attribution", None) is not None and s.attribution.zone_formulas
    ]


def _run_is_exact(damage_steps: list[StepResult]) -> bool:
    """True iff every non-base zone holds one value across all damage steps.

    The log-space decomposition factorises ``total = base_total x prod(zones)``
    only when each non-base zone multiplier is constant across the run's
    steps. A step missing a zone is treated as 1.0 (``10000`` bp), so a zone
    only some steps carry — a partial stun window, or standard and anomaly
    steps mixed in one run — correctly counts as varying.
    """
    for zone in CANONICAL_ZONE_ORDER[1:]:
        values = {
            s.attribution.zone_formulas[zone].result_bp
            if zone in s.attribution.zone_formulas
            else 10000
            for s in damage_steps
        }
        if len(values) > 1:
            return False
    return True


def compute_build_delta(
    from_steps: list[StepResult],
    to_steps: list[StepResult],
    *,
    from_total: int,
    to_total: int,
) -> BuildDelta:
    """Decompose the change from ``from_total`` to ``to_total`` by zone.

    ``from_steps``/``to_steps`` are a :class:`ComboEvaluationResult.steps`
    pair from two :func:`evaluate_combo_attributed` runs of the *same*
    combo/conditions (only disc overrides differing).
    """
    from_damage_steps = _damage_steps(from_steps)
    to_damage_steps = _damage_steps(to_steps)

    zone_bp: dict[str, tuple[int, int]] = {
        "base": (
            sum(s.attribution.zone_formulas["base"].result_bp for s in from_damage_steps),
            sum(s.attribution.zone_formulas["base"].result_bp for s in to_damage_steps),
        ),
    }
    for zone in CANONICAL_ZONE_ORDER[1:]:
        from_val = next(
            (
                s.attribution.zone_formulas[zone].result_bp
                for s in from_damage_steps
                if zone in s.attribution.zone_formulas
            ),
            None,
        )
        to_val = next(
            (
                s.attribution.zone_formulas[zone].result_bp
                for s in to_damage_steps
                if zone in s.attribution.zone_formulas
            ),
            None,
        )
        if from_val is None and to_val is None:
            continue
        zone_bp[zone] = (
            from_val if from_val is not None else 10000,
            to_val if to_val is not None else 10000,
        )

    ln_total_ratio = (
        math.log(to_total / from_total) if from_total > 0 and to_total > 0 else 0.0
    )

    zone_deltas = []
    for zone in CANONICAL_ZONE_ORDER:
        if zone not in zone_bp:
            continue
        from_bp, to_bp = zone_bp[zone]
        ratio = to_bp / from_bp if from_bp else 1.0
        share = (
            math.log(ratio) / ln_total_ratio * 100
            if ratio > 0 and ln_total_ratio != 0
            else 0.0
        )
        zone_deltas.append(
            ZoneDelta(zone=zone, from_bp=from_bp, to_bp=to_bp, ratio=ratio, gain_share_pct=share)
        )

    pct_change = ((to_total - from_total) / from_total * 100) if from_total else 0.0

    return BuildDelta(
        from_total=from_total,
        to_total=to_total,
        pct_change=pct_change,
        zone_deltas=zone_deltas,
        is_exact=_run_is_exact(from_damage_steps) and _run_is_exact(to_damage_steps),
    )
