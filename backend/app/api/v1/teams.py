"""Team endpoints — full CRUD + team-context combo evaluation."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.dependencies import (
    get_attack_repo,
    get_enemy_repo,
    get_owned_build_repo,
    get_owned_combo_repo,
    get_owned_disc_repo,
    get_owned_team_repo,
)
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.models.build import Build
from app.models.enums import Element
from app.repositories.attack import AttackRepository
from app.repositories.build import BuildRepository, ComboRepository, EnemyProfileRepository
from app.repositories.disc import DiscRepository
from app.repositories.team import TeamRepository
from app.schemas.common import PaginatedResponse
from app.schemas.damage import (
    AgentContributionSchema,
    AppliedTeamBuffSchema,
    BuffRosterEntrySchema,
    BuildDeltaSchema,
    CategoryBreakdownSchema,
    ComboStepResultSchema,
    ContributionSchema,
    ElementBreakdownSchema,
    EvaluateDiscsRequest,
    MarkerStepResultSchema,
    StepAttributionSchema,
    TeamCalculateRequest,
    TeamCalculateResponse,
    ZoneAttributionSchema,
    ZoneDeltaSchema,
    ZoneFormulaSchema,
)
from app.schemas.team import TeamCreate, TeamRead, TeamUpdate, assert_slots_distinct
from app.services.attributed_eval import AttributedComboResult, evaluate_combo_attributed
from app.services.attribution import StepAttribution, ZoneAttribution
from app.services.buff_roster import BuffRosterEntry
from app.services.build_delta import BuildDelta, compute_build_delta
from app.services.combo_step_resolver import resolve_combo_sequence
from app.services.combo_types import AnomalyStepResult, ComboStep
from app.services.damage_calculator import CritMode
from app.services.lumiflux import AgentRef, resolve_fluxed_element
from app.services.modifiers import ActiveConditions, Condition
from app.services.snapshot_builder import _discs_to_stat_dicts, build_snapshot_from_db
from app.services.support_selection import select_support_members
from app.services.team_calculator import TeamCalculationResult, TeamMember, calculate_team_combo

router = APIRouter(prefix="/teams", tags=["teams"])

_CRIT_MODES = {
    "expected": CritMode.EXPECTED,
    "crit": CritMode.CRIT,
    "no_crit": CritMode.NO_CRIT,
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


def _team_member_from_build(
    build: Build, *, disabled_buffs: list[str] | None = None
) -> TeamMember:
    """Build a TeamMember value object from a DB Build.

    Loads the build's full modifier set via the same snapshot machinery
    used for DPS, so supports contribute every ``target=team`` modifier
    their kit / W-Engine / disc sets produce.

    stack_counts left at its column-read default: this helper only takes a
    ``Build`` (no request context reaches it), and only ``snap.modifiers`` is
    used below -- ``snap.stack_counts`` is discarded with the rest of the
    snapshot.

    ``custom_buffs`` (#64) is deliberately NOT collected here, and this is the subtle
    half of the one-holder rule. This path stacks **two** distribution layers:
    ``_augment_for_member`` appends other members' TEAM rows *from this list*, and then
    ``anomaly_simulator`` appends other members' TEAM rows again from the augmented
    snapshots it is handed. A stage buff placed here as well as on the primary's snapshot
    therefore reaches the acting agent once per layer — measured as a gain of 513 / 769 /
    1025 on 1-, 2- and 3-agent teams for one 500 flat_atk buff, i.e. still growing with
    the squad. Holding it only on the primary's *snapshot* lets exactly one layer
    distribute it. Pinned by ``test_custom_buff_exactly_once.py``.
    """
    agent = build.agent
    snap = build_snapshot_from_db(build, agent, disabled_buffs=disabled_buffs)
    element = agent.element.value if hasattr(agent.element, "value") else agent.element
    specialty = agent.specialty.value if hasattr(agent.specialty, "value") else agent.specialty
    return TeamMember(
        build_id=str(build.id),
        agent_name=agent.name,
        agent_element=element,
        agent_specialty=specialty,
        agent_faction_id=agent.faction_id,
        modifiers=snap.modifiers,
    )


def _resolve_fluxed_element(
    *,
    override: str | None,
    all_members: list[TeamMember],
    primary_build_id: str,
) -> str | None:
    """Attribute Flux resolution for the team-context calc endpoints (Task 8).

    Explicit override always wins (DESIGN_remielle.md §5.3). Otherwise: flux
    is a Lumiflux-only mechanic (guide line 68) — every other agent's
    fluxed_element is always ``None``, unaffected by team composition.
    ``resolve_fluxed_element`` itself returns ``None`` for a solo/empty team,
    so a missing/undersized team reads as the documented no-flux default
    (pure Lumiflux, RES 0), not a bug.

    ``all_members`` is already in ``team.build1/build2/build3`` slot order
    (``_load_team_context`` builds it that way), the ordering
    ``resolve_fluxed_element`` requires (DESIGN §5.1).
    """
    # F4 (hardening Task 18) ordering, applied here too so the two resolvers
    # agree: the Lumiflux check precedes the override. Previously an override
    # on a non-Lumiflux primary was echoed back as "the element actually used"
    # for an agent that has no flux at all -- and since Task 17 that echo is
    # meant to be a promise about the damage chain, not a restatement of the
    # request. The field's own contract is "Lumiflux agents only".
    primary = next((m for m in all_members if m.build_id == primary_build_id), None)
    if primary is None or primary.agent_element != Element.LUMIFLUX.value:
        return None
    if override is not None:
        return override
    ordered_agents = [
        AgentRef(build_id=m.build_id, element=Element(m.agent_element)) for m in all_members
    ]
    subject = AgentRef(build_id=primary.build_id, element=Element(primary.agent_element))
    try:
        derived = resolve_fluxed_element(ordered_agents, subject)
    except ValueError:
        return None
    return derived.value if derived is not None else None


@router.get("", response_model=PaginatedResponse[TeamRead])
async def list_teams(
    repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[TeamRead]:
    """List the caller's saved teams."""
    teams = await repo.get_all(offset=offset, limit=limit)
    total = await repo.count()
    return PaginatedResponse(
        items=[TeamRead.model_validate(t) for t in teams],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=TeamRead, status_code=201)
@limiter.limit(WRITE_LIMIT)
async def create_team(
    request: Request,
    body: TeamCreate,
    repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
) -> TeamRead:
    """Create a team of up to three builds."""
    team = await repo.create(body.model_dump())
    return TeamRead.model_validate(team)


@router.get("/{team_id}", response_model=TeamRead)
async def get_team(
    team_id: str,
    repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
) -> TeamRead:
    """Fetch a single team by id."""
    team = await repo.get_by_id(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return TeamRead.model_validate(team)


@router.patch("/{team_id}", response_model=TeamRead)
@limiter.limit(WRITE_LIMIT)
async def update_team(
    request: Request,
    team_id: str,
    body: TeamUpdate,
    repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
) -> TeamRead:
    """Partially update a team's name or member builds."""
    patch = body.model_dump(exclude_unset=True)

    # `TeamUpdate`'s validator only sees the patch body. A patch that moves one
    # slot onto an id the row already holds in another slot is a duplicate only
    # once merged, so check the *resulting* team, not the request.
    if any(k in patch for k in ("build1_id", "build2_id", "build3_id")):
        existing = await repo.get_by_id(team_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Team not found")
        merged = {
            slot: patch.get(slot, getattr(existing, slot))
            for slot in ("build1_id", "build2_id", "build3_id")
        }
        try:
            assert_slots_distinct(**merged)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    team = await repo.update(team_id, patch)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return TeamRead.model_validate(team)


@router.delete("/{team_id}", status_code=204)
@limiter.limit(WRITE_LIMIT)
async def delete_team(
    request: Request,
    team_id: str,
    repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
) -> None:
    """Delete a team."""
    deleted = await repo.delete(team_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Team not found")


def _normalize_and_validate_steps(
    raw_steps: list,
    primary_build_id: str,
    valid_agent_ids: set[str],
) -> list:
    """Replace default 'dps' agent_id with primary build ID; 422 on unknown ids."""
    steps = [
        replace(s, agent_id=primary_build_id)
        if isinstance(s, ComboStep) and s.agent_id == "dps"
        else s
        for s in raw_steps
    ]
    unknown = {
        s.agent_id for s in steps if isinstance(s, ComboStep) and s.agent_id not in valid_agent_ids
    }
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Step agent_id(s) not in team: {sorted(unknown)}",
        )
    return steps


def _zone_schema(zone: ZoneAttribution) -> ZoneAttributionSchema:
    return ZoneAttributionSchema(
        contributions=[
            ContributionSchema(
                source=c.source,
                value=c.value,
                source_category=c.source_category,
                source_kind=c.source_kind,
                owner_agent_name=c.owner_agent_name,
                description=c.description,
                notes=c.notes,
            )
            for c in zone.contributions
        ],
        total=zone.total,
    )


def _attribution_schema(attr: StepAttribution | None) -> StepAttributionSchema | None:
    if attr is None:
        return None
    return StepAttributionSchema(
        atk_components=_zone_schema(attr.atk_components),
        atk_pct_components=_zone_schema(attr.atk_pct_components),
        crit_rate=_zone_schema(attr.crit_rate),
        crit_dmg=_zone_schema(attr.crit_dmg),
        boost_bonuses=_zone_schema(attr.boost_bonuses),
        pen_ratio=_zone_schema(attr.pen_ratio),
        pen_flat=_zone_schema(attr.pen_flat),
        res_reduction=_zone_schema(attr.res_reduction),
        res_ignore=_zone_schema(attr.res_ignore),
        def_ignore=_zone_schema(attr.def_ignore),
        vulnerability=_zone_schema(attr.vulnerability),
        stun_bonuses=_zone_schema(attr.stun_bonuses),
        sheer_force_components=(
            _zone_schema(attr.sheer_force_components)
            if attr.sheer_force_components.contributions
            else None
        ),
        sheer_boost_bonuses=(
            _zone_schema(attr.sheer_boost_bonuses)
            if attr.sheer_boost_bonuses.contributions
            else None
        ),
    )


def _zone_formula_schemas(
    attr: StepAttribution | None,
) -> dict[str, ZoneFormulaSchema] | None:
    if attr is None or not attr.zone_formulas:
        return None
    return {
        zone: ZoneFormulaSchema(
            template=zf.template,
            terms=zf.terms,
            result_bp=zf.result_bp,
            pre_clamp_bp=zf.pre_clamp_bp,
        )
        for zone, zf in attr.zone_formulas.items()
    }


def _buff_roster_schemas(roster: list[BuffRosterEntry]) -> list[BuffRosterEntrySchema]:
    return [
        BuffRosterEntrySchema(
            source_label=e.source_label,
            source_category=e.source_category,
            source_kind=e.source_kind,
            owner_agent_name=e.owner_agent_name,
            stat=e.stat,
            zone=e.zone,
            value_bp=e.value_bp,
            magnitude_display=e.magnitude_display,
            condition=e.condition,
            is_modeled=e.is_modeled,
            notes=e.notes,
        )
        for e in roster
    ]


def _build_step_schemas(
    steps: list,
    *,
    with_attribution: bool = False,
) -> list[ComboStepResultSchema | MarkerStepResultSchema]:
    out = []
    for s in steps:
        if hasattr(s, "step_type"):
            out.append(MarkerStepResultSchema(label=s.label, step_type=s.step_type))
        elif isinstance(s, AnomalyStepResult):
            # Derived anomaly damage (anomaly_tick / disorder / vortex / abloom)
            # appended by sim_result_to_combo_evaluation. Serialised through the
            # schema's is_anomaly=True mode: no crit triad, anomaly multipliers
            # instead. `scope` carries the anomaly type so it matches the
            # category these steps aggregate under in by_category.
            out.append(
                ComboStepResultSchema(
                    label=s.label,
                    attack_id=s.attack_id,
                    attack_name=s.label,
                    scope=s.anomaly_type,
                    element=s.element,
                    multiplier=0,
                    total=s.total,
                    base_dmg=s.base_dmg,
                    boost_mult=s.boost_mult,
                    def_mult=s.def_mult,
                    res_mult=s.res_mult,
                    vulnerability_mult=s.vulnerability_mult,
                    stun_mult=s.stun_mult,
                    is_anomaly=True,
                    anomaly_proficiency_mult=s.anomaly_prof_mult,
                    anomaly_level_mult=s.level_mult,
                    anomaly_dmg_bonus_mult=s.anomaly_boost_mult,
                    level_factor=s.level_factor_val,
                    effective_enemy_def=s.effective_enemy_def,
                    stun_base_mult=s.stun_base_mult,
                )
            )
        else:
            out.append(
                ComboStepResultSchema(
                    label=s.label,
                    attack_id=s.attack_id,
                    attack_name=s.attack_name,
                    scope=s.scope.value,
                    element=s.element,
                    multiplier=s.multiplier,
                    total=s.damage.total,
                    damage_no_crit=s.damage_no_crit,
                    damage_crit=s.damage_crit,
                    damage_expected=s.damage_expected,
                    base_dmg=s.damage.base_dmg,
                    boost_mult=s.damage.boost_mult,
                    crit_mult=s.damage.crit_mult,
                    def_mult=s.damage.def_mult,
                    res_mult=s.damage.res_mult,
                    vulnerability_mult=s.damage.vulnerability_mult,
                    stun_mult=s.damage.stun_mult,
                    sheer_force=s.damage.effective_atk if s.damage.is_sheer else None,
                    attribution=(_attribution_schema(s.attribution) if with_attribution else None),
                    zone_formulas=(
                        _zone_formula_schemas(s.attribution) if with_attribution else None
                    ),
                )
            )
    return out


@dataclass
class _TeamEvalContext:
    """Everything resolved from a team_id + combo/enemy/context body, shared
    by ``/calculate`` and ``/evaluate-discs`` so the two entry points into
    ``calculate_team_combo``/``evaluate_combo_attributed`` cannot diverge."""

    team: Any
    combo: Any
    enemy: Any
    crit_mode: CritMode
    builds: dict[str, Build]
    slot_build_ids: list[str]
    primary_build_id: str
    steps: list
    member_snapshots: dict
    all_members: list[TeamMember]
    conditions: ActiveConditions
    fluxed_element: str | None


async def _load_team_context(
    *,
    team_id: str,
    combo_id: str,
    enemy_profile_id: str,
    refinement: int,
    mindscape_level: int | None,
    active_conditions: list[str],
    stack_counts: dict[str, int],
    crit_mode_key: str,
    primary_index: int,
    team_repo: TeamRepository,
    build_repo: BuildRepository,
    combo_repo: ComboRepository,
    attack_repo: AttackRepository,
    enemy_repo: EnemyProfileRepository,
    fluxed_element_override: str | None = None,
    custom_buffs: Sequence[Any] | None = None,
    disabled_buffs: list[str] | None = None,
) -> _TeamEvalContext:
    team = await team_repo.get_by_id(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    slot_build_ids = [
        str(bid) for bid in (team.build1_id, team.build2_id, team.build3_id) if bid is not None
    ]
    if not slot_build_ids:
        raise HTTPException(status_code=422, detail="Team has no members")
    if primary_index >= len(slot_build_ids):
        raise HTTPException(status_code=422, detail="active_index exceeds team size")

    combo = await combo_repo.get_by_id(combo_id)
    if combo is None:
        raise HTTPException(status_code=404, detail="Combo not found")
    if str(combo.team_id) != team_id:
        raise HTTPException(status_code=422, detail="Combo does not belong to this team")

    enemy = await enemy_repo.get_by_id(enemy_profile_id)
    if enemy is None:
        raise HTTPException(status_code=404, detail="Enemy profile not found")

    crit_mode = _CRIT_MODES.get(crit_mode_key)
    if crit_mode is None:
        raise HTTPException(status_code=422, detail=f"Invalid crit_mode: {crit_mode_key}")

    builds: dict[str, Build] = {}
    for bid in slot_build_ids:
        b = await build_repo.get_by_id(bid)
        if b is None:
            raise HTTPException(status_code=404, detail=f"Team member build {bid} not found")
        builds[bid] = b

    primary_build_id = slot_build_ids[primary_index]
    primary_build = builds[primary_build_id]
    if primary_build.agent is None:
        raise HTTPException(status_code=404, detail="Agent not found on primary build")

    # Team combos tag each step with its owner's build UUID; pass the full member
    # map so non-primary steps resolve against the owning member's build (correct
    # move lookup + skill-level scaling).
    raw_steps = await resolve_combo_sequence(
        combo.sequence or [],
        build=primary_build,
        attack_repo=attack_repo,
        member_builds=builds,
    )
    steps = _normalize_and_validate_steps(raw_steps, primary_build_id, set(slot_build_ids))

    # DESIGN §2.1 / issue #94: `stack_counts` is this request's flat,
    # agent-qualified stack override (same shape as `disabled_buffs`
    # elsewhere) -- every member's own snapshot gets it, since the Phase 5B
    # attributed path (evaluate_combo_attributed -> calculate_team_combo ->
    # simulate_combo_steps) resolves stacks per-acting-agent straight off
    # that agent's `member_snapshots` entry, not off the merged
    # `conditions` below. Without this, a team combo's per-member stacks
    # would still silently come from each build's own DB row.
    # Stage buffs (#64) go on exactly ONE member -- the primary -- and reach the rest the
    # way every other team buff does, through the TEAM merges downstream. Putting them on
    # every member's snapshot instead counted a squad-wide buff once per member, and left
    # a `target="self"` buff indistinguishable from a squad-wide one by applying it to all
    # three. `ModifierTarget.SELF` is not "whoever is on field": it is "the holder", and
    # the holder here is the calculation's subject -- which is what the editor's "DPS only"
    # label means. One holder, engine distribution -- the same rule `/simulate` follows.
    member_snapshots: dict = {}
    for bid, b in builds.items():
        if b.agent is None:
            raise HTTPException(status_code=404, detail=f"Agent not found on build {bid}")
        mc_level = mindscape_level if mindscape_level is not None else b.mindscape_level
        member_snapshots[bid] = build_snapshot_from_db(
            b,
            b.agent,
            refinement=refinement,
            mindscape_level=mc_level,
            stack_counts=dict(stack_counts),
            custom_buffs=(custom_buffs if bid == primary_build_id else None),
            disabled_buffs=disabled_buffs,
        )

    # `all_members` carries NO stage buffs — see `_team_member_from_build`. The primary's
    # snapshot above is the single holder; the simulator's own TEAM merge is the one layer
    # that distributes it.
    all_members = [
        _team_member_from_build(builds[bid], disabled_buffs=disabled_buffs)
        for bid in slot_build_ids
    ]
    conditions = _parse_conditions(active_conditions)
    conditions.stack_counts = stack_counts

    fluxed_element = _resolve_fluxed_element(
        override=fluxed_element_override,
        all_members=all_members,
        primary_build_id=primary_build_id,
    )

    return _TeamEvalContext(
        team=team,
        combo=combo,
        enemy=enemy,
        crit_mode=crit_mode,
        builds=builds,
        slot_build_ids=slot_build_ids,
        primary_build_id=primary_build_id,
        steps=steps,
        member_snapshots=member_snapshots,
        all_members=all_members,
        conditions=conditions,
        fluxed_element=fluxed_element,
    )


async def _fetch_discs(disc_ids: list[str], disc_repo: DiscRepository) -> list[dict]:
    """Fetch persisted discs by id and convert to raw disc-stat dicts. 404s
    on any id not found / not owned by the caller (owner-scoped repo)."""
    discs = []
    for disc_id in disc_ids:
        d = await disc_repo.get_by_id(disc_id)
        if d is None:
            raise HTTPException(status_code=404, detail=f"Disc {disc_id} not found")
        discs.append(d)
    return _discs_to_stat_dicts(discs)


async def _resolve_disc_override(
    body: EvaluateDiscsRequest, disc_repo: DiscRepository
) -> list[dict]:
    """Resolve the request's disc_ids/disc_stats (XOR) to raw disc-stat dicts."""
    if body.disc_ids:
        return await _fetch_discs(body.disc_ids, disc_repo)
    return [
        {
            "main_stat_type": d.main_stat_type,
            "main_stat_value": d.main_stat_value,
            "substats": [{"stat": s.stat, "value": s.value} for s in d.substats],
        }
        for d in (body.disc_stats or [])
    ]


def _build_delta_schema(delta: BuildDelta) -> BuildDeltaSchema:
    return BuildDeltaSchema(
        from_total=delta.from_total,
        to_total=delta.to_total,
        pct_change=delta.pct_change,
        is_exact=delta.is_exact,
        zone_deltas=[
            ZoneDeltaSchema(
                zone=z.zone,
                from_bp=z.from_bp,
                to_bp=z.to_bp,
                ratio=z.ratio,
                gain_share_pct=z.gain_share_pct,
            )
            for z in delta.zone_deltas
        ],
    )


def _build_team_response(
    ctx: _TeamEvalContext,
    result: TeamCalculationResult | AttributedComboResult,
    *,
    with_attribution: bool,
    delta: BuildDelta | None = None,
) -> TeamCalculateResponse:
    combo_result = result.combo_result
    stats = combo_result.stats
    return TeamCalculateResponse(
        team_id=str(ctx.team.id),
        team_name=ctx.team.name,
        dps_build_id=result.dps_build_id,
        dps_agent_name=result.dps_agent_name,
        combo_id=str(ctx.combo.id),
        combo_name=ctx.combo.name,
        enemy_name=ctx.enemy.name,
        auto_conditions=result.auto_conditions,
        applied_team_buffs=[
            AppliedTeamBuffSchema(
                source_build_id=b.source_build_id,
                source_agent_name=b.source_agent_name,
                source_label=b.source_label,
                stat=b.stat,
                value=b.value,
            )
            for b in result.applied_team_buffs
        ],
        by_agent=[
            AgentContributionSchema(
                agent_name=a.agent_name, build_id=a.build_id, damage=a.damage, pct=a.pct
            )
            for a in result.by_agent
        ],
        buff_roster=(_buff_roster_schemas(result.buff_roster) if with_attribution else []),
        delta=(_build_delta_schema(delta) if delta is not None else None),
        total_damage=combo_result.total_damage,
        standard_total=combo_result.standard_total,
        anomaly_total=combo_result.anomaly_total,
        steps=_build_step_schemas(combo_result.steps, with_attribution=with_attribution),
        by_category=[
            CategoryBreakdownSchema(category=c.category, total=c.total, pct=c.pct)
            for c in combo_result.by_category
        ],
        by_element=[
            ElementBreakdownSchema(element=e.element, total=e.total, pct=e.pct)
            for e in combo_result.by_element
        ],
        total_atk=stats.atk if stats else 0,
        total_crit_rate=stats.crit_rate if stats else 0,
        total_crit_dmg=stats.crit_dmg if stats else 0,
        total_pen_ratio=stats.pen_ratio if stats else 0,
        fluxed_element=ctx.fluxed_element,
    )


def _evaluate_team(
    body: TeamCalculateRequest,
    *,
    all_members: list[TeamMember],
    member_snapshots: dict,
    primary_build_id: str,
    enemy: Any,
    steps: list,
    conditions: ActiveConditions,
    crit_mode: CritMode,
    fluxed_overrides: dict[str, str] | None = None,
) -> TeamCalculationResult | AttributedComboResult:
    """Dispatch to the attributed or plain team-combo evaluation path.

    ``fluxed_overrides`` carries the caller's explicit Attribute Flux choice
    down to the assembler, so the value this endpoint ECHOES as
    ``fluxed_element`` is the value the damage chain actually used. Resolving
    the echo here while letting the assembler derive its own would put the two
    back out of step -- the narrow form of P-F1 itself.
    """
    # `all_members[1:]` is the slot-slice spelling of the same defect issue #133
    # narrowed everywhere else: on a row with one build in two slots it hands the
    # primary back as its own support, and `_derive_auto_conditions` then lets it
    # satisfy its own SAME_*/ANOMALY_COUNT_* checks. This endpoint always scores
    # slot 0 (`primary_index=0` at the only call site), so the target is
    # `all_members[0]`. Identical to the slice for any team with distinct builds.
    support_members = select_support_members(list(all_members), 0)
    if body.with_attribution:
        return evaluate_combo_attributed(
            dps_member=all_members[0],
            support_members=support_members,
            member_snapshots=member_snapshots,
            enemy=enemy,
            combo_steps=steps,
            conditions=conditions,
            crit_mode=crit_mode,
            is_stunned=body.is_stunned,
            stun_dmg_mult=body.stun_dmg_mult,
        )
    return calculate_team_combo(
        dps_member=all_members[0],
        support_members=support_members,
        dps_snapshot=member_snapshots[primary_build_id],
        enemy=enemy,
        combo_steps=steps,
        conditions=conditions,
        fluxed_overrides=fluxed_overrides,
        crit_mode=crit_mode,
        is_stunned=body.is_stunned,
        stun_dmg_mult=body.stun_dmg_mult,
        member_snapshots=member_snapshots,
    )


@router.post("/{team_id}/calculate", response_model=TeamCalculateResponse)
@limiter.limit(WRITE_LIMIT)
async def calculate_team_endpoint(
    request: Request,
    team_id: str,
    body: TeamCalculateRequest,
    team_repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
    build_repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    combo_repo: Annotated[ComboRepository, Depends(get_owned_combo_repo)],
    attack_repo: Annotated[AttackRepository, Depends(get_attack_repo)],
    enemy_repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
) -> TeamCalculateResponse:
    """Evaluate a team combo under Phase 5B — all members contribute damage.

    The primary build (team slot 1) is the designated DPS. Steps without an
    explicit ``agent_id`` are attributed to the primary build. Each team
    member's snapshot is augmented with ``target=team`` modifiers from the
    other members before the shared simulation runs.
    """
    ctx = await _load_team_context(
        team_id=team_id,
        combo_id=body.combo_id,
        enemy_profile_id=body.enemy_profile_id,
        refinement=body.refinement,
        mindscape_level=body.mindscape_level,
        active_conditions=body.active_conditions,
        stack_counts=body.stack_counts,
        custom_buffs=body.custom_buffs,
        disabled_buffs=body.disabled_buffs,
        crit_mode_key=body.crit_mode,
        primary_index=0,
        team_repo=team_repo,
        build_repo=build_repo,
        combo_repo=combo_repo,
        attack_repo=attack_repo,
        enemy_repo=enemy_repo,
        fluxed_element_override=body.fluxed_element,
    )

    result = _evaluate_team(
        body,
        all_members=ctx.all_members,
        member_snapshots=ctx.member_snapshots,
        primary_build_id=ctx.primary_build_id,
        enemy=ctx.enemy,
        steps=ctx.steps,
        conditions=ctx.conditions,
        crit_mode=ctx.crit_mode,
        # Pass the RESOLVED value (override-or-derived), not just the override:
        # that makes the echoed `fluxed_element` and the element the damage
        # chain used equal by construction, rather than by two code paths
        # happening to agree.
        fluxed_overrides=(
            {ctx.primary_build_id: ctx.fluxed_element} if ctx.fluxed_element else None
        ),
    )

    return _build_team_response(ctx, result, with_attribution=body.with_attribution)


@router.post("/{team_id}/evaluate-discs", response_model=TeamCalculateResponse)
@limiter.limit(WRITE_LIMIT)
async def evaluate_discs_endpoint(
    request: Request,
    team_id: str,
    body: EvaluateDiscsRequest,
    team_repo: Annotated[TeamRepository, Depends(get_owned_team_repo)],
    build_repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    combo_repo: Annotated[ComboRepository, Depends(get_owned_combo_repo)],
    attack_repo: Annotated[AttackRepository, Depends(get_attack_repo)],
    enemy_repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
    disc_repo: Annotated[DiscRepository, Depends(get_owned_disc_repo)],
) -> TeamCalculateResponse:
    """Keystone endpoint (DESIGN_explainability.md §3.1).

    Evaluates a team combo against a *specified* six-disc combination —
    ``disc_ids`` (persisted discs) or ``disc_stats`` (inline, for an
    optimizer/rank candidate that isn't equipped) replace the equipped set
    on the team member at ``active_index`` before stat resolution. Always
    runs with full attribution via ``evaluate_combo_attributed`` (Task B1),
    the same machinery ``/calculate`` uses — this is "run the calculator
    with these six discs," never a second arithmetic path.
    """
    ctx = await _load_team_context(
        team_id=team_id,
        combo_id=body.combo_id,
        enemy_profile_id=body.enemy_profile_id,
        refinement=body.refinement,
        mindscape_level=body.mindscape_level,
        active_conditions=body.active_conditions,
        stack_counts=body.stack_counts,
        custom_buffs=body.custom_buffs,
        disabled_buffs=body.disabled_buffs,
        crit_mode_key=body.crit_mode,
        primary_index=body.active_index,
        team_repo=team_repo,
        build_repo=build_repo,
        combo_repo=combo_repo,
        attack_repo=attack_repo,
        enemy_repo=enemy_repo,
        fluxed_element_override=body.fluxed_element,
    )

    disc_stat_dicts = await _resolve_disc_override(body, disc_repo)
    support_members = select_support_members(list(ctx.all_members), body.active_index)

    result = evaluate_combo_attributed(
        dps_member=ctx.all_members[body.active_index],
        support_members=support_members,
        member_snapshots=ctx.member_snapshots,
        enemy=ctx.enemy,
        combo_steps=ctx.steps,
        conditions=ctx.conditions,
        crit_mode=ctx.crit_mode,
        is_stunned=body.is_stunned,
        stun_dmg_mult=body.stun_dmg_mult,
        disc_overrides={ctx.primary_build_id: disc_stat_dicts},
    )

    delta = None
    if body.compare_to == "equipped" or body.compare_to_disc_ids:
        # None override = the equipped set as-is; compare_to_disc_ids swaps
        # in a specific alternative set instead (independent of "equipped").
        compare_overrides = None
        if body.compare_to_disc_ids:
            compare_discs = await _fetch_discs(body.compare_to_disc_ids, disc_repo)
            compare_overrides = {ctx.primary_build_id: compare_discs}
        compare_result = evaluate_combo_attributed(
            dps_member=ctx.all_members[body.active_index],
            support_members=support_members,
            member_snapshots=ctx.member_snapshots,
            enemy=ctx.enemy,
            combo_steps=ctx.steps,
            conditions=ctx.conditions,
            crit_mode=ctx.crit_mode,
            is_stunned=body.is_stunned,
            stun_dmg_mult=body.stun_dmg_mult,
            disc_overrides=compare_overrides,
        )
        delta = compute_build_delta(
            compare_result.combo_result.steps,
            result.combo_result.steps,
            from_total=compare_result.combo_result.total_damage,
            to_total=result.combo_result.total_damage,
        )

    return _build_team_response(ctx, result, with_attribution=True, delta=delta)
