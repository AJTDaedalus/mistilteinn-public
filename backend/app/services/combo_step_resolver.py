"""Shared resolver for combo step → ComboStep instances.

A user-saved combo step is a small dict — historically just
``{"attack_id": ..., "label": ...}``. As of the move-based combo
refactor, a step may also carry ``"move_name": ...``, in which case
the resolver expands it into one ComboStep per attack hit that shares
that name on the agent.

The four call sites that used to copy this logic (combos / optimizer /
teams / scorer) all funnel through :func:`resolve_combo_sequence` so the
move-name semantics stay consistent across the calculator, the team
DPS endpoint, the optimizer's ranking pass, and the disc scorer.

Sequential / variant hit-mode dispatch
---------------------------------------
``hit_mode='sequential'``: Each button press fires the *next* hit in the
chain, cycling back to 0 after N presses. A different move interrupts the
chain and the next Swiftedge press restarts from hit 0.
  - ``single_tap=False`` (legacy / full-chain): emits all N hits, same as
    atomic. This is the backward-compat branch — existing saved combos use it.
  - ``single_tap=True``: emits exactly one hit whose index is derived from
    the previous step in the sequence.

``hit_mode='variant'``: The move's Attack rows represent mutually-exclusive
game-state contexts. ``variant_label`` on the step selects which context to
use; **missing → the first available label, with a warning**; unknown → 404 error.

Missing-label fallback (:func:`resolve_variant_selection`)
-----------------------------------------------------------
Re-classifying a move from ``sequential`` to ``variant`` invalidates every combo
already saved against it — those steps carry no ``variant_label``, because none
existed when they were saved. A 400 there would take the whole team-DPS request
down with it, and an outage is not a corrected number. So a missing label resolves
deterministically to ``available_labels[0]`` (the list is sorted, so this is stable)
and raises a warning instead. An *unknown* label is still a hard 404: it means the
step names something that does not exist, which no default can repair.

All three cycle implementations — this resolver, ``optimizer_pipeline`` and
``api/v1/simulate`` — call :func:`resolve_variant_selection` so they agree on the
row set for the same input. This is deliberately *not* the de-duplication of the
cycle logic itself (still Scope 3); it is one shared decision applied in three places.

Stun markers (``step_type='stun_trigger'`` / ``'stun_end'``) are pass-through
labels that do **not** mutate resolver state — they are not ability presses
and must not reset a sequential cycle mid-chain.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import HTTPException

from app.models.enums import HitMode, PotentialVariant
from app.services.channel_plan import build_channel_plan
from app.services.combo_types import ComboStep, StunEndStep, StunTriggerStep
from app.services.modifiers import AttackScope
from app.services.snapshot_builder import attack_multiplier_at_level

if TYPE_CHECKING:
    from app.data.loaders.moves import ChannelSpec, MoveBuildupSpec
    from app.models.agent import Attack
    from app.models.build import Build
    from app.repositories.attack import AttackRepository


logger = logging.getLogger(__name__)

_SKILL_KEY_TO_INDEX: dict[str, int] = {
    "Basic": 0,
    "Dodge": 1,
    "Assist": 1,
    "Special": 2,
    "EXSpecial": 2,
    "Chain": 3,
    "Ultimate": 3,
    "Core": 4,
}

_SKILL_KEY_TO_SCOPE: dict[str, AttackScope] = {
    "Basic": AttackScope.BASIC,
    # "Dodge" is intentionally absent: it covers both Dash Attack and Dodge
    # Counter (the DB has one skill_key for both, since both stem from the
    # evade input) and needs name-based disambiguation — see scope_for_skill_key.
    "Special": AttackScope.SPECIAL,
    "EXSpecial": AttackScope.EX_SPECIAL,
    "Chain": AttackScope.CHAIN,
    "Ultimate": AttackScope.ULTIMATE,
    "Assist": AttackScope.ASSIST_FOLLOWUP,
}


def scope_for_skill_key(skill_key: str, attack_name: str) -> AttackScope:
    """Canonical skill_key/name -> AttackScope map, shared with anomaly_simulator.

    "Dodge" needs disambiguation: the DB groups Dash Attack and Dodge Counter
    under it, distinguishable only by name prefix. "Dodge Counter:" is the
    reliable positive signal (146/146 rows checked in the current corpus);
    everything else under this skill_key is a Dash Attack, including
    Harumasa's "Chasing Thunder" which carries neither prefix (confirmed dash
    via ZO char/util.ts:271).
    """
    if skill_key == "Dodge":
        return (
            AttackScope.DODGE_COUNTER
            if attack_name.startswith("Dodge Counter:")
            else AttackScope.DASH
        )
    return _SKILL_KEY_TO_SCOPE.get(skill_key, AttackScope.ALL)


def skill_level_from_build(build: Build, attack: Attack) -> int:
    """Pick the build's per-skill level for the attack's skill_key."""
    levels_str = build.skill_levels or "12,12,12,12,12"
    levels = [int(x) for x in levels_str.split(",")]
    idx = _SKILL_KEY_TO_INDEX.get(attack.skill_key, 0)
    return levels[idx] if idx < len(levels) else 12


def _attack_to_step(
    attack: Attack,
    *,
    build: Build,
    label: str,
    agent_id: str = "dps",
    mv_scale: float = 1.0,
    duration_s: float | None = None,
) -> ComboStep:
    """One ``Attack`` row -> one ``ComboStep``.

    ``mv_scale`` is the channel tick fraction (1.0 for every other mode). It scales the
    multiplier **and** the gauge together, deliberately: a tick row applied at full
    ``anomaly_buildup`` once per tick is an ``n_ticks`` x gauge over-count, which is the
    same defect class as firing every charge level of a variant move
    (docs/DESIGN_channeled_moves.md 4.4).
    """
    skill_level = skill_level_from_build(build, attack)
    multiplier = attack_multiplier_at_level(attack, skill_level)
    buildup = attack.anomaly_buildup or 0
    if mv_scale != 1.0:
        multiplier = round(multiplier * mv_scale)
        buildup = round(buildup * mv_scale)
    scope = scope_for_skill_key(attack.skill_key, attack.name)
    element = attack.element.value if hasattr(attack.element, "value") else attack.element
    return ComboStep(
        label=label,
        attack_id=str(attack.id),
        attack_name=attack.name,
        scope=scope,
        multiplier=multiplier,
        element=element,
        agent_id=agent_id,
        # The step's own gauge contribution, so the team-combo path can accrue
        # anomalies instead of reporting zero for every anomaly agent.
        anomaly_buildup=buildup,
        duration_s=duration_s,
    )


def _classify_move(attacks: list[Attack]) -> tuple[HitMode, list[str]]:
    """Return (hit_mode, available_variant_labels) for a set of Attack rows.

    ``available_variant_labels`` is non-empty only when ``hit_mode == VARIANT``.
    """
    if not attacks:
        return HitMode.ATOMIC, []
    # All rows for a given (agent, name) must share the same hit_mode post-curation.
    mode_value = attacks[0].hit_mode
    hit_mode = HitMode(mode_value) if not isinstance(mode_value, HitMode) else mode_value
    if hit_mode == HitMode.VARIANT:
        labels = sorted({a.variant_label for a in attacks if a.variant_label})
        return hit_mode, labels
    return hit_mode, []


def resolve_variant_selection(
    move_name: str,
    available_labels: list[str],
    variant_label: str | None,
) -> tuple[str | None, str | None]:
    """Decide which variant a step selects. Returns ``(chosen_label, warning)``.

    Shared by all three cycle implementations so they cannot disagree:

    - **label given and known** → ``(label, None)``.
    - **label missing** → ``(available_labels[0], warning)``. Deterministic because
      ``_classify_move`` returns the labels sorted. This is the saved-combo
      compatibility path: a combo saved while the move was ``sequential`` has no
      label to carry, and failing it would be an outage rather than a correction.
    - **label unknown** → ``HTTPException(404)``. A default cannot repair a step
      that names a variant which does not exist.
    - **no labels at all** → ``(None, warning)``. Degenerate data (a move declared
      ``variant`` whose rows carry no ``variant_label``); the caller keeps every row,
      which is the only thing left to do, but it says so out loud.

    The warning is returned rather than raised, and is also logged, so callers with
    a warnings channel can surface it and callers without one still leave a trace.
    """
    if variant_label:
        if variant_label not in available_labels:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Unknown variant_label {variant_label!r} for move {move_name!r}; "
                    f"available: {available_labels}"
                ),
            )
        return variant_label, None

    if not available_labels:
        warning = (
            f"Move {move_name!r} is declared variant but no row carries a variant_label; "
            f"keeping all rows"
        )
        logger.warning(warning)
        return None, warning

    chosen = available_labels[0]
    warning = (
        f"Move {move_name!r} requires a variant_label but the step carries none; "
        f"defaulted to {chosen!r} (available: {available_labels}). "
        f"This combo was probably saved before the move was re-classified — "
        f"re-pick the variant to silence this."
    )
    logger.warning(warning)
    return chosen, warning


def resolve_channel_length(
    move_name: str,
    spec: ChannelSpec,
    channel_s: float | None,
) -> tuple[float, str | None]:
    """Decide how long a channeled move is held. Returns ``(chosen_s, warning)``.

    Deliberately the same shape as :func:`resolve_variant_selection`, and for the same
    reason: a combo saved before a move was re-classified to ``channel`` carries no
    ``channel_s``, and failing it would take the whole team-DPS request down. An outage
    is not a corrected number.

    - **value given, in range** -> ``(value, None)``.
    - **value missing** -> ``(spec.default_s, warning)``.
    - **value out of range** -> ``(clamped, warning)``. This is where it *differs* from
      the variant resolver, which 404s an unknown label. The cases are not analogous: an
      unknown label names a variant that does not exist, and no default repairs it,
      whereas an over-long hold has an obvious and meaningful answer -- the longest the
      move allows. Clamping is a correction; 404ing would be an outage.
    - **negative or non-finite** -> ``HTTPException(422)``. There is no clamp that means
      anything here; it is a malformed request rather than a stale one.

    The warning is returned rather than raised, and also logged, so callers with a
    warnings channel surface it and callers without one still leave a trace.
    """
    if channel_s is None:
        warning = (
            f"Move {move_name!r} is a channel but the step carries no channel_s; "
            f"defaulted to {spec.default_s}s (range [{spec.min_s}, {spec.max_s}]). "
            f"This combo was probably saved before the move was re-classified -- "
            f"set a hold length to silence this."
        )
        logger.warning(warning)
        return spec.default_s, warning

    if math.isnan(channel_s) or math.isinf(channel_s) or channel_s < 0:
        raise HTTPException(
            status_code=422,
            detail=(
                f"channel_s must be a finite, non-negative number of seconds for move "
                f"{move_name!r}; got {channel_s!r}"
            ),
        )

    if channel_s < spec.min_s or channel_s > spec.max_s:
        clamped = min(max(channel_s, spec.min_s), spec.max_s)
        warning = (
            f"Move {move_name!r} was given channel_s={channel_s}s, outside its "
            f"[{spec.min_s}, {spec.max_s}]s range; clamped to {clamped}s."
        )
        logger.warning(warning)
        return clamped, warning

    return channel_s, None


@lru_cache(maxsize=1)
def _channel_specs_by_agent() -> dict[str, dict[str, MoveBuildupSpec]]:
    """``{agents.id: {move_name: ChannelSpec}}`` from the committed move files.

    Indexed by ``agent_id`` rather than by the loader's filename-stem key: the stem is a
    normalisation of ``agent_name`` and this resolver only ever holds the build's
    ``agent_id``, so going through the name would add a second lossy mapping for no gain.
    ``load_agent_moves`` already guarantees every file carries a real UUID ``agent_id``.

    Cached for the same reason ``anomaly_simulator._real_agent_moves`` is: a team-DPS
    request resolves many combos, and re-reading ~26 JSON files per step is a real cost.
    """
    from app.data.loaders.moves import load_agent_moves  # noqa: PLC0415

    out: dict[str, dict[str, MoveBuildupSpec]] = {}
    for spec in load_agent_moves().values():
        if not spec.agent_id:
            continue
        channels = {
            name: move for name, move in spec.moves.items() if move.channel is not None
        }
        if channels:
            out[str(spec.agent_id)] = channels
    return out


def _channel_move_for(agent_id: str, move_name: str) -> MoveBuildupSpec | None:
    """The authored channeled move spec for one agent's move, or ``None``.

    Returns the whole :class:`MoveBuildupSpec` rather than its ``.channel`` alone because
    the expansion needs ``duration_s`` too -- on a channel that field is the **non-held
    tail** (entry + release animation), the held part being the player's to choose.
    """
    return _channel_specs_by_agent().get(str(agent_id), {}).get(move_name)


def _channel_spec_for(agent_id: str, move_name: str) -> ChannelSpec | None:
    """The authored :class:`ChannelSpec` for one agent's move, or ``None``."""
    move = _channel_move_for(agent_id, move_name)
    return move.channel if move is not None else None


