"""Rank pipeline — async DB-resolve + process-pool sync runner (Phase 2 — R2.6).

Pattern mirrors optimizer_pipeline:
  1. resolve_rank_payload() — async, resolves all DB entities, returns
     a picklable ResolvedRankPayload.
  2. run_rank_pipeline_with_progress() — sync, fans out per-(disc, context)
     scoring across a ProcessPoolExecutor, aggregates, fires progress
     callbacks.
"""

from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.disc import Disc
from app.services.am_variants import build_am_2pc_sets, resolve_coarse_am
from app.services.damage_dag_service import evaluate_steps_total
from app.services.disc_ranker import RankProgress
from app.services.disc_scorer import score_disc_potential
from app.services.modifier_loader import load_disc_set_modifiers
from app.services.optimizer_pipeline import (
    CRIT_MODES,
    _disc_to_candidate,
    _parse_conditions,
    build_snapshot_split,
)
from app.services.scorer_support import _build_base_for_target
from app.services.snapshot_builder import build_snapshot_from_db, enemy_snapshot_from_db
from app.services.support_recompute import SupportRecomputeKit, build_support_recompute_kit
from app.services.support_selection import select_support_members

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.build import Build
    from app.repositories.attack import AttackRepository
    from app.repositories.build import (
        BuildRepository,
        ComboRepository,
        EnemyProfileRepository,
    )
    from app.repositories.team import TeamRepository
    from app.schemas.scorer import RankFilters, RankRequest
    from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
    from app.services.combo_types import Step
    from app.services.damage_calculator import CritMode
    from app.services.disc_optimizer import DiscCandidate
    from app.services.modifiers import ActiveConditions, Modifier


# ---------------------------------------------------------------------------
# Plain (picklable) disc reference — for process-pool use
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SetRef:
    hakushin_id: int


@dataclass
class PlainBuildDisc:
    """ORM-free build disc, picklable for process-pool workers.

    Exposes the same attribute surface that scorer_support helpers expect
    from Disc ORM objects (slot, main_stat_type, main_stat_value, substats,
    disc_set.hakushin_id).
    """

    slot: int
    main_stat_type: str
    main_stat_value: int
    substats: list[dict]
    set_hakushin_id: int
    disc_set: _SetRef = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "disc_set", _SetRef(self.set_hakushin_id))


def _plain_disc_from_orm(disc: Disc) -> PlainBuildDisc:
    """Convert an ORM Disc into a PlainBuildDisc (call in async resolve phase)."""
    stat_type = disc.main_stat_type
    if hasattr(stat_type, "value"):
        stat_type = stat_type.value
    slot = disc.slot
    slot = int(slot.value) if hasattr(slot, "value") else int(slot)
    set_id = disc.disc_set.hakushin_id if disc.disc_set is not None else 0
    return PlainBuildDisc(
        slot=slot,
        main_stat_type=str(stat_type),
        main_stat_value=disc.main_stat_value,
        substats=list(disc.substats or []),
        set_hakushin_id=set_id,
    )


# ---------------------------------------------------------------------------
# Resolved payload dataclasses (picklable)
# ---------------------------------------------------------------------------


