"""Disc potential scorer endpoints (Phase 7b)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.dependencies import (
    DBSession,
    get_attack_repo,
    get_build_repo,
    get_combo_repo,
    get_enemy_repo,
    get_job_runner,
    get_owned_optimization_job_repo,
    get_owned_team_repo,
)
from app.middleware.rate_limit import COMPUTE_LIMIT, JOB_LIMIT, limiter
from app.models.disc import Disc
from app.repositories.attack import AttackRepository
from app.repositories.build import BuildRepository, ComboRepository, EnemyProfileRepository
from app.repositories.optimization_job import (
    MAX_ACTIVE_JOBS_PER_USER,
    OptimizationJobRepository,
)
from app.repositories.team import TeamRepository
from app.schemas.optimization_job import OptimizationJobSummary
from app.schemas.scorer import (
    DiscScoreRequest,
    DiscScoreResponse,
    DiscScoreSchema,
    InventoryScoreRequest,
    InventoryScoreResponse,
    RankRequest,
)
from app.services.am_variants import build_am_2pc_sets, resolve_coarse_am
from app.services.damage_dag_service import evaluate_steps_total
from app.services.disc_scorer import score_disc_potential
from app.services.job_runner import JobRunner
from app.services.optimizer_pipeline import (
    _CRIT_MODES,
    _disc_to_candidate,
    _load_set_modifiers,
    _parse_conditions,
    build_snapshot_split,
    normalize_team_sequence,
    resolve_stateful_am_step_lists,
)
from app.services.rank_pipeline import resolve_rank_payload
from app.services.scorer_support import (
    _build_base_for_target,
    _disc_rarity_str,
)
from app.services.snapshot_builder import enemy_snapshot_from_db
from app.services.support_selection import select_support_members

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.build import Build, Combo, EnemyProfile
    from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
    from app.services.combo_types import Step
    from app.services.damage_calculator import CritMode
    from app.services.disc_scorer import DiscScoreResult
    from app.services.modifiers import ActiveConditions, Modifier

router = APIRouter(prefix="/scorer", tags=["scorer"])


def _result_to_schema(
    disc_id: str,
    result: DiscScoreResult,
    *,
    include_distribution: bool,
) -> DiscScoreSchema:
    return DiscScoreSchema(
        disc_id=disc_id,
        rolls_used=result.rolls_used,
        remaining_rolls=result.remaining_rolls,
        current_damage=result.current_damage,
        baseline_damage=result.baseline_damage,
        max_improvement=result.max_improvement,
        mean_improvement=result.mean_improvement,
        stddev_improvement=result.stddev_improvement,
        p10=result.p10,
        p50=result.p50,
        p90=result.p90,
        distribution=(list(result.distribution) if include_distribution else None),
    )


async def _fetch_build_discs(session: DBSession, build_id: str) -> list[Disc]:
    """Build's equipped discs with disc_set eager-loaded for set counting."""
    stmt = select(Disc).where(Disc.build_id == build_id).options(selectinload(Disc.disc_set))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _fetch_target_discs(
    session: DBSession,
    disc_ids: list[str],
) -> list[Disc]:
    stmt = select(Disc).where(Disc.id.in_(disc_ids)).options(selectinload(Disc.disc_set))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _resolve_context(
    *,
    body: DiscScoreRequest | InventoryScoreRequest,
    combo_repo: ComboRepository,
    build_repo: BuildRepository,
    enemy_repo: EnemyProfileRepository,
    team_repo: TeamRepository,
) -> tuple[Combo, Build, EnemyProfile, Agent, list[Build | None]]:
    combo = await combo_repo.get_by_id(body.combo_id)
    if combo is None:
        raise HTTPException(status_code=404, detail="Combo not found")
    team = await team_repo.get_by_id(combo.team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found for combo")
    members = [team.build1, team.build2, team.build3]
    build = members[body.active_index]
    if build is None:
        raise HTTPException(status_code=404, detail="Build not found at active_index")
    enemy = await enemy_repo.get_by_id(body.enemy_profile_id)
    if enemy is None:
        raise HTTPException(status_code=404, detail="Enemy profile not found")
    agent = build.agent
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found on build")
    # Task 26 (issue #112): the members were always loaded here and thrown away,
    # so both scorer endpoints simulated with no teammates at all. Returned now
    # so the simulation can see the whole team.
    return combo, build, enemy, agent, members


def _current_build_damage(
    *,
    scoring_snap: BuildSnapshot,
    enemy_snap: EnemySnapshot,
    combo_steps: list[Step] | dict[int, list[Step]],
    conditions: ActiveConditions,
    body: DiscScoreRequest | InventoryScoreRequest,
    build_discs: list[Disc] | None = None,
    am_2pc_sets: dict[int, list[Modifier]] | None = None,
) -> float:
    """Combo damage of the build exactly as it stands now (no swap, no leveling).

    This is the reference point the scorer compares candidates against:
    a candidate's "improvement" answers "how much better is this build
    if I swap in and level this disc?".
    """
    crit_mode = _resolve_crit_mode(body.crit_mode)

    if isinstance(combo_steps, dict):
        if build_discs is None:
            raise ValueError("build_discs must be provided for multiplexed stateful calculation")
        disc_cands = [_disc_to_candidate(d) for d in build_discs if d.disc_set is not None]
        coarse_am = resolve_coarse_am(
            scoring_snap.agent_anomaly_mastery,
            disc_cands,
            am_2pc_sets or {},
        )
        steps = combo_steps.get(coarse_am, next(iter(combo_steps.values())))
    else:
        steps = combo_steps

    return evaluate_steps_total(
        build=scoring_snap,
        enemy=enemy_snap,
        steps=steps,
        conditions=conditions,
        crit_mode=crit_mode,
        is_stunned=body.is_stunned,
        stun_dmg_mult=body.stun_dmg_mult,
    )


def _resolve_crit_mode(raw: str) -> CritMode:
    crit_mode = _CRIT_MODES.get(raw)
    if crit_mode is None:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid crit_mode: {raw}",
        )
    return crit_mode