@dataclass
class _ResolverState:
    """Mutable state threaded through the sequence walker for sequential moves."""

    prev_attack_key: tuple[str, str] | None = None  # (skill_key, name)
    prev_was_single_tap: bool = False
    prev_cycle_position: int = -1


def _build_for_step(
    step_agent_id: str,
    *,
    build: Build,
    member_builds: dict[str, Build] | None,
    label: str,
) -> Build:
    """Which build owns this step: the primary one, or a named team member's."""
    if step_agent_id in ("support1", "support2"):
        resolved = (member_builds or {}).get(step_agent_id)
        if resolved is None:
            slot = "1" if step_agent_id == "support1" else "2"
            raise HTTPException(
                status_code=422,
                detail=(
                    f"No Support {slot} build in this team, "
                    f"but combo sequence contains a step for "
                    f"'{step_agent_id}' (combo step '{label}')"
                ),
            )
        return resolved
    if step_agent_id != "dps":
        # Team-owned combos tag steps with the owner's build UUID. Resolve the
        # step against that owner's build when known (so move names and skill
        # levels come from the right agent). Unknown ids are left on the primary
        # build and validated by the caller after resolution.
        return (member_builds or {}).get(step_agent_id) or build
    return build


async def _resolve_one(  # noqa: PLR0911
    raw: dict,
    *,
    state: _ResolverState,
    build: Build,
    attack_repo: AttackRepository,
    member_builds: dict[str, Build] | None = None,
    warnings: list[str] | None = None,
) -> tuple[list[ComboStep | StunTriggerStep | StunEndStep], _ResolverState]:
    """Resolve one raw step to typed steps plus updated state.

    Returns ``(steps, new_state)``. Marker steps return the *same* state
    object unchanged — they are labels, not move presses.
    """
    step_type = raw.get("step_type", "attack")
    label = str(raw.get("label", ""))

    # --- Marker steps: pass through, do NOT update state ---
    if step_type == "stun_trigger":
        return [StunTriggerStep(label=label or "Stun")], state
    if step_type == "stun_end":
        return [StunEndStep(label=label or "Stun End")], state

    # --- Move-name steps ---
    move_name: str | None = raw.get("move_name")
    attack_id: str | None = raw.get("attack_id")
    variant_label: str | None = raw.get("variant_label")
    cycle_position_override: int | None = raw.get("cycle_position")

    step_agent_id = raw.get("agent_id") or "dps"
    active_build = _build_for_step(
        step_agent_id, build=build, member_builds=member_builds, label=label
    )

    if move_name:
        # The variant comes from the build that OWNS this step, not the primary
        # build: a team combo resolves a teammate's move against the teammate's own
        # Potential rank (#90).
        attacks = await attack_repo.get_by_agent_and_name(
            str(active_build.agent_id),
            str(move_name),
            PotentialVariant.for_rank(active_build.potential_rank),
        )
        if not attacks:
            raise HTTPException(
                status_code=404,
                detail=(f"No attack named {move_name!r} for this agent (combo step '{label}')"),
            )
        hit_mode, available_labels = _classify_move(attacks)
        skill_key = attacks[0].skill_key

        if hit_mode == HitMode.VARIANT:
            return await _resolve_variant(
                attacks,
                available_labels,
                variant_label,
                warnings=warnings,
                build=active_build,
                label=label,
                agent_id=step_agent_id,
            ), _ResolverState()

        if hit_mode == HitMode.CHANNEL:
            return await _resolve_channel(
                attacks,
                str(move_name),
                raw.get("channel_s"),
                variant_label,
                build=active_build,
                label=label,
                agent_id=step_agent_id,
                warnings=warnings,
            ), _ResolverState()

        if hit_mode == HitMode.SEQUENTIAL:
            # Always single-tap for sequential moves — each step is one button press.
            # single_tap=False on stored steps is treated as single_tap=True so that
            # combos saved before this convention are resolved correctly.
            steps, new_state = await _resolve_sequential_single_tap(
                attacks,
                skill_key,
                move_name,
                state=state,
                cycle_position_override=cycle_position_override,
                build=active_build,
                label=label,
                agent_id=step_agent_id,
            )
            return steps, new_state

        # atomic: emit all hits in one step
        steps = [
            _attack_to_step(a, build=active_build, label=label, agent_id=step_agent_id)
            for a in attacks
        ]
        return steps, _ResolverState()

    if attack_id:
        attack = await attack_repo.get_by_id(str(attack_id))
        if attack is None:
            raise HTTPException(
                status_code=404,
                detail=f"Attack {attack_id} not found (combo step '{label}')",
            )
        step = _attack_to_step(attack, build=active_build, label=label, agent_id=step_agent_id)
        return [step], _ResolverState()

    return [], _ResolverState()