@dataclass
class ResolvedRankContext:
    """All data needed to score every disc against one (build, combo, enemy)."""

    build_id: str
    build_name: str
    # Disc-stripped and SUPPORT-FOLDED (issue #121) — the per-candidate base
    # `_build_base_for_target` re-fills one disc at a time. It is *not* the
    # snapshot the simulator ran on: that one is support-free
    # (`SnapshotSplit.sim_base`), consumed during resolution and not carried
    # here, because nothing downstream of `resolve_rank_payload` simulates.
    scoring_base: BuildSnapshot
    enemy_snap: EnemySnapshot
    combo_steps: list[Step] | dict[int, list[Step]]
    conditions: ActiveConditions
    crit_mode: CritMode
    is_stunned: bool
    stun_dmg_mult: int
    weight: float
    baseline_damage: float
    disc_set_modifiers: dict[int, list[Modifier]]
    allowed_set_ids: list[int] | None
    build_discs: list[PlainBuildDisc]
    support_recompute_kit: SupportRecomputeKit | None = field(default=None)
    # Support-slot path only. Carries every OTHER support's team modifiers but
    # none of `support_recompute_kit`'s own — `score_support_disc_potential`
    # re-bakes those per candidate loadout, and
    # `rebuild_primary_snapshot_with_support` appends rather than merges
    # (issue #121; enforced by its own guard).
    primary_snap_without_support: BuildSnapshot | None = field(default=None)
    # Raw request-level context, passed through untouched so the rank result
    # can self-describe the keystone deep-link (DESIGN §3.4) without the
    # frontend having to positionally zip results back to the request.
    team_id: str | None = field(default=None)
    combo_id: str | None = field(default=None)
    enemy_profile_id: str | None = field(default=None)
    active_index: int | None = field(default=None)


@dataclass
class ResolvedRankPayload:
    """All data needed to run the rank pipeline without DB access."""

    contexts: list[ResolvedRankContext]
    inventory: list[DiscCandidate]
    disc_rarity_map: dict[str, str]  # disc_id → "S" / "A" / "B"


# ---------------------------------------------------------------------------
# Process-pool worker (module-level for pickling)
# ---------------------------------------------------------------------------


def _score_pair(args: tuple) -> tuple[str, str, float, float, float, float] | None:
    """Score one (disc, context) pair.

    Returns (disc_id, build_id, avg_pct, max_pct, abs_mean, abs_max) or None
    if set-filtered out. abs_mean/abs_max are baseline_damage + the
    improvement — recoverable without re-simulation (DESIGN_ranker_discless.md
    "The measure") and threaded through so _aggregate can compute norm_pct
    without re-deriving them.
    This function must be a top-level module function for pickling.
    """
    (
        disc,
        build_id,
        scoring_base,
        build_discs,
        enemy_snap,
        combo_steps,
        conditions,
        crit_mode,
        is_stunned,
        stun_dmg_mult,
        disc_set_modifiers,
        baseline_damage,
        disc_rarity,
        support_recompute_kit,
        primary_snap_without_support,
    ) = args

    if support_recompute_kit is not None:
        from app.services.support_scorer import score_support_disc_potential  # noqa: PLC0415

        result = score_support_disc_potential(
            primary_snap_without_support=primary_snap_without_support,
            kit=support_recompute_kit,
            support_build_discs=support_recompute_kit.build_discs,
            candidate=disc,
            disc_rarity=disc_rarity,
            enemy=enemy_snap,
            combo_steps=combo_steps,
            conditions=conditions,
            crit_mode=crit_mode,
            is_stunned=is_stunned,
            stun_dmg_mult=stun_dmg_mult,
        )
    else:
        base = _build_base_for_target(
            stripped=scoring_base,
            build_discs=build_discs,
            target=disc,
            disc_set_modifiers=disc_set_modifiers,
        )
        am_2pc_sets = (
            build_am_2pc_sets(disc_set_modifiers) if isinstance(combo_steps, dict) else {}
        )
        result = score_disc_potential(
            base_build=base,
            enemy=enemy_snap,
            combo_steps=combo_steps,
            disc=disc,
            disc_rarity=disc_rarity,
            conditions=conditions,
            crit_mode=crit_mode,
            is_stunned=is_stunned,
            stun_dmg_mult=stun_dmg_mult,
            baseline_damage=baseline_damage,
            build_discs=build_discs,
            am_2pc_sets=am_2pc_sets,
        )

    baseline = result.baseline_damage
    avg_pct = result.mean_improvement / baseline * 100 if baseline != 0.0 else 0.0
    max_pct = result.max_improvement / baseline * 100 if baseline != 0.0 else 0.0
    abs_mean = baseline + result.mean_improvement
    abs_max = baseline + result.max_improvement
    return (disc.disc_id, build_id, avg_pct, max_pct, abs_mean, abs_max)