def _score_one(
    *,
    target_disc: Disc,
    build_discs: list[Disc],
    scoring_base: BuildSnapshot,
    enemy_snap: EnemySnapshot,
    combo_steps: list[Step] | dict[int, list[Step]],
    disc_set_modifiers: dict[int, list[Modifier]],
    conditions: ActiveConditions,
    baseline_damage: float,
    body: DiscScoreRequest | InventoryScoreRequest,
) -> DiscScoreSchema:
    candidate = _disc_to_candidate(target_disc)
    base_for_scorer = _build_base_for_target(
        stripped=scoring_base,
        build_discs=build_discs,
        target=candidate,
        disc_set_modifiers=disc_set_modifiers,
    )
    crit_mode = _resolve_crit_mode(body.crit_mode)
    am_2pc_sets = build_am_2pc_sets(disc_set_modifiers) if isinstance(combo_steps, dict) else {}
    result = score_disc_potential(
        base_build=base_for_scorer,
        enemy=enemy_snap,
        combo_steps=combo_steps,
        disc=candidate,
        disc_rarity=_disc_rarity_str(target_disc),
        conditions=conditions,
        crit_mode=crit_mode,
        is_stunned=body.is_stunned,
        stun_dmg_mult=body.stun_dmg_mult,
        baseline_damage=baseline_damage,
        build_discs=build_discs,
        am_2pc_sets=am_2pc_sets,
    )
    return _result_to_schema(
        candidate.disc_id,
        result,
        include_distribution=body.include_distribution,
    )