async def _resolve_variant(
    attacks: list[Attack],
    available_labels: list[str],
    variant_label: str | None,
    *,
    build: Build,
    label: str,
    agent_id: str = "dps",
    warnings: list[str] | None = None,
) -> list[ComboStep]:
    chosen, warning = resolve_variant_selection(
        attacks[0].name, available_labels, variant_label
    )
    if warning is not None and warnings is not None:
        warnings.append(warning)
    filtered = [a for a in attacks if a.variant_label == chosen] if chosen else list(attacks)
    ordered = sorted(filtered, key=lambda a: a.hit_index)
    return [_attack_to_step(a, build=build, label=label, agent_id=agent_id) for a in ordered]


async def _resolve_channel(
    attacks: list[Attack],
    move_name: str,
    channel_s: float | None,
    variant_label: str | None,
    *,
    build: Build,
    label: str,
    agent_id: str = "dps",
    warnings: list[str] | None = None,
) -> list[ComboStep]:
    """Expand a held move into entry / tick x N / release steps.

    The tick rows are emitted as ``n_ticks`` separate ``ComboStep`` entries rather than one
    step at ``n_ticks`` x the multiplier. They are not the same thing downstream: the
    simulator places hits on a clock, and the whole reason this mode exists is that a 4s
    spray must apply its gauge at ``tick_s`` cadence instead of in one instant (issue #83's
    defect class, in a different mode -- DESIGN_channeled_moves.md 4.4).

    Composes with ``variant``: when the rows carry ``variant_label``, the label picks the
    trio first and the hold then scales *that* trio's tick rows (Norma's warheads).
    """

    def _warn(message: str) -> None:
        logger.warning(message)
        if warnings is not None:
            warnings.append(message)

    move = _channel_move_for(str(build.agent_id), move_name)
    spec = move.channel if move is not None else None

    labels = sorted({a.variant_label for a in attacks if a.variant_label})
    if labels or variant_label:
        chosen, warning = resolve_variant_selection(move_name, labels, variant_label)
        if warning is not None and warnings is not None:
            warnings.append(warning)
        if chosen:
            attacks = [a for a in attacks if a.variant_label == chosen]

    ordered = sorted(attacks, key=lambda a: a.hit_index)

    if spec is None:
        # The DB says `channel` but no move file authored the spec. Degrade to atomic --
        # exactly what this move did before it was re-classified -- and say so. Silently
        # emitting nothing, or guessing a cadence, would both be worse than unchanged.
        _warn(
            f"Move {move_name!r} has hit_mode='channel' but no channel spec is authored for "
            f"this agent; every row fired once (atomic behaviour). Damage and gauge are the "
            f"pre-channel figures, not a hold-scaled result."
        )
        return [
            _attack_to_step(a, build=build, label=label, agent_id=agent_id) for a in ordered
        ]

    chosen_s, warning = resolve_channel_length(move_name, spec, channel_s)
    if warning is not None and warnings is not None:
        warnings.append(warning)

    # The expansion itself lives in `channel_plan` so this path and the two direct ones
    # (api/v1/simulate, optimizer_pipeline) cannot drift: two encodings of one rotation
    # producing different anomaly counts is precisely the #83 defect (Task 10c).
    #
    # `move.duration_s` goes in as the tail because on a channel that field is the NON-HELD
    # animation, not the whole move's length. The plan's durations therefore sum to
    # `chosen_s + tail`, which is what `_step_duration_s` independently returns for the same
    # move — they must agree, and #83 is what happens when a clock divisor and a gauge
    # divisor drift apart.
    plan = build_channel_plan(
        ordered,
        spec,
        chosen_s,
        tail_s=(move.duration_s if move is not None else 0.0) or 0.0,
        move_name=move_name,
    )
    for w in plan.warnings:
        _warn(w)

    return [
        _attack_to_step(
            hit.row,
            build=build,
            label=label,
            agent_id=agent_id,
            mv_scale=hit.mv_scale,
            duration_s=hit.duration_s,
        )
        for hit in plan.hits
    ]