# ---------------------------------------------------------------------------
# Sync pipeline runner
# ---------------------------------------------------------------------------


def run_rank_pipeline_with_progress(
    payload: ResolvedRankPayload,
    progress_callback: Callable[[RankProgress], None],
    *,
    max_workers: int | None = None,
) -> list[dict]:
    """Score every (disc, context) pair in the payload, aggregate, and return.

    Returns a list of serialisable dicts (one per disc) ready to be stored as
    the job result.  Progress callbacks fire on each completed future.
    """
    if not payload.inventory:
        return []

    # Build the list of (disc, context) work items filtered by set constraints.
    work_items: list[tuple[DiscCandidate, ResolvedRankContext]] = []
    for disc in payload.inventory:
        for ctx in payload.contexts:
            if ctx.allowed_set_ids is not None and disc.set_id not in ctx.allowed_set_ids:
                continue
            work_items.append((disc, ctx))

    # Per-disc accumulator: {disc_id: {build_id: (avg_pct, max_pct, abs_mean, abs_max)}}
    disc_results: _DiscBuildScores = {}

    total_work = len(work_items)
    start = time.perf_counter()
    done = 0

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for disc, ctx in work_items:
            args = (
                disc,
                ctx.build_id,
                ctx.scoring_base,
                ctx.build_discs,
                ctx.enemy_snap,
                ctx.combo_steps,
                ctx.conditions,
                ctx.crit_mode,
                ctx.is_stunned,
                ctx.stun_dmg_mult,
                ctx.disc_set_modifiers,
                ctx.baseline_damage,
                payload.disc_rarity_map.get(disc.disc_id, "S"),
                ctx.support_recompute_kit,
                ctx.primary_snap_without_support,
            )
            futures[pool.submit(_score_pair, args)] = (disc.disc_id, ctx.build_id)

        for future in as_completed(futures):
            done += 1
            result = future.result()
            disc_id, build_id, avg_pct, max_pct, abs_mean, abs_max = result
            disc_results.setdefault(disc_id, {})[build_id] = (avg_pct, max_pct, abs_mean, abs_max)

            elapsed = time.perf_counter() - start
            p = RankProgress(
                discs_done=done,
                discs_total=total_work,
                elapsed_seconds=elapsed,
            )
            progress_callback(p)

    return _aggregate(payload, disc_results)


_DiscBuildScores = dict[str, dict[str, tuple[float, float, float, float]]]


def _context_best_abs(
    payload: ResolvedRankPayload, disc_results: _DiscBuildScores
) -> dict[str, tuple[float, float]]:
    """Per-context (best_abs_mean, best_abs_max) — the max absolute damage across
    every disc scored in that context. Denominator for norm_pct (DESIGN_ranker_discless.md
    "The measure"): comparable across contexts because it carries no baseline term.
    """
    best: dict[str, tuple[float, float]] = {}
    for ctx in payload.contexts:
        abs_means = []
        abs_maxes = []
        for build_scores in disc_results.values():
            entry = build_scores.get(ctx.build_id)
            if entry is not None:
                _avg_pct, _max_pct, abs_mean, abs_max = entry
                abs_means.append(abs_mean)
                abs_maxes.append(abs_max)
        if abs_means:
            best[ctx.build_id] = (max(abs_means), max(abs_maxes))
    return best


