"""Stateful anomaly simulator API controller."""

from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from app.schemas.simulate import SimulationStepRequest

from fastapi import APIRouter, Depends, HTTPException, Request

from app.data.loaders.moves import load_agent_moves
from app.dependencies import (
    get_attack_repo,
    get_enemy_repo,
    get_owned_build_repo,
)
from app.middleware.rate_limit import WRITE_LIMIT, limiter
from app.models.enums import HitMode, PotentialVariant
from app.repositories.attack import AttackRepository
from app.repositories.build import (
    BuildRepository,
    EnemyProfileRepository,
)
from app.schemas.damage import BuffRosterEntrySchema
from app.schemas.simulate import (
    SimulationRequest,
    SimulationResponse,
    TimelineEventSchema,
)
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.buff_resolver import ActiveConditions, resolve_modifiers
from app.services.buff_roster import pivot_buff_roster
from app.services.build_damage_service import AttackScope
from app.services.channel_plan import build_channel_plan, plan_hit_offsets
from app.services.combo_step_resolver import (
    _channel_move_for,
    _classify_move,
    _ResolverState,
    resolve_channel_length,
    resolve_variant_selection,
)
from app.services.lumiflux_assembly import assemble_lumiflux_inputs
from app.services.modifiers import Condition, ModifierTarget
from app.services.snapshot_builder import build_snapshot_from_db

router = APIRouter(prefix="/simulate", tags=["simulate"])

# Load moves database globally once at import time
_MOVES_DB = load_agent_moves()


def _resolve_sequential(
    attacks: list, step: "SimulationStepRequest", resolver_states: dict
) -> list:
    """Advance the per-agent cycle state and return the single chosen attack."""
    state = resolver_states.setdefault(step.agent_id, _ResolverState())
    n = len(attacks)
    skill_key = attacks[0].skill_key
    attack_key = (skill_key, step.move_name)

    if step.cycle_position is not None:
        pos = step.cycle_position % n
    elif state.prev_attack_key == attack_key and state.prev_was_single_tap:
        pos = (state.prev_cycle_position + 1) % n
    else:
        pos = 0

    by_index = {a.hit_index: a for a in attacks}
    chosen = by_index.get(pos) or sorted(attacks, key=lambda a: a.hit_index)[pos]

    resolver_states[step.agent_id] = _ResolverState(
        prev_attack_key=attack_key,
        prev_was_single_tap=True,
        prev_cycle_position=pos,
    )
    return [chosen]


def _filter_attacks(
    attacks: list,
    step: "SimulationStepRequest",
    resolver_states: dict,
    warnings: list[str] | None = None,
    agent_uuid: str = "",
) -> tuple[list, list[float] | None, list[float] | None]:
    """Apply variant / sequential / channel resolution to a raw attack list.

    Returns ``(rows, scales)``. ``scales`` is ``None`` for every mode but ``channel``, where
    a tick row appears once per tick and each occurrence is worth a fraction of the authored
    multiplier — see :func:`app.services.channel_plan.build_channel_plan`, which the saved-combo
    path expands through as well so the two encodings cannot disagree (Task 10c).
    """
    if not attacks:
        return attacks, None, None
    hit_mode, available_labels = _classify_move(attacks)
    if hit_mode == HitMode.VARIANT:
        # Missing label → first available, with a warning; unknown → 404. Shared with
        # combo_step_resolver and optimizer_pipeline so the three agree on the row set
        # (DESIGN_sequential_variant.md §5.8). Before this, a label-less step silently
        # kept *every* row here.
        chosen, warning = resolve_variant_selection(
            str(step.move_name), available_labels, step.variant_label
        )
        if warning is not None and warnings is not None:
            warnings.append(warning)
        if chosen is None:
            return attacks, None, None
        filtered = [a for a in attacks if a.variant_label == chosen]
        return sorted(filtered, key=lambda a: a.hit_index), None, None
    if hit_mode == HitMode.SEQUENTIAL:
        return _resolve_sequential(attacks, step, resolver_states), None, None
    if hit_mode == HitMode.CHANNEL:
        return _resolve_channel_rows(attacks, step, agent_uuid, warnings)
    return attacks, None, None