async def _resolve_sequential_single_tap(
    attacks: list[Attack],
    skill_key: str,
    move_name: str,
    *,
    state: _ResolverState,
    cycle_position_override: int | None,
    build: Build,
    label: str,
    agent_id: str = "dps",
) -> tuple[list[ComboStep], _ResolverState]:
    n = len(attacks)
    attack_key = (skill_key, move_name)

    if cycle_position_override is not None:
        pos = cycle_position_override % n
    elif state.prev_attack_key == attack_key and state.prev_was_single_tap:
        pos = (state.prev_cycle_position + 1) % n
    else:
        pos = 0

    by_index = {a.hit_index: a for a in attacks}
    chosen = by_index.get(pos)
    if chosen is None:
        # Fallback: sort and pick by ordinal position
        chosen = sorted(attacks, key=lambda a: a.hit_index)[pos]

    step_label = label
    new_state = _ResolverState(
        prev_attack_key=attack_key,
        prev_was_single_tap=True,
        prev_cycle_position=pos,
    )
    return [_attack_to_step(chosen, build=build, label=step_label, agent_id=agent_id)], new_state


async def resolve_combo_step(
    raw: dict,
    *,
    build: Build,
    attack_repo: AttackRepository,
    member_builds: dict[str, Build] | None = None,
    warnings: list[str] | None = None,
) -> list[ComboStep | StunTriggerStep | StunEndStep]:
    """Resolve one raw step entry to one or more typed Step objects (stateless).

    This is the legacy single-step entry point. For sequences, prefer
    :func:`resolve_combo_sequence` which threads state through for sequential moves.

    When member_builds is provided, support key resolution uses it. ``warnings``,
    if given, collects non-fatal resolution notices (currently the missing
    ``variant_label`` fallback) for the caller to surface.
    """
    steps, _ = await _resolve_one(
        raw,
        state=_ResolverState(),
        build=build,
        attack_repo=attack_repo,
        member_builds=member_builds,
        warnings=warnings,
    )
    return steps