@router.post("/disc", response_model=DiscScoreResponse)
@limiter.limit(COMPUTE_LIMIT)
async def score_disc_endpoint(
    request: Request,
    body: DiscScoreRequest,
    session: DBSession,
    combo_repo: Annotated[ComboRepository, Depends(get_combo_repo)],
    build_repo: Annotated[BuildRepository, Depends(get_build_repo)],
    attack_repo: Annotated[AttackRepository, Depends(get_attack_repo)],
    enemy_repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
    team_repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
) -> DiscScoreResponse:
    """Score a single disc's upgrade potential against a saved combo."""
    combo, build, enemy, agent, team_members = await _resolve_context(
        body=body,
        combo_repo=combo_repo,
        build_repo=build_repo,
        enemy_repo=enemy_repo,
        team_repo=team_repo,
    )

    targets = await _fetch_target_discs(session, [body.disc_id])
    if not targets:
        raise HTTPException(status_code=404, detail="Disc not found")
    target_disc = targets[0]

    build_discs = await _fetch_build_discs(session, str(build.id))

    mc_level = body.mindscape_level if body.mindscape_level is not None else build.mindscape_level
    _supports = select_support_members(team_members, body.active_index)
    # DESIGN §2.1 / issue #94: body.stack_counts is the request-scoped value,
    # available here exactly like body.disabled_buffs above -- pass it
    # through rather than letting the snapshots fall back to the build row.
    #
    # Issue #121: this endpoint used to build ONE support-free snapshot and hand
    # it to both the simulator (correct) and the scorer (wrong -- team buffs were
    # absent from every scored number). `build_snapshot_split` gives each
    # consumer the snapshot it needs; see SnapshotSplit in optimizer_pipeline.
    snaps = build_snapshot_split(
        build,
        agent,
        support_builds=_supports,
        refinement=body.refinement,
        mindscape_level=mc_level,
        disabled_buffs=body.disabled_buffs,
        stack_counts=dict(body.stack_counts),
        custom_buffs=body.custom_buffs,
    )

    element = agent.element.value if hasattr(agent.element, "value") else agent.element
    enemy_snap = enemy_snapshot_from_db(enemy, element)

    inventory = [_disc_to_candidate(target_disc)]
    disc_set_modifiers = _load_set_modifiers(
        [
            *(_disc_to_candidate(d) for d in build_discs if d.disc_set is not None),
            *inventory,
        ]
    )

    conditions = _parse_conditions(body.active_conditions)
    conditions.stack_counts = body.stack_counts

    am_2pc_sets = build_am_2pc_sets(disc_set_modifiers)
    # Task 26 (issue #112). These two call sites passed neither a sequence nor
    # any support build, so a team combo's teammate steps fell back to the target
    # build (`optimizer_pipeline` `_member_map.get(step_agent_id, build)`) and
    # resolved their move names against the target agent's own attack table --
    # yielding nothing. Lumiflux was as inert here as it was on `/optimize`, by a
    # different route. Simulate the real team, then keep only the scored build's
    # own events.
    _seq = normalize_team_sequence(
        combo.sequence,
        target_build_id=str(build.id),
        support_builds=_supports,
        active_index=body.active_index,
        team_members=team_members,
    )
    combo_steps = await resolve_stateful_am_step_lists(
        combo=combo,
        build=build,
        base_build=snaps.sim_base,
        enemy=enemy,
        attack_repo=attack_repo,
        inventory=inventory,
        am_2pc_sets=am_2pc_sets,
        conditions=conditions,
        support_builds=_supports,
        sequence_override=_seq,
        disabled_buffs=body.disabled_buffs,
        score_owner_id="dps",
    )

    baseline_damage = _current_build_damage(
        scoring_snap=snaps.scoring_snap,
        enemy_snap=enemy_snap,
        combo_steps=combo_steps,
        conditions=conditions,
        body=body,
        build_discs=build_discs,
        am_2pc_sets=am_2pc_sets,
    )

    schema = _score_one(
        target_disc=target_disc,
        build_discs=build_discs,
        scoring_base=snaps.scoring_base,
        enemy_snap=enemy_snap,
        combo_steps=combo_steps,
        disc_set_modifiers=disc_set_modifiers,
        conditions=conditions,
        baseline_damage=baseline_damage,
        body=body,
    )
    return DiscScoreResponse(
        combo_id=str(combo.id),
        combo_name=combo.name,
        agent_name=agent.name,
        enemy_name=enemy.name,
        score=schema,
    )


