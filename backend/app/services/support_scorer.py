"""Support disc scorer — Phase 3 R3.15/R3.16.

Channel-1 (discrete): measures primary combo damage delta from a set-count
change when a candidate disc is swapped into the support's loadout. No PMF —
the improvement is deterministic because disc-set thresholds (2pc/4pc) are
binary. Returns a degenerate DiscScoreResult (avg == max, stddev == 0).

Channel-2 (stat-scaling PMF, R3.16): when the support has HP-scaled
target=team mods, the disc's substat PMF is enumerated. Each cell recomputes
the support's total HP, re-bakes the HP-scaled mod, rebuilds the primary
snapshot, and evaluates the combo. Aggregates into a full DiscScoreResult.
The PMF is skipped (collapses to channel-1) when no such mod exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.damage_calculator import CritMode
from app.services.damage_dag_service import evaluate_steps_total
from app.services.disc_scorer import (
    DEFAULT_SUBSTAT_WEIGHTS,
    MAX_ROLLS_BY_RARITY,
    MAX_SUBSTATS_BY_RARITY,
    DiscScoreResult,
    _count_rolls,
    _enumerate_outcomes,
    _existing_substats,
    _summarize,
)
from app.services.modifiers import ModifierTarget
from app.services.rank_pipeline import PlainBuildDisc
from app.services.support_recompute import rebuild_primary_snapshot_with_support

if TYPE_CHECKING:
    from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
    from app.services.combo_types import Step
    from app.services.disc_optimizer import DiscCandidate
    from app.services.modifiers import ActiveConditions
    from app.services.support_recompute import SupportRecomputeKit


def score_support_disc_potential(
    *,
    primary_snap_without_support: BuildSnapshot,
    kit: SupportRecomputeKit,
    support_build_discs: list[PlainBuildDisc],
    candidate: DiscCandidate,
    disc_rarity: str = "S",
    enemy: EnemySnapshot,
    combo_steps: list[Step],
    conditions: ActiveConditions,
    crit_mode: CritMode = CritMode.EXPECTED,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    substat_weights: dict[str, int] | None = None,
) -> DiscScoreResult:
    """Score a candidate disc's potential via the support's set-count / stat-scaling channels.

    Baseline: primary combo damage with the support's current disc loadout.
    Candidate: primary combo damage after swapping the candidate into the
    support's target slot (recomputes set counts and team mods ORM-free).

    Channel-1 (discrete): no HP-scaled team mods → single-point PMF (avg == max).
    Channel-2 (stat-scaling, R3.16): HP-scaled team mods present → full substat PMF.
    """
    # Baseline: current support disc loadout
    baseline_snap = rebuild_primary_snapshot_with_support(
        primary_snap_without_support,
        kit,
        support_build_discs,
    )
    baseline_damage = _eval_combo(
        baseline_snap,
        enemy,
        combo_steps,
        conditions,
        crit_mode,
        is_stunned,
        stun_dmg_mult,
    )

    # Candidate base discs (set-count swap, current substats)
    candidate_discs = _swap_support_disc(support_build_discs, candidate)

    if not _has_hp_scaled_team_mods(kit):
        # Channel-1: set-count only — deterministic single point
        candidate_snap = rebuild_primary_snapshot_with_support(
            primary_snap_without_support,
            kit,
            candidate_discs,
        )
        candidate_damage = _eval_combo(
            candidate_snap,
            enemy,
            combo_steps,
            conditions,
            crit_mode,
            is_stunned,
            stun_dmg_mult,
        )
        improvement = candidate_damage - baseline_damage
        return DiscScoreResult(
            current_damage=candidate_damage,
            baseline_damage=baseline_damage,
            max_improvement=improvement,
            mean_improvement=improvement,
            stddev_improvement=0.0,
            p10=improvement,
            p50=improvement,
            p90=improvement,
            distribution=[(improvement, 1.0)],
            rolls_used=0,
            remaining_rolls=0,
        )

    # Channel-2: HP-scaled team mods — enumerate substat PMF
    max_rolls = MAX_ROLLS_BY_RARITY.get(disc_rarity)
    if max_rolls is None:
        msg = f"Unknown disc rarity: {disc_rarity!r}"
        raise ValueError(msg)
    target_subs = MAX_SUBSTATS_BY_RARITY[disc_rarity]
    weights = substat_weights or DEFAULT_SUBSTAT_WEIGHTS

    rolls_used = _count_rolls(candidate, disc_rarity)
    remaining = max(0, max_rolls - rolls_used)

    def evaluate(disc_variant: DiscCandidate) -> float:
        variant_discs = _swap_disc_substats(candidate_discs, candidate.slot, disc_variant)
        snap = rebuild_primary_snapshot_with_support(
            primary_snap_without_support,
            kit,
            variant_discs,
        )
        return _eval_combo(
            snap,
            enemy,
            combo_steps,
            conditions,
            crit_mode,
            is_stunned,
            stun_dmg_mult,
        )

    # current_damage: primary damage with candidate's existing substats
    current_damage = evaluate(candidate)

    existing = _existing_substats(candidate)
    pmf: list[tuple[float, float]] = list(
        _enumerate_outcomes(
            disc=candidate,
            existing=existing,
            remaining=remaining,
            target_subs=target_subs,
            weights=weights,
            evaluate=evaluate,
            disc_rarity=disc_rarity,
        ),
    )
    deltas = sorted((dmg - baseline_damage, prob) for dmg, prob in pmf)
    return _summarize(
        deltas=deltas,
        current_damage=current_damage,
        baseline_damage=baseline_damage,
        rolls_used=rolls_used,
        remaining=remaining,
    )


def _has_hp_scaled_team_mods(kit: SupportRecomputeKit) -> bool:
    """True if the kit has any HP-scaled target=team mod in agent_kit_mods_prefiltered."""
    return any(
        m.hp_scale_per_unit > 0 and m.target == ModifierTarget.TEAM
        for m in kit.agent_kit_mods_prefiltered
    )


def _swap_support_disc(
    support_build_discs: list[PlainBuildDisc],
    candidate: DiscCandidate,
) -> list[PlainBuildDisc]:
    """Replace the disc at candidate.slot with a PlainBuildDisc from the candidate."""
    new_disc = PlainBuildDisc(
        slot=candidate.slot,
        main_stat_type=candidate.main_stat_type,
        main_stat_value=candidate.main_stat_value,
        substats=list(candidate.substats or []),
        set_hakushin_id=candidate.set_id,
    )
    replaced = [new_disc if d.slot == candidate.slot else d for d in support_build_discs]
    if all(d.slot != candidate.slot for d in support_build_discs):
        replaced.append(new_disc)
    return replaced


def _swap_disc_substats(
    discs: list[PlainBuildDisc],
    target_slot: int,
    variant: DiscCandidate,
) -> list[PlainBuildDisc]:
    """Return discs with the disc at target_slot updated to variant's substats."""
    return [
        PlainBuildDisc(
            slot=d.slot,
            main_stat_type=d.main_stat_type,
            main_stat_value=d.main_stat_value,
            substats=list(variant.substats or []),
            set_hakushin_id=d.set_hakushin_id,
        )
        if d.slot == target_slot
        else d
        for d in discs
    ]


def _eval_combo(
    build: BuildSnapshot,
    enemy: EnemySnapshot,
    steps: list[Step],
    conditions: ActiveConditions,
    crit_mode: CritMode,
    is_stunned: bool,
    stun_dmg_mult: int,
) -> float:
    return evaluate_steps_total(
        build=build,
        enemy=enemy,
        steps=steps,
        conditions=conditions,
        crit_mode=crit_mode,
        is_stunned=is_stunned,
        stun_dmg_mult=stun_dmg_mult,
    )