def _aggregate(payload: ResolvedRankPayload, disc_results: _DiscBuildScores) -> list[dict]:
    """Convert per-(disc, build) results into ranked disc dicts."""
    output = []
    context_best_abs = _context_best_abs(payload, disc_results)

    for disc in payload.inventory:
        build_scores = disc_results.get(disc.disc_id)
        if not build_scores:
            continue  # filtered out by set constraint in all contexts

        per_build = []
        # (build_id, weight, norm_avg, norm_max) — always norm_pct (D3), the
        # baseline-free quantity the aggregates below are computed from. Distinct
        # from the *displayed* avg_pct/max_pct, which stays "vs equipped" for
        # geared contexts (D1) — see the field docs on DiscRankSchema.
        scored: list[tuple[str, float, float, float]] = []
        for ctx in payload.contexts:
            if ctx.build_id in build_scores:
                avg_pct, max_pct, abs_mean, abs_max = build_scores[ctx.build_id]
                discless = len(ctx.build_discs) == 0
                best_abs_mean, best_abs_max = context_best_abs[ctx.build_id]
                norm_avg = (
                    (abs_mean - best_abs_mean) / best_abs_mean * 100
                    if best_abs_mean != 0.0
                    else 0.0
                )
                norm_max = (
                    (abs_max - best_abs_max) / best_abs_max * 100 if best_abs_max != 0.0 else 0.0
                )
                if discless:
                    # D1 — disc-less contexts have no "vs equipped" baseline to
                    # speak of, so the displayed value is norm_pct too.
                    avg_pct, max_pct = norm_avg, norm_max
                per_build.append(
                    {
                        "build_id": ctx.build_id,
                        "avg_pct": avg_pct,
                        "max_pct": max_pct,
                        "reference_mode": "best" if discless else "equipped",
                        "team_id": ctx.team_id,
                        "combo_id": ctx.combo_id,
                        "enemy_profile_id": ctx.enemy_profile_id,
                        "active_index": ctx.active_index,
                    }
                )
                scored.append((ctx.build_id, ctx.weight, norm_avg, norm_max))
            else:
                per_build.append(
                    {
                        "build_id": ctx.build_id,
                        "avg_pct": None,
                        "max_pct": None,
                        "reference_mode": None,
                        "team_id": ctx.team_id,
                        "combo_id": ctx.combo_id,
                        "enemy_profile_id": ctx.enemy_profile_id,
                        "active_index": ctx.active_index,
                    }
                )

        if not scored:
            continue

        # D3/D4 — best_build_avg/best_build_max/portfolio_avg are derived from
        # norm_pct uniformly across every context, not the displayed avg_pct/
        # max_pct. They saturate at 0.0 for any disc that is the best candidate
        # in at least one context (D4), and are run-relative (D5): they move
        # when the scored inventory or context set changes, even for a disc
        # whose own score did not change.
        best_avg = max(avg for _, _, avg, _ in scored)
        best_avg_id = next(bid for bid, _, avg, _ in scored if avg == best_avg)
        best_max = max(mx for _, _, _, mx in scored)
        weight_sum = sum(w for _, w, _, _ in scored)
        portfolio = sum(w * avg for _, w, avg, _ in scored) / weight_sum if weight_sum > 0 else 0.0

        output.append(
            {
                "disc_id": disc.disc_id,
                "per_build": per_build,
                "best_build_avg": best_avg,
                "best_build_avg_build_id": best_avg_id,
                "best_build_max": best_max,
                "portfolio_avg": portfolio,
            }
        )

    return output


# ---------------------------------------------------------------------------
# Inventory filter helper
# ---------------------------------------------------------------------------


def _apply_rank_filters(discs: list, filters: RankFilters | None) -> list:
    """Return the subset of *discs* that pass all non-empty filter predicates.

    Accepts any objects with .slot, .rarity, .level, .main_stat_type, and
    .disc_set.hakushin_id — works with ORM Disc rows and lightweight fakes.
    Empty list / None field = no constraint; filters=None = no constraint.
    """
    if filters is None:
        return discs

    out = []
    for d in discs:
        if filters.slot is not None and d.slot != filters.slot:
            continue
        if filters.rarities:
            rarity_str = d.rarity.value if hasattr(d.rarity, "value") else str(d.rarity)
            if rarity_str not in filters.rarities:
                continue
        if filters.main_stats and d.main_stat_type not in filters.main_stats:
            continue
        if filters.set_ids and d.disc_set.hakushin_id not in filters.set_ids:
            continue
        if filters.level_value is not None:
            lv = filters.level_value
            if (
                (filters.level_mode == "min" and d.level < lv)
                or (filters.level_mode == "max" and d.level > lv)
                or (filters.level_mode == "exact" and d.level != lv)
            ):
                continue
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Async DB-resolve phase
# ---------------------------------------------------------------------------