@router.post("/inventory", response_model=InventoryScoreResponse)
@limiter.limit(COMPUTE_LIMIT)
async def score_inventory_endpoint(
    request: Request,
    body: InventoryScoreRequest,
    session: DBSession,
    combo_repo: Annotated[ComboRepository, Depends(get_combo_repo)],
    build_repo: Annotated[BuildRepository, Depends(get_build_repo)],
    attack_repo: Annotated[AttackRepository, Depends(get_attack_repo)],
    enemy_repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
    team_repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
) -> InventoryScoreResponse:
    """Score a list of discs (or all available discs) against a combo."""
    combo, build, enemy, agent, team_members = await _resolve_context(
        body=body,
        combo_repo=combo_repo,
        build_repo=build_repo,
        enemy_repo=enemy_repo,
        team_repo=team_repo,
    )

    if body.disc_ids is not None:
        targets = await _fetch_target_discs(session, body.disc_ids)
    elif body.scope == "all":
        stmt = select(Disc).options(selectinload(Disc.disc_set))
        result = await session.execute(stmt)
        targets = list(result.scalars().all())
    else:
        # Default scope: build's equipped discs + every unequipped disc.
        stmt = (
            select(Disc)
            .where((Disc.build_id.is_(None)) | (Disc.build_id == build.id))
            .options(selectinload(Disc.disc_set))
        )
        result = await session.execute(stmt)
        targets = list(result.scalars().all())

    if body.allowed_set_ids is not None:
        allowed = set(body.allowed_set_ids)
        targets = [
            d for d in targets if d.disc_set is not None and d.disc_set.hakushin_id in allowed
        ]

    build_discs = await _fetch_build_discs(session, str(build.id))

    mc_level = body.mindscape_level if body.mindscape_level is not None else build.mindscape_level
    _supports = select_support_members(team_members, body.active_index)
    # DESIGN §2.1 / issue #94: body.stack_counts is the request-scoped value,
    # available here exactly like body.disabled_buffs above -- pass it
    # through rather than letting the snapshots fall back to the build row.
    #
    # Issue #121: this endpoint used to build ONE support-free snapshot and hand
    # it to both the simulator (correct) and the scorer (wrong -- team buffs were
    # absent from every scored number). `build_snapshot_split` gives each
    # consumer the snapshot it needs; see SnapshotSplit in optimizer_pipeline.
    snaps = build_snapshot_split(
        build,
        agent,
        support_builds=_supports,
        refinement=body.refinement,
        mindscape_level=mc_level,
        disabled_buffs=body.disabled_buffs,
        stack_counts=dict(body.stack_counts),
        custom_buffs=body.custom_buffs,
    )

    element = agent.element.value if hasattr(agent.element, "value") else agent.element
    enemy_snap = enemy_snapshot_from_db(enemy, element)

    inventory_candidates = [_disc_to_candidate(d) for d in targets]
    base_candidates = [_disc_to_candidate(d) for d in build_discs if d.disc_set is not None]
    disc_set_modifiers = _load_set_modifiers(
        [*base_candidates, *inventory_candidates],
    )

    conditions = _parse_conditions(body.active_conditions)
    conditions.stack_counts = body.stack_counts

    am_2pc_sets = build_am_2pc_sets(disc_set_modifiers)
    # Task 26 (issue #112). These two call sites passed neither a sequence nor
    # any support build, so a team combo's teammate steps fell back to the target
    # build (`optimizer_pipeline` `_member_map.get(step_agent_id, build)`) and
    # resolved their move names against the target agent's own attack table --
    # yielding nothing. Lumiflux was as inert here as it was on `/optimize`, by a
    # different route. Simulate the real team, then keep only the scored build's
    # own events.
    _seq = normalize_team_sequence(
        combo.sequence,
        target_build_id=str(build.id),
        support_builds=_supports,
        active_index=body.active_index,
        team_members=team_members,
    )
    combo_steps = await resolve_stateful_am_step_lists(
        combo=combo,
        build=build,
        base_build=snaps.sim_base,
        enemy=enemy,
        attack_repo=attack_repo,
        inventory=inventory_candidates,
        am_2pc_sets=am_2pc_sets,
        conditions=conditions,
        support_builds=_supports,
        sequence_override=_seq,
        disabled_buffs=body.disabled_buffs,
        score_owner_id="dps",
    )

    baseline_damage = _current_build_damage(
        scoring_snap=snaps.scoring_snap,
        enemy_snap=enemy_snap,
        combo_steps=combo_steps,
        conditions=conditions,
        body=body,
        build_discs=build_discs,
        am_2pc_sets=am_2pc_sets,
    )

    scores = [
        _score_one(
            target_disc=target,
            build_discs=build_discs,
            scoring_base=snaps.scoring_base,
            enemy_snap=enemy_snap,
            combo_steps=combo_steps,
            disc_set_modifiers=disc_set_modifiers,
            conditions=conditions,
            baseline_damage=baseline_damage,
            body=body,
        )
        for target in targets
    ]
    scores.sort(key=lambda s: s.mean_improvement, reverse=True)

    return InventoryScoreResponse(
        combo_id=str(combo.id),
        combo_name=combo.name,
        agent_name=agent.name,
        enemy_name=enemy.name,
        scores=scores,
    )