async def resolve_combo_sequence(
    raw_sequence: list[dict],
    *,
    build: Build,
    attack_repo: AttackRepository,
    member_builds: dict[str, Build] | None = None,
    warnings: list[str] | None = None,
) -> list[ComboStep | StunTriggerStep | StunEndStep]:
    """Resolve a full ``combo.sequence`` JSON list, threading state for sequential moves.

    State is tracked **per owner** (keyed by the step's agent_id field): a foreign
    agent's step does not reset another agent's sequential-cycle position.
    When member_builds is provided, support key resolution uses it. ``warnings``,
    if given, collects non-fatal resolution notices — a saved combo whose move has
    since been re-classified to ``variant`` resolves successfully and lands one here
    rather than failing the request.
    """
    states: dict[str, _ResolverState] = {}
    out: list[ComboStep | StunTriggerStep | StunEndStep] = []
    for raw in raw_sequence or []:
        step_agent_id = raw.get("agent_id") or "dps"
        current_state = states.get(step_agent_id, _ResolverState())
        steps, new_state = await _resolve_one(
            raw,
            state=current_state,
            build=build,
            attack_repo=attack_repo,
            member_builds=member_builds,
            warnings=warnings,
        )
        states[step_agent_id] = new_state
        out.extend(steps)
    return out


