"""Damage calculation endpoints.

Three tiers:
1. Raw calc  — /calculate, /anomaly, /compare — stateless, no DB
2. Build calc — /build, /build/anomaly — fetches from DB, loads modifier JSONs
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_attack_repo, get_build_repo, get_enemy_repo
from app.models.enums import PotentialVariant
from app.repositories.attack import AttackRepository
from app.repositories.build import BuildRepository, EnemyProfileRepository
from app.schemas.damage import (
    CUSTOM_BUFF_STATS,
    AnomalyDamageRequest,
    AnomalyDamageResponse,
    BuildAnomalyRequest,
    BuildAnomalyResponse,
    BuildDamageRequest,
    BuildDamageResponse,
    CompareRequest,
    CompareResponse,
    StandardDamageRequest,
    StandardDamageResponse,
)
from app.services.anomaly_simulator import simulate_single_hit
from app.services.build_damage_service import (
    calculate_build_anomaly,
    resolve_build_stats,
)
from app.services.damage_calculator import (
    AnomalyType,
    CritMode,
    calculate_anomaly_damage,
    calculate_standard_damage,
)
from app.services.modifiers import ActiveConditions, Condition
from app.services.snapshot_builder import (
    attack_multiplier_at_level,
    build_snapshot_from_db,
    enemy_snapshot_from_db,
)

router = APIRouter(prefix="/damage", tags=["damage"])

_CRIT_MODES = {"expected": CritMode.EXPECTED, "crit": CritMode.CRIT, "no_crit": CritMode.NO_CRIT}
_ANOMALY_TYPES = {t.value: t for t in AnomalyType}


@router.get("/custom-buff-stats", response_model=list[str])
async def list_custom_buff_stats() -> list[str]:
    """Stat keys a custom (stage) buff may target — the stage-buff editor's picker.

    Served rather than hardcoded client-side so the picker cannot drift from the buff
    resolver's own vocabulary. That drift is the exact failure Task B2 exists to prevent:
    a stat outside these buckets is accepted, displayed, and then silently ignored by the
    calc, and a user whose numbers do not move has no way to tell "the buff did nothing"
    from "the buff is not modelled". `docs/RESEARCH_custom_buff_stats.md` measured each
    key end to end.
    """
    return sorted(CUSTOM_BUFF_STATS)


def _calc_standard(req: StandardDamageRequest) -> StandardDamageResponse:
    mode = _CRIT_MODES.get(req.crit_mode)
    if mode is None:
        raise HTTPException(422, f"Invalid crit_mode: {req.crit_mode}")
    result = calculate_standard_damage(
        scaling_stat=req.scaling_stat,
        multiplier=req.multiplier,
        dmg_bonuses=req.dmg_bonuses,
        crit_rate=req.crit_rate,
        crit_dmg=req.crit_dmg,
        crit_mode=mode,
        attacker_level=req.attacker_level,
        enemy_base_def=req.enemy_base_def,
        enemy_level=req.enemy_level,
        pen_ratio=req.pen_ratio,
        pen_flat=req.pen_flat,
        def_ignore=req.def_ignore,
        enemy_res=req.enemy_res,
        res_reduction=req.res_reduction,
        res_ignore=req.res_ignore,
        vulnerability_bonuses=req.vulnerability_bonuses,
        is_stunned=req.is_stunned,
        stun_dmg_mult=req.stun_dmg_mult,
    )
    return StandardDamageResponse(
        total=result.total,
        base_dmg=result.base_dmg,
        boost_mult=result.boost_mult,
        crit_mult=result.crit_mult,
        def_mult=result.def_mult,
        res_mult=result.res_mult,
        vulnerability_mult=result.vulnerability_mult,
        stun_mult=result.stun_mult,
    )


@router.post("/calculate", response_model=StandardDamageResponse)
async def calculate_damage(body: StandardDamageRequest) -> StandardDamageResponse:
    """Calculate standard (non-anomaly) damage from raw stats — no DB lookups."""
    return _calc_standard(body)


@router.post("/anomaly", response_model=AnomalyDamageResponse)
async def calculate_anomaly(body: AnomalyDamageRequest) -> AnomalyDamageResponse:
    """Calculate anomaly damage from raw stats — no DB lookups."""
    anom_type = _ANOMALY_TYPES.get(body.anomaly_type)
    if anom_type is None:
        raise HTTPException(422, f"Invalid anomaly_type: {body.anomaly_type}")
    result = calculate_anomaly_damage(
        anomaly_type=anom_type,
        atk=body.atk,
        anomaly_proficiency=body.anomaly_proficiency,
        attacker_level=body.attacker_level,
        dmg_bonuses=body.dmg_bonuses,
        anomaly_dmg_bonus=body.anomaly_dmg_bonus,
        enemy_base_def=body.enemy_base_def,
        enemy_level=body.enemy_level,
        pen_ratio=body.pen_ratio,
        pen_flat=body.pen_flat,
        def_ignore=body.def_ignore,
        enemy_res=body.enemy_res,
        res_reduction=body.res_reduction,
        res_ignore=body.res_ignore,
        vulnerability_bonuses=body.vulnerability_bonuses,
        is_stunned=body.is_stunned,
        stun_dmg_mult=body.stun_dmg_mult,
        procs=body.procs,
    )
    return AnomalyDamageResponse(
        per_proc=result.per_proc,
        total=result.total,
        procs=result.procs,
        base_dmg=result.base_dmg,
        boost_mult=result.boost_mult,
        def_mult=result.def_mult,
        res_mult=result.res_mult,
        vulnerability_mult=result.vulnerability_mult,
        stun_mult=result.stun_mult,
        anomaly_prof_mult=result.anomaly_prof_mult,
        level_mult=result.level_mult,
        anomaly_boost_mult=result.anomaly_boost_mult,
    )


@router.post("/compare", response_model=CompareResponse)
async def compare_damage(body: CompareRequest) -> CompareResponse:
    """Calculate two standard-damage scenarios and return their delta."""
    a = _calc_standard(body.a)
    b = _calc_standard(body.b)
    diff = b.total - a.total
    diff_pct = (diff / a.total * 100) if a.total > 0 else 0.0
    return CompareResponse(a=a, b=b, diff=diff, diff_pct=round(diff_pct, 2))


# ---------------------------------------------------------------------------
# Build-aware endpoints (DB + modifier JSONs → snapshot → damage calc)
# ---------------------------------------------------------------------------

# Map skill_key to index in build.skill_levels ("basic,dodge,special,chain,core")
_SKILL_KEY_TO_INDEX = {
    "Basic": 0,
    "Dodge": 1,
    "Assist": 1,
    "Special": 2,
    "EXSpecial": 2,
    "Chain": 3,
    "Ultimate": 3,
    "Core": 4,
}


def _parse_conditions(raw: list[str]) -> ActiveConditions:
    """Convert raw condition strings to ActiveConditions.

    ``ALWAYS`` is unioned in unconditionally — see the docstring on
    ``optimizer_pipeline._parse_conditions`` for why an empty-list-only
    fallback is wrong.
    """
    condition_map = {c.value: c for c in Condition}
    active = set()
    for s in raw:
        c = condition_map.get(s)
        if c is not None:
            active.add(c)
    active.add(Condition.ALWAYS)
    return ActiveConditions(active=active)


def _skill_level_from_build(build: object, attack: object, override: int | None) -> int:
    """Resolve the skill level for an attack from the build or override."""
    if override is not None:
        return override
    levels_str = build.skill_levels or "12,12,12,12,12"
    levels = [int(x) for x in levels_str.split(",")]
    idx = _SKILL_KEY_TO_INDEX.get(attack.skill_key, 0)
    return levels[idx] if idx < len(levels) else 12


@router.post("/build", response_model=BuildDamageResponse)
async def calculate_build(
    body: BuildDamageRequest,
    build_repo: Annotated[BuildRepository, Depends(get_build_repo)],
    attack_repo: Annotated[AttackRepository, Depends(get_attack_repo)],
    enemy_repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
) -> BuildDamageResponse:
    """Calculate standard damage for a saved build + attack + enemy."""
    build = await build_repo.get_by_id(body.build_id)
    if build is None:
        raise HTTPException(404, "Build not found")

    attack = await attack_repo.get_by_id(body.attack_id)
    if attack is None:
        raise HTTPException(404, "Attack not found")

    # A primary-key fetch takes part in no WHERE clause, so `visible_to` cannot reach
    # it: a client holding an attack id from the *other* Potential state would get that
    # row back and the calc would proceed on a move this build does not have (#90,
    # DESIGN §5.3). Validate after fetch instead. 404 rather than 400 — from the
    # build's point of view the move genuinely does not exist.
    if not PotentialVariant.for_rank(build.potential_rank).includes(attack.potential):
        raise HTTPException(
            404,
            f"Attack not in this build's kit: {attack.name!r} belongs to the "
            f"{attack.potential} Potential variant, but the build is at rank "
            f"{build.potential_rank}",
        )

    enemy = await enemy_repo.get_by_id(body.enemy_profile_id)
    if enemy is None:
        raise HTTPException(404, "Enemy profile not found")

    agent = build.agent
    if agent is None:
        raise HTTPException(404, "Agent not found on build")

    # Build snapshots
    mc_level = body.mindscape_level if body.mindscape_level is not None else build.mindscape_level
    # DESIGN §2.1 -- stack_counts comes from the request context only; passed
    # straight into build_snapshot_from_db so simulate_single_hit's internal
    # per-hit resolution (which reads stack_counts off the snapshot, not off
    # `conditions` below) sees it too.
    snap = build_snapshot_from_db(
        build,
        agent,
        refinement=body.refinement,
        mindscape_level=mc_level,
        disabled_buffs=body.buff_context.disabled_buffs,
        stack_counts=dict(body.buff_context.stack_counts),
        custom_buffs=body.buff_context.custom_buffs,
    )

    # Resolve skill level and multiplier
    skill_level = _skill_level_from_build(build, attack, body.skill_level)
    multiplier = attack_multiplier_at_level(attack, skill_level)

    # Resolve conditions for display-stat resolution.
    conditions = _parse_conditions(body.buff_context.active_conditions)
    conditions.stack_counts = dict(body.buff_context.stack_counts)

    # Route through the stateful engine degenerate-hit seam (Task 2 / Phase 4).
    #
    # is_stunned: injected as a runtime attribute read by getattr(enemy,"is_stunned",False)
    #   inside simulate().  Not a mapped column; SQLAlchemy will not flush it.
    # stun_dmg_mult: derived from enemy.stun_dmg_taken_ratio (default 5000 → 15000),
    #   matching the endpoint default of 15000.  Custom stun_dmg_mult request values
    #   are not forwarded — the enemy model value is used.
    # crit_mode: the stateful engine always uses CritMode.EXPECTED; the crit_mode
    #   request param is intentionally ignored on this path.
    enemy.is_stunned = body.is_stunned  # type: ignore[attr-defined]
    sim_result = simulate_single_hit(
        build=snap,
        attacks=[attack],
        enemy=enemy,
        conditions=body.buff_context.active_conditions,
        # P-F1 (hardening Task 17): the response echoes this as "the element
        # actually used" -- passing it here is what makes that description true.
        fluxed_element=body.fluxed_element,
    )

    hit_ev = next((e for e in sim_result.events if e.kind == "hit"), None)
    if hit_ev is None:
        raise HTTPException(500, "Stateful engine produced no hit event for this attack")

    det = hit_ev.detail or {}
    total = sim_result.totals.get("total", 0)

    # Resolve display stats (crit_rate, crit_dmg, pen_ratio) — not in SimulationResult.
    disp_stats = resolve_build_stats(snap, conditions)

    return BuildDamageResponse(
        total=total,
        base_dmg=det.get("base_dmg", 0),
        boost_mult=det.get("boost_mult", 10000),
        crit_mult=det.get("crit_mult", 10000),
        def_mult=det.get("def_mult", 10000),
        res_mult=det.get("res_mult", 10000),
        vulnerability_mult=det.get("vulnerability_mult", 10000),
        stun_mult=det.get("stun_mult", 10000),
        total_atk=det.get("effective_atk", disp_stats.atk),
        total_crit_rate=disp_stats.crit_rate,
        total_crit_dmg=disp_stats.crit_dmg,
        total_pen_ratio=disp_stats.pen_ratio,
        sheer_force=det.get("sheer_force"),
        attack_name=attack.name,
        attack_multiplier=multiplier,
        agent_name=agent.name,
        enemy_name=enemy.name,
        # This endpoint has no team roster to derive Attribute Flux from (a
        # single build_id, no team_id) — the derived value is always null;
        # only an explicit override is ever echoed here (DESIGN §5.3, Task 8).
        fluxed_element=body.fluxed_element,
    )


@router.post("/build/anomaly", response_model=BuildAnomalyResponse)
async def calculate_build_anomaly_endpoint(
    body: BuildAnomalyRequest,
    build_repo: Annotated[BuildRepository, Depends(get_build_repo)],
    enemy_repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
) -> BuildAnomalyResponse:
    """Calculate anomaly damage for a saved build."""
    build = await build_repo.get_by_id(body.build_id)
    if build is None:
        raise HTTPException(404, "Build not found")

    enemy = await enemy_repo.get_by_id(body.enemy_profile_id)
    if enemy is None:
        raise HTTPException(404, "Enemy profile not found")

    agent = build.agent
    if agent is None:
        raise HTTPException(404, "Agent not found on build")

    mc_level = body.mindscape_level if body.mindscape_level is not None else build.mindscape_level
    # Not named in issue #94's call-site list (calculate_build_anomaly resolves
    # stacks from `conditions.stack_counts` below, not from the snapshot), but
    # the request value is right here -- pass it too so this site doesn't
    # become the "next call site that silently inherits the build row".
    snap = build_snapshot_from_db(
        build,
        agent,
        refinement=body.refinement,
        mindscape_level=mc_level,
        disabled_buffs=body.buff_context.disabled_buffs,
        stack_counts=dict(body.buff_context.stack_counts),
        custom_buffs=body.buff_context.custom_buffs,
    )

    element = agent.element.value if hasattr(agent.element, "value") else agent.element
    enemy_snap = enemy_snapshot_from_db(enemy, element)

    conditions = _parse_conditions(body.buff_context.active_conditions)
    conditions.stack_counts = dict(body.buff_context.stack_counts)

    result = calculate_build_anomaly(
        build=snap,
        enemy=enemy_snap,
        anomaly_type=body.anomaly_type,
        conditions=conditions,
        procs=body.procs,
        is_stunned=body.is_stunned,
        stun_dmg_mult=body.stun_dmg_mult,
    )

    return BuildAnomalyResponse(
        per_proc=result.damage.per_proc,
        total=result.damage.total,
        procs=result.damage.procs,
        base_dmg=result.damage.base_dmg,
        boost_mult=result.damage.boost_mult,
        def_mult=result.damage.def_mult,
        res_mult=result.damage.res_mult,
        vulnerability_mult=result.damage.vulnerability_mult,
        stun_mult=result.damage.stun_mult,
        anomaly_prof_mult=result.damage.anomaly_prof_mult,
        level_mult=result.damage.level_mult,
        anomaly_boost_mult=result.damage.anomaly_boost_mult,
        total_atk=result.stats.atk,
        total_anomaly_proficiency=result.stats.anomaly_proficiency,
        agent_name=agent.name,
        enemy_name=enemy.name,
    )