async def resolve_rank_payload(  # noqa: PLR0912, PLR0915
    session: AsyncSession,
    body: RankRequest,
    build_repo: BuildRepository,
    combo_repo: ComboRepository,
    attack_repo: AttackRepository,
    enemy_repo: EnemyProfileRepository,
    support_builds_by_build_id: dict[str, list[Build]] | None = None,
    team_repo: TeamRepository | None = None,
) -> ResolvedRankPayload:
    """Async DB-fetch phase: resolve all entities and build the payload."""
    contexts: list[ResolvedRankContext] = []

    for ctx_schema in body.contexts:
        combo = await combo_repo.get_by_id(ctx_schema.combo_id)
        if combo is None:
            raise HTTPException(404, detail=f"Combo not found: {ctx_schema.combo_id}")
        if ctx_schema.build_id is None:
            if team_repo is None or ctx_schema.team_id is None:
                raise HTTPException(422, detail="build_id or team_id is required")
            _team = await team_repo.get_by_id(ctx_schema.team_id)
            if _team is None:
                raise HTTPException(404, detail=f"Team not found: {ctx_schema.team_id}")
            _members = [_team.build1, _team.build2, _team.build3]
            _team_members = _members
            build = _members[ctx_schema.active_index]
            if build is None:
                raise HTTPException(
                    422,
                    detail=f"No build at active_index {ctx_schema.active_index}",
                )
            _ctx_support_builds = select_support_members(_members, ctx_schema.active_index)
        else:
            _team_members = None
            build = await build_repo.get_by_id(ctx_schema.build_id)
            if build is None:
                raise HTTPException(404, detail=f"Build not found: {ctx_schema.build_id}")
            _ctx_support_builds = (
                support_builds_by_build_id.get(str(build.id))
                if support_builds_by_build_id is not None
                else None
            )
        enemy = await enemy_repo.get_by_id(ctx_schema.enemy_profile_id)
        if enemy is None:
            raise HTTPException(
                404,
                detail=f"Enemy profile not found: {ctx_schema.enemy_profile_id}",
            )
        agent = build.agent
        if agent is None:
            raise HTTPException(404, detail=f"Agent not found on build: {ctx_schema.build_id}")

        crit_mode = CRIT_MODES.get(ctx_schema.crit_mode)
        if crit_mode is None:
            raise HTTPException(422, detail=f"Invalid crit_mode: {ctx_schema.crit_mode}")

        mc_level = (
            ctx_schema.mindscape_level
            if ctx_schema.mindscape_level is not None
            else build.mindscape_level
        )
        # DESIGN §2.1 / issue #94: ctx_schema.stack_counts is the
        # request-scoped value, available here exactly like
        # ctx_schema.disabled_buffs above -- pass it through rather than
        # letting the snapshots fall back to the build row.
        #
        # Issue #121: rank used to build ONE snapshot with no `support_builds=`
        # at all, which was right for the simulator and wrong for the scorer --
        # its non-support-slot scoring base resolved ATK 2790 where the team
        # value is 3627, i.e. supports contributed nothing to any ranked disc
        # score. `build_snapshot_split` gives each consumer the snapshot it
        # needs; see SnapshotSplit in optimizer_pipeline.
        snaps = build_snapshot_split(
            build,
            agent,
            support_builds=_ctx_support_builds,
            refinement=ctx_schema.refinement,
            mindscape_level=mc_level,
            disabled_buffs=ctx_schema.disabled_buffs,
            stack_counts=dict(ctx_schema.stack_counts),
            custom_buffs=ctx_schema.custom_buffs,
        )

        element = agent.element.value if hasattr(agent.element, "value") else agent.element
        enemy_snap = enemy_snapshot_from_db(enemy, element)

        conditions = _parse_conditions(ctx_schema.active_conditions)
        conditions.stack_counts = ctx_schema.stack_counts

        # Load the build's equipped discs for set counting.
        stmt = select(Disc).where(Disc.build_id == build.id).options(selectinload(Disc.disc_set))
        result = await session.execute(stmt)
        equipped_discs = list(result.scalars().all())
        build_discs = [_plain_disc_from_orm(d) for d in equipped_discs if d.disc_set is not None]

        # Build disc set modifiers before stateful precompute (needed for am_2pc_sets).
        all_set_ids = {d.set_hakushin_id for d in build_discs}
        disc_set_modifiers = {sid: load_disc_set_modifiers(str(sid)) for sid in all_set_ids}

        from app.services.optimizer_pipeline import (  # noqa: PLC0415
            normalize_team_sequence,
            resolve_stateful_am_step_lists,
        )

        am_2pc_sets = build_am_2pc_sets(disc_set_modifiers)
        # Task 26 (issue #112): simulate the FULL team rotation -- cross-agent
        # mechanics need both halves of the team in one run -- and enforce
        # ownership on the resulting events via `score_owner_id` instead of by
        # deleting teammate steps before the simulator ever sees them.
        # `_team_members` is only known on the team path; on the legacy
        # `build_id` path the helper falls back to identity for role strings.
        _filtered_seq = normalize_team_sequence(
            combo.sequence,
            target_build_id=str(build.id),
            support_builds=_ctx_support_builds,
            active_index=ctx_schema.active_index,
            team_members=_team_members,
        )
        combo_steps = await resolve_stateful_am_step_lists(
            combo=combo,
            build=build,
            base_build=snaps.sim_base,
            enemy=enemy,
            attack_repo=attack_repo,
            inventory=build_discs,
            am_2pc_sets=am_2pc_sets,
            conditions=conditions,
            support_builds=_ctx_support_builds,
            sequence_override=_filtered_seq,
            disabled_buffs=ctx_schema.disabled_buffs,
            score_owner_id="dps",
        )
        coarse_am = resolve_coarse_am(
            # `agent_anomaly_mastery` is the agent's *base* AM
            # (snapshot_builder passes `agent.base_anomaly_mastery` straight
            # through), so this is identical on every member of the split.
            snaps.scoring_base.agent_anomaly_mastery,
            build_discs,
            am_2pc_sets,
        )
        steps_for_baseline = combo_steps[coarse_am]
        if ctx_schema.support_slot is not None:
            combo_steps = steps_for_baseline

        # Compute baseline: the build's damage with its current 6 discs.
        baseline_damage = evaluate_steps_total(
            build=snaps.scoring_snap,
            enemy=enemy_snap,
            steps=steps_for_baseline,
            conditions=conditions,
            crit_mode=crit_mode,
            is_stunned=ctx_schema.is_stunned,
            stun_dmg_mult=ctx_schema.stun_dmg_mult,
        )

        # Resolve support recompute kit when support_slot is requested.
        support_kit: SupportRecomputeKit | None = None
        primary_snap_without_support = None
        if ctx_schema.support_slot is not None:
            slot = ctx_schema.support_slot
            team_supports = (
                support_builds_by_build_id.get(str(build.id))
                if support_builds_by_build_id is not None
                else None
            ) or []
            idx = slot - 1
            if idx >= len(team_supports):
                raise HTTPException(
                    404,
                    detail=(f"Support slot {slot} is empty for build {ctx_schema.build_id}"),
                )
            support_build = team_supports[idx]
            sup_equipped = [
                _plain_disc_from_orm(d)
                for d in (support_build.discs or [])
                if d.disc_set is not None
            ]
            support_kit = build_support_recompute_kit(
                support_build, sup_equipped, disabled_buffs=ctx_schema.disabled_buffs
            )
            # `rebuild_primary_snapshot_with_support` *appends* this support's
            # team mods per candidate loadout, so the snapshot it is handed must
            # carry none of them -- but it should still carry every OTHER
            # teammate's, or a three-agent team's second support silently stops
            # buffing the primary while support slot 1 is being ranked.
            #
            # Before #121 this was `full_snap`, which had no supports folded in
            # at all: exactly-once for the scored support, zero for the others.
            # Now it is a scoring snapshot built from `_ctx_support_builds` minus
            # this one. Filtering by build **id** rather than by agent name
            # matters: `owner_name` is stamped on the primary's own kit / core /
            # W-Engine / disc modifiers too, so a name-based filter deletes the
            # primary's entire kit whenever the two agents share a name (#97;
            # pinned by test_primary_keeps_own_modifiers_when_it_also_fills_the_
            # support_slot). The exactly-once property is pinned by
            # tests/integration/test_rank_support_snapshot.py and enforced at
            # runtime by rebuild_primary_snapshot_with_support's own guard.
            _other_supports = [
                s for s in (_ctx_support_builds or []) if str(s.id) != str(support_build.id)
            ]
            primary_snap_without_support = build_snapshot_from_db(
                build,
                agent,
                refinement=ctx_schema.refinement,
                mindscape_level=mc_level,
                support_builds=_other_supports,
                disabled_buffs=ctx_schema.disabled_buffs,
                stack_counts=dict(ctx_schema.stack_counts),
                custom_buffs=ctx_schema.custom_buffs,
            )

        contexts.append(
            ResolvedRankContext(
                build_id=str(build.id),
                build_name=build.agent.name if build.agent else str(build.id),
                scoring_base=snaps.scoring_base,
                enemy_snap=enemy_snap,
                combo_steps=combo_steps,
                conditions=conditions,
                crit_mode=crit_mode,
                is_stunned=ctx_schema.is_stunned,
                stun_dmg_mult=ctx_schema.stun_dmg_mult,
                weight=ctx_schema.weight,
                baseline_damage=baseline_damage,
                disc_set_modifiers=disc_set_modifiers,
                allowed_set_ids=ctx_schema.allowed_set_ids,
                build_discs=build_discs,
                support_recompute_kit=support_kit,
                primary_snap_without_support=primary_snap_without_support,
                team_id=ctx_schema.team_id,
                combo_id=ctx_schema.combo_id,
                enemy_profile_id=ctx_schema.enemy_profile_id,
                active_index=ctx_schema.active_index,
            )
        )

    # Resolve the disc inventory (scope / disc_ids).
    if body.disc_ids is not None:
        stmt = select(Disc).where(Disc.id.in_(body.disc_ids)).options(selectinload(Disc.disc_set))
    elif body.scope == "all":
        stmt = select(Disc).options(selectinload(Disc.disc_set))
    else:
        # Default: build-equipped + unequipped.
        # Use the first context's build for "default" scoping.
        first_build_id = body.contexts[0].build_id
        stmt = (
            select(Disc)
            .where((Disc.build_id.is_(None)) | (Disc.build_id == first_build_id))
            .options(selectinload(Disc.disc_set))
        )
    result = await session.execute(stmt)
    discs = [d for d in result.scalars().all() if d.disc_set is not None]
    discs = _apply_rank_filters(discs, body.filters)

    # Enrich disc_set_modifiers with sets present in the inventory.
    for ctx in contexts:
        inv_set_ids = {d.disc_set.hakushin_id for d in discs}
        for sid in inv_set_ids:
            if sid not in ctx.disc_set_modifiers:
                ctx.disc_set_modifiers[sid] = load_disc_set_modifiers(str(sid))

    inventory = [_disc_to_candidate(d) for d in discs]
    disc_rarity_map = {
        str(d.id): (d.rarity.value if hasattr(d.rarity, "value") else str(d.rarity)) for d in discs
    }

    return ResolvedRankPayload(
        contexts=contexts,
        inventory=inventory,
        disc_rarity_map=disc_rarity_map,
    )