# Guide: "After triggering three Attribute Anomalies, she can be brought
# on-field" -- the primary Phase Flow swap-lock unlock threshold.
PHASE_FLOW_UNLOCK_REFRINGE_COUNT = 3


def is_phase_flow_swap_legal(refringe_count: int) -> bool:
    """Combo-legality predicate for Remielle's Phase Flow swap lock (Task 16,
    DESIGN §7.3): swapping to her mid-Phase-Flow is legal once **3
    Refringes** have occurred since entry.

    The guide's alternate unlock condition — "≥1 Voidflare, when FR
    depletes" — is deliberately **not** modeled here, and not just because
    FR (Floating Radiance) arithmetic is out of scope (DESIGN §2 OQ-5).
    Task 12 captures a Voidflare on *every* Refringe (Task 12: "when
    teammates trigger Refringe... stores it as one Voidflare"), so a bare
    ``voidflare_count >= 1`` fallback is trivially true after the very
    *first* Refringe — it would silently swallow the 3-Refringe gate this
    predicate exists to enforce, not model a real alternate path. Modeling
    the alternate correctly needs live FR state to know *when* it applies
    (only "at FR depletion", not "ever"), which is exactly the arithmetic
    DESIGN scoped out. Implementing a naive version would be worse than not
    implementing it at all — a Worker judgment call, not an escalation
    (`docs/LOG_remielle.md` Task 16 entry), since the task brief already
    blesses "prefer the cheap option."

    Pure and stateless on purpose: the caller (`anomaly_simulator.simulate`)
    derives the count from its own already-recorded "refringe" events at the
    moment of the swap, so this function only ever compares one integer —
    the actual "how many Refringes happened by now" bookkeeping stays where
    the live state already lives, not duplicated here.
    """
    return refringe_count >= PHASE_FLOW_UNLOCK_REFRINGE_COUNT