@router.post("/rank", response_model=OptimizationJobSummary, status_code=202)
@limiter.limit(JOB_LIMIT)
async def submit_rank_job(
    request: Request,
    body: RankRequest,
    session: DBSession,
    build_repo: Annotated[BuildRepository, Depends(get_build_repo)],
    combo_repo: Annotated[ComboRepository, Depends(get_combo_repo)],
    attack_repo: Annotated[AttackRepository, Depends(get_attack_repo)],
    enemy_repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
    job_repo: Annotated[OptimizationJobRepository, Depends(get_owned_optimization_job_repo)],
    runner: Annotated[JobRunner, Depends(get_job_runner)],
    team_repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
) -> OptimizationJobSummary:
    """Submit a disc rank job; returns 202 + queued job summary.

    A single-context request is the single-build case (D-RANK-6).
    Poll the job via ``GET /optimizer/jobs/{job_id}``.
    """
    active = await job_repo.count_active()
    if active >= MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=(
                f"You already have {active} active jobs "
                f"(max {MAX_ACTIVE_JOBS_PER_USER}). "
                "Cancel one or wait for it to finish before submitting another."
            ),
        )

    # Resolve explicit support builds from teams for contexts that supply team_id.
    support_builds_by_build_id = None
    if any(ctx.team_id for ctx in body.contexts):
        support_builds_by_build_id = {}
        for ctx in body.contexts:
            if ctx.team_id:
                team = await team_repo.get_by_id(ctx.team_id)
                if team is None:
                    raise HTTPException(404, detail=f"Team not found: {ctx.team_id}")
                members = [team.build1, team.build2, team.build3]
                idx = ctx.active_index
                _target_member = members[idx]
                # Never let the scored build be its own support. This site was
                # hand-guarded first, in the #120 review; issue #133 moved the rule
                # into `select_support_members` and applied it to the other seven
                # call sites, so this now shares one implementation with them
                # rather than being the single narrow exception it used to be.
                supports = select_support_members(members, idx)
                _build_key = ctx.build_id or (str(_target_member.id) if _target_member else None)
                if _build_key is not None:
                    support_builds_by_build_id[_build_key] = supports

    payload = await resolve_rank_payload(
        session,
        body,
        build_repo=build_repo,
        combo_repo=combo_repo,
        attack_repo=attack_repo,
        enemy_repo=enemy_repo,
        support_builds_by_build_id=support_builds_by_build_id,
        team_repo=team_repo,
    )

    build_names = ", ".join(ctx.build_name for ctx in payload.contexts)
    job = await job_repo.create(
        {
            "status": "queued",
            "job_type": "rank",
            "request": body.model_dump(mode="json"),
            "agent_name": build_names,
            "enemy_name": "",
            "combo_name": "",
        }
    )

    runner.submit_rank_job(str(job.id), payload)

    return OptimizationJobSummary.model_validate(job)