def _resolve_channel_rows(
    attacks: list,
    step: "SimulationStepRequest",
    agent_uuid: str,
    warnings: list[str] | None,
) -> tuple[list, list[float] | None, list[float] | None]:
    """Expand a channel into its real hits, through the shared plan.

    Unauthored spec -> every row once, unscaled, with a warning: exactly what the move did
    before it was re-classified. Failing the request instead would be an outage rather than
    a corrected number, the same call the missing-`variant_label` fallback makes.
    """
    move_name = str(step.move_name)
    # Keyed by the agent's real `agents.id`, NOT `step.agent_id` -- the latter is the
    # team-slot key ("dps"/"support1"), and looking a spec up by it would silently find
    # nothing and degrade every channel to atomic.
    move = _channel_move_for(agent_uuid, move_name)
    spec = move.channel if move is not None else None
    if spec is None:
        if warnings is not None:
            warnings.append(
                f"Move {move_name!r} has hit_mode='channel' but no channel spec is authored; "
                f"every row fired once (atomic behaviour). Damage and gauge are the "
                f"pre-channel figures, not a hold-scaled result."
            )
        return sorted(attacks, key=lambda a: a.hit_index), None, None

    chosen_s, warning = resolve_channel_length(move_name, spec, step.channel_s)
    if warning is not None and warnings is not None:
        warnings.append(warning)
    # `tail_s` is NOT optional here even though it defaults to 0.0: on a channel the move's
    # `duration_s` is the non-held tail, and dropping it places the release hit one tail
    # earlier than the combo path does for the identical rotation. Totals stay equal, hit
    # TIMES do not — and hit times are what the 3s per-attribute re-trigger CD and the decay
    # clock read, so the two encodings can disagree on proc count. That is the #83 defect in
    # its timing form, and Task 10c exists to keep all three paths on one expansion.
    plan = build_channel_plan(
        attacks,
        spec,
        chosen_s,
        tail_s=(move.duration_s if move is not None else 0.0) or 0.0,
        move_name=move_name,
    )
    if warnings is not None:
        warnings.extend(plan.warnings)
    return (
        [h.row for h in plan.hits],
        [h.mv_scale for h in plan.hits],
        plan_hit_offsets(plan),
    )


@router.post("", response_model=SimulationResponse)
@limiter.limit(WRITE_LIMIT)
async def simulate_combat(
    request: Request,
    body: SimulationRequest,
    build_repo: Annotated[BuildRepository, Depends(get_owned_build_repo)],
    attack_repo: Annotated[AttackRepository, Depends(get_attack_repo)],
    enemy_repo: Annotated[EnemyProfileRepository, Depends(get_enemy_repo)],
) -> SimulationResponse:
    """Execute a stateful team anomaly simulation over a sequence of steps."""
    enemy = await enemy_repo.get_by_id(body.enemy_profile_id)
    if enemy is None:
        raise HTTPException(status_code=404, detail="Enemy profile not found")

    # 1. Resolve and clone team build snapshots in memory
    #
    # Stage buffs (#64) go on exactly ONE snapshot -- the simulator's own merge is what
    # distributes them. `_resolve_onfield_modifiers` gives the acting agent its own
    # modifiers PLUS every teammate's TEAM/ACTIVE rows, and `resolve_modifiers` sums
    # duplicates rather than deduping, so a squad-wide buff placed on every member's
    # snapshot is counted once per member: measured at +1000 on a 2-agent team and +1500
    # on a 3-agent team for a 500 flat_atk stage buff, before this guard.
    #
    # The holder is the `"dps"` key when present, else the first one (dicts preserve
    # insertion order, so this is deterministic for a given request). Which member holds
    # it is irrelevant for a `target="team"` buff -- the merge hands it to whoever is
    # acting -- and for `target="self"` the holder IS the intended subject.
    holder_key = "dps" if "dps" in body.team_builds else next(iter(body.team_builds), None)
    db_builds = {}
    builds = {}
    for agent_key, build_id in body.team_builds.items():
        build = await build_repo.get_by_id(build_id)
        if build is None:
            raise HTTPException(
                status_code=404,
                detail=f"Build {build_id} not found for key '{agent_key}'",
            )

        agent = build.agent
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail=f"Agent not found on build {build_id} for key '{agent_key}'",
            )

        db_builds[agent_key] = build
        # DESIGN §2.1 -- stack_counts comes from the request context only;
        # passed straight into build_snapshot_from_db rather than baked in
        # from the DB row and corrected afterward.
        snap = build_snapshot_from_db(
            build,
            agent,
            support_builds=[],
            disabled_buffs=body.buff_context.disabled_buffs,
            stack_counts=dict(body.buff_context.stack_counts),
            custom_buffs=(body.buff_context.custom_buffs if agent_key == holder_key else None),
        )
        builds[agent_key] = snap

    # 2. Resolve sequential steps to SimulatedAttackStep instances
    steps = []
    resolver_states: dict = {}
    # Non-fatal step-resolution notices (missing variant_label fallback), surfaced
    # ahead of the simulator's own warnings in the response.
    resolution_warnings: list[str] = []
    for step in body.steps:
        if step.agent_id not in builds:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"agent_id '{step.agent_id}' in steps does not match any key in team_builds"
                ),
            )

        build = db_builds[step.agent_id]

        attack_scales: list[float] | None = None
        attack_offsets: list[float] | None = None
        if step.move_name in ("stun_trigger", "stun_end", "switch", "aftershock"):
            attacks = []
        else:
            raw = await attack_repo.get_by_agent_and_name(
                build.agent_id,
                step.move_name,
                PotentialVariant.for_rank(build.potential_rank),
            )
            attacks, attack_scales, attack_offsets = _filter_attacks(
                raw, step, resolver_states, resolution_warnings, str(build.agent_id)
            )

        saved = list(body.buff_context.active_conditions)
        conditions = list(dict.fromkeys(saved + (step.conditions or [])))

        steps.append(
            SimulatedAttackStep(
                agent_id=step.agent_id,
                move_name=step.move_name,
                attacks=attacks,
                conditions=conditions,
                # Held length for a `hit_mode='channel'` move; `None` for every other
                # move. `_step_duration_s` reads it to charge the real clock, and
                # substitutes the spec's `default_s` (with a warning) when it is absent.
                channel_s=step.channel_s,
                # Positionally aligned with `attacks`, and set only for a channel: a tick
                # row appears once per tick and each occurrence is a FRACTION of the
                # authored multiplier. Repeating the row without this would multiply the
                # move's damage by the tick count.
                attack_scales=attack_scales,
                attack_offsets=attack_offsets,
            )
        )

    # 3. Execute the stateful simulation.
    # `assemble_lumiflux_inputs` is called unconditionally: it is a no-op for
    # every team without a Lumiflux agent (no file I/O, empty result, and
    # `simulate()` with empty kwargs is byte-identical to omitting them). A
    # branch here would be the "one call site forgot" shape escalation E-5
    # documented — DESIGN_remielle.md §13.2.
    lumiflux_inputs = assemble_lumiflux_inputs(builds, steps, _MOVES_DB)
    result = simulate(
        builds,
        steps,
        enemy,
        _MOVES_DB,
        lumiflux_specs=lumiflux_inputs.specs,
        phase_flow_windows=lumiflux_inputs.phase_flow_windows,
        fluxed_elements=lumiflux_inputs.fluxed_elements,
    )

    # 3b. Build-level buff roster per team_builds key (DESIGN §2.3) -- always-
    # active resolution (ALL scope, SELF target), same pattern as
    # team_calculator._build_buff_roster.
    always_conditions = ActiveConditions(active={Condition.ALWAYS})
    buff_roster = {
        agent_key: pivot_buff_roster(
            resolve_modifiers(
                snap.modifiers,
                always_conditions,
                attack_scope=AttackScope.ALL,
                target_filter=ModifierTarget.SELF,
            )
        )
        for agent_key, snap in builds.items()
    }

    # 4. Map back to Pydantic response models
    events_schema = [
        TimelineEventSchema(
            t=e.t,
            kind=e.kind,
            agent_id=e.agent_id,
            element=e.element,
            damage=e.damage,
            aura_type=e.aura_type,
            applier_agent_id=e.applier_agent_id,
            detail=e.detail,
        )
        for e in result.events
    ]

    return SimulationResponse(
        events=events_schema,
        totals=result.totals,
        per_agent_attribution=result.per_agent_attribution,
        warnings=[*resolution_warnings, *result.warnings],
        field_timeline=result.field_timeline,
        buff_roster={
            agent_key: [
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
                for e in entries
            ]
            for agent_key, entries in buff_roster.items()
        },
    )
