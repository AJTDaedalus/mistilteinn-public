"""Optimizer pipeline — DB resolution + sync search runner.

Separates the async DB-fetch phase from the CPU-bound optimization phase
so the latter can run on a worker thread (via JobRunner) without holding
an async DB session.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.disc import Disc
from app.models.enums import Element, PotentialVariant
from app.schemas.optimizer import (
    DiscOptimizeRequest,
    DiscOptimizeResponse,
    OptimizerDiscBuildSchema,
    OptimizerDiscSummary,
    SearchTransparencySchema,
    SubstatRollSummary,
)
from app.services.am_variants import build_am_2pc_sets, enumerate_coarse_am_values
from app.services.buff_resolver import _gated_out
from app.services.combo_types import (
    AbloomStep,
    AnomalyStep,
    ComboStep,
    LuminizeStep,
    RefringeCreditStep,
    SquadAtkCreditStep,
    Step,
    StunEndStep,
    StunTriggerStep,
    TeammateDamageStep,
)
from app.services.damage_calculator import CritMode
from app.services.damage_dag_service import evaluate_steps_total
from app.services.disc_constants import compute_rolls
from app.services.disc_optimizer import (
    DiscCandidate,
    OptimizerConstraints,
    ProgressCallback,
    SetFrame,
    optimize_discs,
)
from app.services.lumiflux import AgentRef, resolve_fluxed_element
from app.services.modifier_loader import load_agent_modifiers, load_disc_set_modifiers
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    ModifierSource,
    ModifierTarget,
)
from app.services.snapshot_builder import (
    build_snapshot_from_db,
    enemy_snapshot_from_db,
)
from app.services.support_selection import select_support_members
from app.services.team_calculator import TeamMember, _derive_auto_conditions

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.build import Build, Combo, EnemyProfile
    from app.repositories.attack import AttackRepository
    from app.repositories.build import BuildRepository, ComboRepository, EnemyProfileRepository
    from app.repositories.team import TeamRepository
    from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
    from app.services.modifiers import Modifier

CRIT_MODES = {
    "expected": CritMode.EXPECTED,
    "crit": CritMode.CRIT,
    "no_crit": CritMode.NO_CRIT,
}
_CRIT_MODES = CRIT_MODES  # backward compat alias
_DISC_SET_SOURCES = {ModifierSource.DISC_SET_2PC, ModifierSource.DISC_SET_4PC}


@dataclass
class ResolvedPayload:
    """All data needed to run the optimizer, resolved from the DB."""

    # Both are SUPPORT-FOLDED (issue #121): they are the scorer's inputs, and
    # `build.modifiers` is the only route by which a support's team buff
    # reaches a score. The simulator's support-free `SnapshotSplit.sim_base` is
    # consumed during resolution and deliberately not carried here -- nothing
    # downstream of `resolve_optimize_payload` simulates.
    scoring_base: BuildSnapshot  # disc-stripped; per-candidate base for optimize_discs
    scoring_snap: BuildSnapshot  # discs equipped; "the build as it stands" reference
    enemy_snap: EnemySnapshot
    all_step_lists: list[list[Step]]
    inventory: list[DiscCandidate]
    disc_summary_map: dict[str, OptimizerDiscSummary]
    disc_set_modifiers: dict[int, list[Modifier]]
    constraints: OptimizerConstraints
    conditions: ActiveConditions
    crit_mode: CritMode
    is_stunned: bool
    stun_dmg_mult: int
    # For response construction
    combo_ids_ordered: list[str]
    combo_id: str
    combo_name: str
    agent_name: str
    enemy_name: str
    # Value-keyed stateful simulation map (None when stateless path was used).
    # Sentinel: non-None → AM-value-map; consumers must use event_log_by_am[coarse_am].
    event_log_by_am: dict[int, list[Step]] | None = None
    # Resolved Attribute Flux target (Task 8) — override if the request set
    # one, else the derived value; None for non-Lumiflux builds and for a
    # Lumiflux build with no team / a solo team. Threaded into optimize_discs
    # so the top-K prefilter unions the *fluxed* element's `<element>_dmg`
    # disc stat instead of the (nonexistent) `lumiflux_dmg`.
    fluxed_element: str | None = None


def _strip_disc_contribution(snap: BuildSnapshot) -> BuildSnapshot:
    return replace(
        snap,
        disc_stats=[],
        modifiers=[m for m in snap.modifiers if m.source not in _DISC_SET_SOURCES],
    )


@dataclass(frozen=True)
class SnapshotSplit:
    """The three snapshots one (build, team) resolves to (issue #121).

    One snapshot used to serve two consumers with **opposite** requirements,
    and each pipeline picked a setting that was wrong for one of them:

    * The **scorer** (``evaluate_steps_total`` / ``score_disc_potential`` /
      ``_build_base_for_target``) re-scores each step against the snapshot it
      is handed, so ``build.modifiers`` is the only route by which a support's
      team buff reaches a score. It needs supports **present**.
    * The **simulator** (``resolve_stateful_am_step_lists`` →
      ``anomaly_simulator``) merges every teammate's TEAM/ACTIVE modifier into
      the acting agent itself ("Merge active acting agent modifiers with
      team-buff modifiers from teammates"), and ``resolve_modifiers`` sums
      duplicates with no dedupe. It needs supports **absent**, or a support's
      +100% ``anomaly_buildup`` resolves as +200% and fabricates anomaly procs
      that reach the scored step list.

    So the fields are named for their consumer, not for their shape:

    ``scoring_snap``
        Discs equipped, supports folded in. The "build exactly as it stands"
        reference — ``evaluate_steps_total`` for the baseline / current damage.
    ``scoring_base``
        ``scoring_snap`` with the disc contribution stripped, supports still
        folded in. The per-candidate base the scorer re-fills one disc at a
        time (``optimize_discs``, ``_build_base_for_target``).
    ``sim_base``
        Disc contribution stripped **and** supports absent. The only snapshot
        that may be handed to ``resolve_stateful_am_step_lists`` — which
        enforces that via ``folded_supports``, so a future call site cannot
        pick the wrong one silently.
    """

    scoring_snap: BuildSnapshot
    scoring_base: BuildSnapshot
    sim_base: BuildSnapshot


def build_snapshot_split(
    build: Build,
    agent: Any,
    *,
    support_builds: list[Build] | None,
    **snapshot_kwargs: Any,
) -> SnapshotSplit:
    """Resolve one build into its scorer-facing and simulator-facing snapshots.

    ``snapshot_kwargs`` are forwarded verbatim to ``build_snapshot_from_db``
    for **both** snapshots, so the two differ in exactly one input: whether
    ``support_builds`` was passed.

    The support-free half is rebuilt from the DB rather than filtered out of
    the support-folded one by ``owner_name``. That filter is not safe: the
    primary's own kit / core / W-Engine / disc modifiers carry
    ``owner_name=<dps agent name>`` too, so it deletes the primary's entire
    modifier list whenever the two agents share a name (measured in #97, pinned
    by ``test_primary_keeps_own_modifiers_when_it_also_fills_the_support_slot``).
    Two builds is a little more work and has no such failure mode.

    With no supports the two are identical by construction, so only one is
    built and the same object is shared.
    """
    scoring_snap = build_snapshot_from_db(
        build,
        agent,
        support_builds=support_builds,
        **snapshot_kwargs,
    )
    scoring_base = _strip_disc_contribution(scoring_snap)
    if not support_builds:
        return SnapshotSplit(
            scoring_snap=scoring_snap,
            scoring_base=scoring_base,
            sim_base=scoring_base,
        )
    sim_snap = build_snapshot_from_db(
        build,
        agent,
        support_builds=None,
        **snapshot_kwargs,
    )
    return SnapshotSplit(
        scoring_snap=scoring_snap,
        scoring_base=scoring_base,
        sim_base=_strip_disc_contribution(sim_snap),
    )


def _make_am_variant(base: BuildSnapshot, extra_am: int) -> BuildSnapshot:
    """Return a snapshot with extra_am layered on top of existing disc_stats.

    extra_am is a bonus delta, not a replacement. When extra_am=0 the snapshot
    is returned unchanged (same disc_stats list).
    """
    if extra_am == 0:
        return base
    bonus_entry: dict = {"main_stat_type": "anomaly_mastery", "main_stat_value": extra_am}
    return replace(base, disc_stats=[*base.disc_stats, bonus_entry])


def _parse_conditions(raw: list[str]) -> ActiveConditions:
    """Parse a request's condition strings into ``ActiveConditions``.

    ``ALWAYS`` is unioned in unconditionally, never merely as an empty-list
    fallback. It marks a modifier as *unconditional*, and the Builds
    conditions endpoint deliberately never offers it (``_SKIP_CONDITIONS`` in
    ``api/v1/builds.py``), so a build's saved ``active_conditions`` never
    contains it. Injecting it only for an empty list meant a build with any
    one real condition toggled on had its entire unconditional buff baseline
    gated off. ``team_calculator._merge_conditions`` already unions it the
    same way, which is why /damage and /simulate never showed the defect.
    """
    condition_map = {c.value: c for c in Condition}
    active = {condition_map[s] for s in raw if s in condition_map}
    active.add(Condition.ALWAYS)
    return ActiveConditions(active=active)


def _resolve_fluxed_element(
    *,
    override: str | None,
    subject_build_id: str,
    subject_element: str,
    ordered_team_builds: list[Build | None],
) -> str | None:
    """Attribute Flux resolution for the optimizer's top-K union field (Task 8).

    Explicit override always wins (DESIGN_remielle.md §5.3). Otherwise: flux
    is a Lumiflux-only mechanic (guide line 68) — every other agent's
    fluxed_element is always ``None``, unaffected by team composition.
    ``resolve_fluxed_element`` itself returns ``None`` for a solo/empty team,
    so a missing/undersized team reads as the documented no-flux default
    (pure Lumiflux, no `<element>_dmg` stat unioned), not a bug.

    ``ordered_team_builds`` is the literal ``team.build1/build2/build3`` slot
    order (may contain ``None`` for an empty slot) — the same ordering
    ``resolve_fluxed_element`` requires (DESIGN §5.1).

    F4 (hardening Task 18): the Lumiflux check now gates the OVERRIDE too, not
    just the derived value. Previously the override returned before it, so a
    `fluxed_element` on a non-Lumiflux request really did change that agent's
    behaviour: `disc_optimizer` unions `fluxed_element or agent_element`, so a
    Fire DPS sent `"ice"` had `fire_dmg` REPLACED by `ice_dmg` in both the
    top-K prefilter keep-set and the Pareto force-keep. In approximate mode
    that can drop the DPS's real `fire_dmg` discs and quietly degrade the
    result — a numeric effect the field's own contract says cannot happen
    ("Lumiflux agents only"). The value itself is separately validated against
    `Element` at the schema, so a bad string is a 422 rather than a silent
    union of nothing.
    """
    if subject_element != Element.LUMIFLUX.value:
        return None
    if override is not None:
        return override
    ordered_agents = [
        AgentRef(
            build_id=str(m.id),
            element=Element(
                m.agent.element.value if hasattr(m.agent.element, "value") else m.agent.element
            ),
        )
        for m in ordered_team_builds
        if m is not None and m.agent is not None
    ]
    subject = AgentRef(build_id=subject_build_id, element=Element(subject_element))
    try:
        derived = resolve_fluxed_element(ordered_agents, subject)
    except ValueError:
        return None
    return derived.value if derived is not None else None


def _disc_to_candidate(disc: Disc) -> DiscCandidate:
    stat_type = disc.main_stat_type
    if hasattr(stat_type, "value"):
        stat_type = stat_type.value
    slot = disc.slot
    if hasattr(slot, "value"):
        slot = slot.value
    return DiscCandidate(
        disc_id=str(disc.id),
        slot=int(slot),
        set_id=disc.disc_set.hakushin_id,
        main_stat_type=stat_type,
        main_stat_value=disc.main_stat_value,
        substats=list(disc.substats or []),
    )


def _disc_to_summary(disc: Disc) -> OptimizerDiscSummary:
    stat_type = disc.main_stat_type
    if hasattr(stat_type, "value"):
        stat_type = stat_type.value
    slot = disc.slot
    if hasattr(slot, "value"):
        slot = slot.value
    rarity = disc.rarity
    if hasattr(rarity, "value"):
        rarity = rarity.value
    substats: list[SubstatRollSummary] = []
    for sub in disc.substats or []:
        s_type = str(sub.get("stat", ""))
        s_value = int(sub.get("value", 0))
        s_rolls = int(sub.get("rolls", compute_rolls(s_type, s_value, str(rarity))))
        substats.append(SubstatRollSummary(stat_type=s_type, value=s_value, rolls=s_rolls))
    return OptimizerDiscSummary(
        disc_id=str(disc.id),
        slot=int(slot),
        set_id=disc.disc_set.hakushin_id,
        set_name=disc.disc_set.name,
        main_stat_type=str(stat_type),
        main_stat_value=disc.main_stat_value,
        rarity=str(rarity),
        substats=substats,
        icon_path=disc.disc_set.icon_path or "",
    )


def _load_set_modifiers(inventory: list[DiscCandidate]) -> dict[int, list[Modifier]]:
    unique_sets = {d.set_id for d in inventory}
    return {sid: load_disc_set_modifiers(str(sid)) for sid in unique_sets}


def _refringe_scale(detail: dict) -> float:
    """RefringeArea for one anomaly event, as a plain scalar (1.0 = no Lumiflux).

    Task 35 (E-6, ``docs/LOG_remielle.md``). Refringe multiplies the anomaly half
    of the damage split and nothing else, so dropping it does not merely understate
    a total — it moves the AP/AM-vs-CRIT optimum and changes disc *ranking*.

    Folding it into ``procs_override`` is exact rather than approximate: anomaly
    damage is linear in proc count (``calculate_build_anomaly_dag`` returns
    ``per_proc * n_procs``), and the multiplier is snapshotted per aura, so every
    tick of one aura shares one value and there is no partial-window ambiguity.

    It does not double-apply against ``disorder_mv_bp`` / ``vortex_mv_bp``: those
    derive from ``base_dmg``, and RefringeArea is applied *after* ``base_dmg`` in
    all three anomaly calculators (``damage_calculator.py`` 573 / 774 / 899).

    Defaults to neutral for every event that predates Lumiflux or has no Lumiflux
    agent on the team.
    """
    return detail.get("refringe_mult", 10000) / 10000


# Event kinds that carry no damage of their own. They are enemy-state or
# bookkeeping markers, so they belong to no agent and are never filtered by
# ownership -- a stun window opened by a teammate's hit is still a stun window
# the scored build attacks into.
_OWNERLESS_EVENT_KINDS = frozenset({"stun_trigger", "stun_end"})

# Event kinds that are ordinary standard damage: they carry a motion value and an
# attack scope, are computed by `calculate_build_damage`, and crit. They map onto
# `ComboStep` identically to `hit` and differ only in provenance.
#
# `aftershock` and `kit_formula` were previously unhandled and therefore scored as
# ZERO, behind a log warning nobody sees (#163) — so any agent whose damage flows
# through them was optimized against a fraction of its own output. Ownership needs
# no special case: `_owns` falls through to `event.agent_id` for both, which is the
# emitter, so a teammate's aftershock is still dropped.
#
# NOT included, and each for its own reason:
#   * `abloom` — anomaly-derived (`is_anomaly: True`), scaling off the original
#     anomaly's per-proc damage and AP with its own optional crit path. It needs a
#     dedicated step type with a frozen-derivation rescale, not a ComboStep.
#   * `sweeping` — named in the old warn-list but it is not an event kind at all;
#     it is a `cyclone_kind` VALUE (`anomaly_simulator.py:3070`). Nothing emits it.
_STANDARD_DAMAGE_EVENT_KINDS = frozenset(
    {"hit", "aftershock", "kit_formula", "phase_flow_unlock_assist"}
)

# RefringeArea with no Refringe applied. `_refringe_scale` already treats this as
# the identity; `_refringe_credit_step` uses it as the "nothing to attribute"
# threshold, since a tick at exactly neutral carries no uplift.
_NEUTRAL_REFRINGE_MULT = 10000

# Human-facing names for the scored-step diagnostics (#161). Keyed on the step
# CLASS rather than the originating event kind, because that is what the
# objective function actually consumed -- `phase_flow_tick` and `aftershock`
# both arrive as ComboStep, and reporting them as "hit" would be a lie about
# what was scored.
_STEP_KIND_LABELS: dict[type, str] = {
    ComboStep: "standard",
    AnomalyStep: "anomaly",
    LuminizeStep: "luminize",
    RefringeCreditStep: "refringe_credit",
    SquadAtkCreditStep: "squad_atk_credit",
    AbloomStep: "abloom",
    TeammateDamageStep: "teammate_constant",
    StunTriggerStep: "stun_marker",
    StunEndStep: "stun_marker",
}


def _anomaly_owner_share(detail: dict, owner_id: str) -> float:
    """`owner_id`'s share of one anomaly tick, as a scale on its damage.

    F-20 made a triggered anomaly's per-proc damage the buildup-share-weighted
    sum of *each contributor's own* anomaly calc, so an aura two agents fed is
    only partly the scored build's. The optimizer re-scores the whole anomaly
    against the candidate, which yields ``per_proc(candidate) * procs``; the
    scored build's actual term is ``buildup_share * per_proc(candidate)``, so
    the buildup share is exactly the scalar to fold in.

    Deliberately **not** ``per_agent_shares`` -- that one is renormalized by
    each contributor's own per-proc damage, and dividing by a per_proc the
    rescore is about to recompute would be wrong twice over.

    Falls back to the applier when the field is absent (events predating this,
    and the hand-built ones in tests): a single contributor is share 1.0, which
    is what the pre-F-20 world always was.
    """
    shares = detail.get("per_agent_buildup_shares")
    if not shares:
        return 1.0
    return float(shares.get(owner_id, 0.0))


def normalize_team_sequence(
    sequence: list[dict] | None,
    *,
    target_build_id: str,
    support_builds: list[Any] | None,
    active_index: int = 0,
    team_members: list[Any] | None = None,
) -> list[dict]:
    """Rewrite a combo sequence's ``agent_id``s into the simulator's role space.

    Task 26 (issue #112). ``resolve_stateful_am_step_lists`` always seats the
    build being optimized as ``"dps"`` and the rest as ``"support1..N"`` in the
    order ``support_builds`` was built. A stored step can name its agent three
    ways -- a build UUID, the legacy role string, or nothing at all -- and the
    legacy strings index by **team slot**, so ``"support1"`` means team member 1,
    which is not the simulator's ``"support1"`` once ``active_index`` is
    non-zero. Left unmapped, such a step resolves its move against the wrong
    build entirely.

    Raises 422 when no step belongs to the target, preserving the contract the
    pre-simulation filter used to enforce (team-builder B10).
    """
    to_sim_role: dict[str, str] = {str(target_build_id): "dps", "dps": "dps"}
    for i, sup in enumerate(support_builds or [], 1):
        to_sim_role[str(sup.id)] = f"support{i}"
        # Identity default for legacy strings; overwritten below when the team
        # slots are known and disagree.
        to_sim_role.setdefault(f"support{i}", f"support{i}")
    if team_members:
        _legacy_for_slot = {0: "dps", 1: "support1", 2: "support2"}
        _next_support = 1
        for slot, member in enumerate(team_members):
            if member is None:
                continue
            sim_role = "dps" if slot == active_index else f"support{_next_support}"
            if slot != active_index:
                _next_support += 1
            to_sim_role[str(member.id)] = sim_role
            if slot in _legacy_for_slot:
                to_sim_role[_legacy_for_slot[slot]] = sim_role

    normalized: list[dict] = []
    saw_target = False
    for step in sequence or []:
        raw = step.get("agent_id") or "dps"
        sim_role = to_sim_role.get(str(raw), raw)
        saw_target = saw_target or sim_role == "dps"
        normalized.append({**step, "agent_id": sim_role})
    if not saw_target:
        raise HTTPException(
            status_code=422,
            detail="No steps for the target agent in this combo",
        )
    return normalized


def _owns_luminize(detail: dict, owner_id: str) -> bool:
    """Is a Luminize instance scaled by ``owner_id``'s build?

    Task 26 kept every Luminize event, on the reasoning that the mapping site
    already splits them by provenance (E-8 / Task 36 ``frozen_damage``, Task 15's
    owner-scaled third shape). That split makes each step's *value* right, but it
    never asked whether the step belongs in this build's list at all -- and one of
    the three shapes does not.

    Luminize is attributed whole to the Lumiflux agent who fires it
    (``per_agent_attribution[acting_agent_id]``, ``anomaly_simulator.py:3679``),
    so when she is a **support** none of it is the scored build's damage by
    attribution. What decides inclusion here is `_owns`'s own criterion --
    *would swapping the scored build's discs move this number?* -- and the three
    shapes answer differently:

    - Voidflare captured from the scored build (``frozen_damage is None``, the
      live branch at ``disc_optimizer.py:526``). Her Luminize fractions a
      snapshot of **its** ATK/AP/DMG%/PEN, so its discs move it. **Kept** -- and
      it is why ``anomaly_proficiency`` joins the union keep-set
      (``disc_optimizer.py:692``).
    - The scored build is herself (``luminize_owner_agent_id == owner_id``).
      Her own damage; the owner-scaled shape re-folds her live half against each
      candidate. **Kept.**
    - Captured from one teammate, fired by another (both fields point away from
      the scored build). Frozen at a build the optimizer never strips and never
      varies, so no candidate can move it by a single point. **Dropped** -- it
      rode along as a pure constant that inflated ``total_damage`` with a
      teammate's move without ever changing a ranking.

    That last case is the one the sibling rule below already settles the same
    way: ``phase_flow_tick`` is excluded while she is a support precisely because
    the ticks are constant and "not the scored build's damage anyway".
    """
    return (
        detail.get("voidflare_captured_from") == owner_id
        or detail.get("luminize_owner_agent_id") == owner_id
    )


def _teammate_constant_of(payload: ResolvedPayload) -> float:
    """The un-attributable teammate constant carried by this payload's steps (A3).

    Identical across every AM-multiplexed list — the events it sums are teammate
    damage, which no coarse-AM value of the *target* changes — so the first list
    that has one is representative. Returns 0.0 when nothing was dropped, which
    is every single-agent rotation.
    """
    step_lists = (
        list(payload.event_log_by_am.values())
        if payload.event_log_by_am is not None
        else payload.all_step_lists
    )
    for steps in step_lists:
        for step in steps:
            if isinstance(step, TeammateDamageStep):
                return step.frozen_damage
    return 0.0


def _scored_event_kind_counts(payload: ResolvedPayload) -> dict[str, int]:
    """Scored steps by kind, for the optimize response's diagnostics (#161).

    Counts the STEPS that survived event→step mapping and ownership filtering —
    i.e. what the objective function actually saw — rather than the raw event
    log. That is the number a user needs: a rotation can emit a hundred Luminize
    events and score none of them if they belong to a teammate.

    The motivating case: a Remielle run whose authored rotation put her only
    Luminize trigger at step 1, before any Voidflare could exist. Luminize
    damage was exactly zero, so 100% of her scored output was crit-bearing and
    the optimizer duly recommended selling Anomaly Proficiency to buy CRIT.
    Nothing in the response said so, and diagnosing it took a direct
    `optimization_jobs` query against production.

    Reports the union across every AM-multiplexed step list rather than one, so a
    kind present at only some coarse-AM values still shows up — its absence
    everywhere is the signal, and a per-list view would hide that behind
    whichever list happened to be sampled.
    """
    counts: Counter[str] = Counter()
    step_lists = (
        list(payload.event_log_by_am.values())
        if payload.event_log_by_am is not None
        else payload.all_step_lists
    )
    for steps in step_lists:
        for step in steps:
            counts[_STEP_KIND_LABELS.get(type(step), type(step).__name__)] += 1
    return dict(counts)


def _squad_atk_grant_rows(
    build: Any, support_builds: list[Any] | None, conditions: ActiveConditions
) -> tuple[tuple[int, int], ...]:
    """The scored build's active ``atk_scale_ratio`` team-ATK grants (#160, A4).

    Returns ``((cap, ratio), …)`` for the target's own rows that grant flat ATK
    to the TEAM scaled off the target's ATK — Remielle's Additional Ability rows
    are the only instance today (ratios 600/600/2800, caps 240/240/1120, summing
    to the DB's stated shared maximum of 1600).

    Reads the **pre-bake kit JSON**, not the resolved snapshot (issue #167). The
    snapshot's rows have already been through ``_bake_atk_scaled_modifier``,
    which folds the ratio into a flat value and then *clears it*
    (``dc_replace(mod, value=baked, atk_scale_ratio=0, …)``). Selecting on
    ``atk_scale_ratio`` there matches nothing, so the credit was silently inert
    in production while its unit tests — which built ``Modifier`` objects by
    hand — passed. The bake itself is correct for its own purpose; it is the
    wrong *source* for this question.

    Team-composition conditions are derived here too, for the same reason: the
    request-resolved ``conditions`` carry only what the user toggled (``always``
    on a normal run), so the tiered gates (``anomaly_count_2/3_in_team``,
    ``same_specialty_or_faction_in_team``) would never pass. Reuses
    ``_derive_auto_conditions`` rather than re-deriving the counting rules, so a
    3-Anomaly squad activates all three tiers exactly as the team calculator
    does.

    Empty tuple when the target grants nothing — every agent but her — which
    short-circuits the emitter.
    """
    agent = getattr(build, "agent", None)
    hakushin_id = getattr(agent, "hakushin_id", None)
    if hakushin_id is None:
        return ()
    mods = load_agent_modifiers(str(hakushin_id))
    if not any(getattr(m, "atk_scale_ratio", 0) for m in mods):
        return ()

    def _member(b: Any) -> TeamMember | None:
        a = getattr(b, "agent", None)
        if a is None:
            return None
        return TeamMember(
            build_id=str(getattr(b, "id", "")),
            agent_name=getattr(a, "name", ""),
            agent_element=_enum_str(getattr(a, "element", "")),
            agent_specialty=_enum_str(getattr(a, "specialty", "")),
            agent_faction_id=getattr(a, "faction_id", 0) or 0,
            modifiers=[],
        )

    dps = _member(build)
    if dps is None:
        return ()
    supports = [m for m in (_member(b) for b in (support_builds or [])) if m is not None]
    active = set(conditions.active) | _derive_auto_conditions(dps, supports)
    resolved = replace(conditions, active=active)

    rows: list[tuple[int, int]] = []
    for mod in mods:
        if not getattr(mod, "atk_scale_ratio", 0) or mod.target is not ModifierTarget.TEAM:
            continue
        if _gated_out(
            mod,
            resolved,
            attack_scope=AttackScope.ALL,
            target_filter=ModifierTarget.TEAM,
            damage_element=None,
        ):
            continue
        rows.append((int(mod.value), int(mod.atk_scale_ratio)))
    return tuple(rows)


def _enum_str(v: Any) -> str:
    return str(getattr(v, "value", v) or "")


def _squad_atk_credit_step(
    event: Any, owner_id: str | None, grant_rows: tuple[tuple[int, int], ...]
) -> SquadAtkCreditStep | None:
    """A teammate damage instance the scored build's ATK grant scaled (#160, A4).

    Emitted on the ownership DROP path, beside the Refringe credit, and gated
    harder than it is — every guard below is a case where crediting would scale
    something the grant never touched:

    - **No active grant rows.** Every agent but Remielle, today.
    - **The event is the scored build's own.** Its ATK is already live in the
      rescore; a credit would double it.
    - **Not an ATK-scaled damage kind.** Only the standard-damage kinds carry
      ``effective_atk``. Anomaly-side attribution is a deliberate follow-up (an
      under-credit, not an over-credit) — an anomaly tick's ATK belongs to its
      *applier*, which the buildup shares already model, and folding a second
      ATK term in without reconciling the two would double-count.
    - **Sheer damage.** ``effective_atk`` holds SheerForce there, not ATK, so
      the grant is irrelevant to it (``DamageResult.is_sheer``).
    - **No ATK or no damage.** Division by zero, and nothing to attribute.
    """
    if owner_id is None or not grant_rows:
        return None
    if event.kind not in _STANDARD_DAMAGE_EVENT_KINDS:
        return None
    if getattr(event, "agent_id", None) == owner_id:
        return None
    if event.detail.get("is_sheer"):
        return None
    teammate_atk = int(event.detail.get("effective_atk", 0) or 0)
    damage = float(event.damage or 0.0)
    if teammate_atk <= 0 or damage <= 0.0:
        return None
    return SquadAtkCreditStep(
        label=f"Squad ATK credit ({event.detail.get('attack_name', event.kind)})",
        attack_id=f"squad_atk_credit_{event.kind}_{event.t}",
        frozen_teammate_damage=damage,
        teammate_atk_at_sim=teammate_atk,
        grant_rows=grant_rows,
    )


def _refringe_credit_step(event: Any, owner_id: str | None) -> RefringeCreditStep | None:
    """The scored build's attributable slice of a teammate's anomaly tick (#160).

    Returns ``None`` — meaning "nothing to credit" — in every case but one:
    an ``anomaly_tick`` that actually carried a Refringe uplift, whose Lumiflux
    agent *is* the build being scored, and which carries real damage.

    Deliberately narrow. Every guard below is a case where crediting would be
    wrong rather than merely unhelpful:

    - **Not an anomaly tick.** Refringe multiplies the anomaly half of the
      damage split and nothing else (Task 35 / E-6).
    - **No ``refringe_credit`` payload, or a neutral multiplier.** Refringe did
      not fire on this aura, so there is no uplift in the number at all and
      crediting any part of it would invent damage.
    - **A different agent's Refringe.** Two Lumiflux agents on one team is an
      unmodeled edge case, but the ownership check must still be explicit —
      crediting build A for build B's coefficient is exactly the class of error
      #112 fixed.
    - **The scored build already owns the tick.** When her buildup share is
      non-zero the tick is kept and re-scored against her stats *with*
      ``_refringe_scale`` folded into ``procs_override``, so the uplift is
      already counted; adding a credit would double it. This is why the caller
      only reaches here on the drop path.
    """
    if owner_id is None or event.kind != "anomaly_tick":
        return None
    credit = event.detail.get("refringe_credit")
    if not credit or credit.get("refringe_agent_id") != owner_id:
        return None
    mult = int(event.detail.get("refringe_mult", _NEUTRAL_REFRINGE_MULT))
    damage = float(event.damage or 0.0)
    if mult <= _NEUTRAL_REFRINGE_MULT or damage <= 0.0:
        return None
    return RefringeCreditStep(
        label=f"Refringe credit ({event.element})",
        attack_id=f"refringe_credit_{event.element}_{event.t}",
        frozen_tick_damage=damage,
        refringe_mult_at_stripped_ap=mult,
        refringe_ap_ratio_bp=int(credit.get("refringe_ap_ratio_bp", 0)),
        refringe_flat_bonus_bp=int(credit.get("refringe_flat_bonus_bp", 0)),
    )


def _owns(event: Any, owner_id: str) -> bool:
    """Is this damage event scaled by ``owner_id``'s build?

    Task 26 (issue #112). "Owns" here means *whose stats compute it*, not who
    the timeline credits or who pressed the button -- the optimizer re-scores
    every step it emits against the candidate discs, so the question that
    matters is whether swapping the scored build's discs would move this number.

    The field that answers it differs by kind:

    - ``hit`` / ``phase_flow_tick`` -- the acting agent (``agent_id``).
    - ``anomaly_tick`` -- fractional; see :func:`_anomaly_owner_share`. Non-zero
      share means partial ownership, which the caller folds into
      ``procs_override`` rather than treating as all-or-nothing.
    - ``disorder`` -- ``applier_agent_id``, **not** ``agent_id``. Disorder is
      emitted against the agent who triggered it but computed from the
      *overridden aura's* applier context (``old_ctx``,
      ``anomaly_simulator.py:2633``) and credited to that applier, so a Disorder
      the scored build triggers on a teammate's aura is teammate-scaled damage.
    - ``vortex`` -- both fields are the triggerer; either works.
    - ``luminize`` -- neither field on its own; see :func:`_owns_luminize`.
    """
    if event.kind in _OWNERLESS_EVENT_KINDS:
        return True
    if event.kind == "luminize":
        return _owns_luminize(event.detail, owner_id)
    if event.kind == "anomaly_tick":
        return _anomaly_owner_share(event.detail, owner_id) > 0.0
    if event.kind == "disorder":
        return event.applier_agent_id == owner_id
    return event.agent_id == owner_id


async def resolve_stateful_am_step_lists(  # noqa: PLR0912, PLR0915
    combo: Combo,
    build: Build,
    base_build: BuildSnapshot,
    enemy: EnemyProfile,
    attack_repo: AttackRepository,
    inventory: list[DiscCandidate],
    am_2pc_sets: dict[int, list[Modifier]],
    conditions: ActiveConditions,
    support_builds: list[Build] | None = None,
    sequence_override: list[dict] | None = None,
    disabled_buffs: list[str] | None = None,
    score_owner_id: str | None = None,
) -> dict[int, list[Step]]:
    """Resolve stateful team simulations keyed by coarse resolved Anomaly Mastery.

    Enumerates all (slot-6 AM main on/off) × (AM-granting 2pc set active/not)
    combinations from the supplied inventory, deduplicates by coarse AM value,
    runs one simulate() per distinct value, and returns a value-keyed map.

    The returned dict is the sentinel for AM-multiplexed step lists: non-None means
    consumers must use event_log_by_am[coarse_am] rather than positional indexing.

    ``conditions`` is the request-resolved BuffContext (DESIGN_buff_context.md
    §2.1) -- its ``active`` set feeds every step's active_conditions merge and
    its ``stack_counts`` becomes every team snapshot's ``stack_counts``: passed
    straight into ``build_snapshot_from_db`` for each support (issue #94), and
    via a documented ``replace()`` for ``base_build``/"dps" (already a
    ``BuildSnapshot``, not an ORM ``Build``, so it can't take the parameter).
    Neither ``active`` nor ``stack_counts`` is read from any build row.

    ``score_owner_id`` (Task 26, issue #112): when set, only events *owned* by
    that simulator role become steps. Callers that optimize or rank one build
    must pass the **full team rotation** in ``sequence_override`` -- Refringe,
    Voidflare, Disorder and every other cross-agent mechanic needs both halves
    of the team in one simulation -- and then set this so the teammates' own
    damage does not get re-scored against the candidate build. ``None`` keeps
    the historical "map every event" behaviour, which is only correct when the
    caller already passed a single-agent rotation.

    ``disabled_buffs``: request-scoped override (§7 Q1, Task A6), threaded to
    each support's own snapshot the same way -- entries are agent-qualified,
    so the one flat list addresses DPS and every support. None (default)
    preserves the old per-build column read.

    ``custom_buffs`` is deliberately **not** a parameter (#64). ``base_build``/"dps"
    already carries the request's stage buffs -- ``build_snapshot_split`` built it
    with them -- and the simulator's own merge distributes them from there:
    ``_resolve_onfield_modifiers`` gives the actor its own modifiers plus every
    teammate's TEAM/ACTIVE rows. Adding them to the support snapshots below would
    put the same buff on N snapshots, and ``resolve_modifiers`` sums duplicates
    rather than deduping -- measured at +1000 on a 2-agent team and +1500 on a
    3-agent team for a 500 flat_atk stage buff. One holder, engine distribution.

    ``base_build`` **must be support-free** (``SnapshotSplit.sim_base``, issue
    #121) -- see the guard below.

    Raises:
        ValueError: if ``base_build`` already carries a support's folded team
            modifiers.
    """
    # Issue #121. Step 1 below folds every support's own snapshot into
    # `sim_builds`, and `anomaly_simulator` then merges each teammate's
    # TEAM/ACTIVE modifiers into whichever agent is acting. A `base_build` that
    # already carries them therefore resolves them TWICE -- `resolve_modifiers`
    # sums duplicates and never dedupes -- and the error is not cosmetic: it
    # reaches the scored step list through `procs_override`, anomaly tick
    # counts, stun windows and Luminize `frozen_damage`. Refuse the input
    # rather than silently double-count it; `SnapshotSplit.sim_base` is the
    # snapshot that satisfies this.
    if base_build.folded_supports:
        msg = (
            "resolve_stateful_am_step_lists requires a support-free base_build: "
            "got one carrying folded team modifiers from "
            f"{[name for _bid, name in base_build.folded_supports]}. The simulator "
            "merges every teammate's TEAM/ACTIVE modifiers itself, so folding them "
            "in here counts them twice (issue #121). Pass SnapshotSplit.sim_base, "
            "not scoring_base/scoring_snap."
        )
        raise ValueError(msg)

    from app.data.loaders.moves import load_agent_moves  # noqa: PLC0415
    from app.models.enums import HitMode  # noqa: PLC0415
    from app.services.anomaly_simulator import (  # noqa: PLC0415
        ELEMENT_TO_ANOMALY,
        SimulatedAttackStep,
        simulate,
    )
    from app.services.channel_plan import (  # noqa: PLC0415
        build_channel_plan,
        plan_hit_offsets,
    )
    from app.services.combo_step_resolver import (  # noqa: PLC0415
        _channel_move_for,
        _classify_move,
        _ResolverState,
        resolve_channel_length,
        resolve_variant_selection,
    )
    from app.services.damage_calculator import ANOMALY_BASE, AnomalyType  # noqa: PLC0415
    from app.services.lumiflux_assembly import assemble_lumiflux_inputs  # noqa: PLC0415
    from app.services.modifiers import AttackScope  # noqa: PLC0415

    moves_db = load_agent_moves()
    context_conditions = [c.value for c in conditions.active]
    context_stack_counts = dict(conditions.stack_counts)

    # 1. Resolve team builds for simulator. stack_counts comes from the
    # request context only (DESIGN §2.1).
    #
    # `base_build` arrives here as an already-built BuildSnapshot, not an ORM
    # Build -- it cannot go through build_snapshot_from_db's stack_counts
    # parameter, so this replace() is a documented seam (issue #94), not the
    # repeated correct-it-afterward convention the rest of this function
    # avoids.
    sim_builds = {"dps": replace(base_build, stack_counts=context_stack_counts)}
    _supports = support_builds or []
    for i, sup in enumerate(_supports, 1):
        sim_builds[f"support{i}"] = build_snapshot_from_db(
            sup,
            sup.agent,
            disabled_buffs=disabled_buffs,
            stack_counts=context_stack_counts,
        )

    # 2. Resolve combo sequence to SimulatedAttackStep
    sim_steps = []
    resolver_states = {}
    _member_map: dict[str, Build] = {"dps": build}
    for i, sup in enumerate(_supports, 1):
        _member_map[f"support{i}"] = sup
    # Map build UUIDs → role strings so steps stored with UUID agent_ids resolve correctly.
    _uuid_to_role: dict[str, str] = {str(build.id): "dps"}
    for i, sup in enumerate(_supports, 1):
        _uuid_to_role[str(sup.id)] = f"support{i}"
    _sequence = sequence_override if sequence_override is not None else (combo.sequence or [])
    for step_raw in _sequence:
        move_name = step_raw.get("move_name")
        _step_agent_raw = step_raw.get("agent_id") or "dps"
        step_agent_id = _uuid_to_role.get(_step_agent_raw, _step_agent_raw)
        step_conditions = step_raw.get("conditions") or []
        variant_label = step_raw.get("variant_label")
        cycle_position = step_raw.get("cycle_position")

        active_build = _member_map.get(step_agent_id, build)

        attack_id = step_raw.get("attack_id")

        attack_scales: list[float] | None = None
        attack_offsets: list[float] | None = None
        if move_name in ("stun_trigger", "stun_end"):
            attacks = []
        elif move_name:
            attacks = await attack_repo.get_by_agent_and_name(
                str(active_build.agent_id),
                str(move_name),
                PotentialVariant.for_rank(active_build.potential_rank),
            )
            if attacks:
                hit_mode, available_labels = _classify_move(attacks)
                if hit_mode == HitMode.VARIANT:
                    # Missing label → first available, with a warning; unknown → 404.
                    # Shared with combo_step_resolver and simulate so the three agree
                    # on the row set (DESIGN_sequential_variant.md §5.8). Before this,
                    # a label-less step silently kept *every* row here.
                    chosen, _warning = resolve_variant_selection(
                        str(move_name), available_labels, variant_label
                    )
                    if chosen is not None:
                        attacks = [a for a in attacks if a.variant_label == chosen]
                        attacks = sorted(attacks, key=lambda a: a.hit_index)
                elif hit_mode == HitMode.SEQUENTIAL:
                    state = resolver_states.setdefault(step_agent_id, _ResolverState())
                    n = len(attacks)
                    skill_key = attacks[0].skill_key
                    attack_key = (skill_key, move_name)

                    pos_override = cycle_position
                    if pos_override is not None:
                        pos = pos_override % n
                    elif state.prev_attack_key == attack_key and state.prev_was_single_tap:
                        pos = (state.prev_cycle_position + 1) % n
                    else:
                        pos = 0

                    by_index = {a.hit_index: a for a in attacks}
                    chosen = by_index.get(pos)
                    if chosen is None:
                        chosen = sorted(attacks, key=lambda a: a.hit_index)[pos]
                    attacks = [chosen]

                    resolver_states[step_agent_id] = _ResolverState(
                        prev_attack_key=attack_key,
                        prev_was_single_tap=True,
                        prev_cycle_position=pos,
                    )
                elif hit_mode == HitMode.CHANNEL:
                    # Third of the three step-production paths, expanded through the same
                    # `build_channel_plan` as the resolver and /simulate — two encodings of
                    # one rotation producing different anomaly counts is the #83 defect
                    # (Task 10c). No spec authored -> every row once, unscaled: exactly what
                    # the move did before it was re-classified.
                    _chan_move = _channel_move_for(str(active_build.agent_id), str(move_name))
                    _chan_spec = _chan_move.channel if _chan_move is not None else None
                    if _chan_spec is not None:
                        _held_s, _ = resolve_channel_length(
                            str(move_name), _chan_spec, step_raw.get("channel_s")
                        )
                        # tail_s carries the non-held entry/release animation, same as the
                        # combo path — see the note at simulate._resolve_channel_rows.
                        _plan = build_channel_plan(
                            attacks,
                            _chan_spec,
                            _held_s,
                            tail_s=(_chan_move.duration_s if _chan_move else 0.0) or 0.0,
                            move_name=str(move_name),
                        )
                        attacks = [h.row for h in _plan.hits]
                        attack_scales = [h.mv_scale for h in _plan.hits]
                        attack_offsets = plan_hit_offsets(_plan)
        elif attack_id:
            # Legacy attack_id-based step: resolve by UUID and use directly.
            attack = await attack_repo.get_by_id(str(attack_id))
            attacks = [attack] if attack is not None else []
        else:
            attacks = []

        merged_conditions = list(dict.fromkeys(context_conditions + (step_conditions or [])))

        sim_steps.append(
            SimulatedAttackStep(
                agent_id=step_agent_id,
                move_name=move_name or "",
                attacks=attacks,
                conditions=merged_conditions,
                channel_s=step_raw.get("channel_s"),
                # Positionally aligned with `attacks`; set only for a channel. A tick row
                # appears once per tick and each occurrence is a FRACTION of the authored
                # multiplier -- repeating the row unscaled would multiply the move's damage
                # by the tick count.
                attack_scales=attack_scales,
                attack_offsets=attack_offsets,
            )
        )

    # 3. Enumerate distinct coarse AM values and simulate once per unique value.
    # Freedom Blues 2pc gives +30 anomaly_proficiency_flat (damage only, not buildup),
    # so it is NOT a separate simulation axis — it flows through normal stat resolution.
    base_agent_am = base_build.agent_anomaly_mastery
    coarse_am_values = enumerate_coarse_am_values(base_agent_am, inventory, am_2pc_sets)

    # Lumiflux inputs (DESIGN_remielle.md §13.2) are assembled ONCE, outside the
    # AM loop: neither the per-agent kit spec nor the rotation-derived Phase Flow
    # windows depend on Anomaly Mastery, and rebuilding them per variant would be
    # pure waste on the optimizer's hot path. `_make_am_variant` only replaces
    # the dps build's AM, so the element/source_id the assembler keys off are
    # identical across variants.
    lumiflux_inputs = assemble_lumiflux_inputs(sim_builds, sim_steps, moves_db)

    # P-F2 (hardening Task 15): is the build whose discs we are enumerating the
    # Lumiflux agent herself? If so, every Luminize event will report a support
    # as its Voidflare source (she can never capture from herself), which would
    # otherwise send all of them down the frozen branch below -- freezing HER
    # disc-stripped AP into the largest part of her own damage.
    _dps_is_lumiflux = getattr(sim_builds.get("dps"), "agent_element", "") == "lumiflux"

    event_log_by_am: dict[int, list[Step]] = {}
    for coarse_am in coarse_am_values:
        extra_am = coarse_am - base_agent_am
        variant_dps = _make_am_variant(base_build, extra_am)

        current_sim_builds = dict(sim_builds)
        current_sim_builds["dps"] = variant_dps

        sim_res = simulate(
            current_sim_builds,
            sim_steps,
            enemy,
            moves_db,
            lumiflux_specs=lumiflux_inputs.specs,
            phase_flow_windows=lumiflux_inputs.phase_flow_windows,
            fluxed_elements=lumiflux_inputs.fluxed_elements,
        )

        # 4. Map events to steps
        mapped_steps = []
        # A4 (#160): resolved once per step list rather than per event — the
        # rows and their condition gates are invariant across the rotation.
        # Empty for every build that grants no team ATK, which short-circuits
        # the emitter so no other agent pays for this.
        _squad_grant_rows = _squad_atk_grant_rows(build, support_builds, conditions)
        _teammate_constant = 0.0
        for e in sim_res.events:
            # Task 26 (issue #112). The rotation simulated above is the FULL team
            # one, so cross-agent state (Lumiflux points -> Refringe -> Voidflare,
            # aura overrides -> Disorder) actually evolves. That means teammate-owned
            # damage events are now in the stream, and every step this loop emits is
            # re-scored against the candidate discs -- so anything not owned by the
            # scored build has to be dropped here or it gets credited the target's
            # stats. Ownership is per-kind and is resolved at each branch below,
            # because the event field that carries it differs (see `_owns`).
            if score_owner_id is not None and not _owns(e, score_owner_id):
                # #160: dropping the event is right for the teammate's own
                # damage and wrong for the Refringe uplift riding on it. The
                # uplift exists only because of the scored build and scales with
                # HER Anomaly Proficiency, so it belongs to her even though
                # `_anomaly_owner_share` (a BUILDUP share, and she applies
                # Lumiflux points rather than Attribute Anomaly buildup) is 0.0.
                # Emit the attributable slice before discarding the rest.
                _credit = _refringe_credit_step(e, score_owner_id)
                if _credit is not None:
                    mapped_steps.append(_credit)
                # A4: the other stat-driven team buff. Separate from the Refringe
                # credit rather than folded in — Refringe scales only the anomaly
                # half, this scales every ATK-based instance, so they attach to
                # different events and neither implies the other.
                _atk_credit = _squad_atk_credit_step(e, score_owner_id, _squad_grant_rows)
                if _atk_credit is not None:
                    mapped_steps.append(_atk_credit)
                # A3: whatever neither credit claimed is teammate damage the scored
                # build's stats do not move. Accumulated as one constant so
                # `total_damage` can mean TEAM damage; it cannot affect ranking,
                # because no candidate changes it by a point.
                _teammate_constant += float(e.damage or 0.0)
                continue
            if e.kind in _STANDARD_DAMAGE_EVENT_KINDS:
                raw_scope = e.detail.get("scope", "all")
                scope_enum = (
                    AttackScope(raw_scope)
                    if raw_scope in AttackScope.__members__.values()
                    else AttackScope.ALL
                )
                # `hit` carries an attack name/id from its Attack row; the other
                # two do not, so fall back to something that identifies the
                # provenance rather than labelling every aftershock "Hit".
                # `kit_formula` names itself via `formula_name`.
                _default_name = e.detail.get("formula_name") or e.kind.replace("_", " ").title()
                _name = e.detail.get("attack_name", _default_name)
                mapped_steps.append(
                    ComboStep(
                        label=_name,
                        attack_id=e.detail.get("attack_id", f"{e.kind}_{e.t}"),
                        attack_name=_name,
                        scope=scope_enum,
                        multiplier=int(e.detail.get("multiplier", 0)),
                        element=e.element or "physical",
                    )
                )
            elif e.kind == "abloom":
                # #163: the last damage-carrying kind scored as zero. Only the
                # acting agent's AP is live; the aura applier's
                # `original_anomaly_dmg` stays frozen inside the simulated total.
                mapped_steps.append(
                    AbloomStep(
                        label=f"Abloom ({e.element})",
                        attack_id=f"abloom_{e.element}_{e.t}",
                        frozen_abloom_damage=float(e.damage or 0.0),
                        frozen_ap=int(e.detail.get("ap", 0) or 0),
                    )
                )
            elif e.kind == "anomaly_tick":
                # Guarded lookup: skip elements with no anomaly (e.g. Lumiflux,
                # which applies zero buildup and should never actually reach
                # here) instead of raising KeyError or mislabeling the tick with
                # a fabricated anomaly type.
                anom_type = ELEMENT_TO_ANOMALY.get(e.element)
                if anom_type is None:
                    continue
                # Task 26: `procs_override` is effective proc-equivalents, a plain
                # linear scale on the anomaly's damage, so the scored build's
                # buildup share composes with RefringeArea by multiplication --
                # the same trick Task 35 used for Refringe itself. 1.0 whenever
                # the scored build fed the aura alone, which is every case the
                # old target-only rotation could produce.
                _tick_scale = _refringe_scale(e.detail)
                if score_owner_id is not None:
                    _tick_scale *= _anomaly_owner_share(e.detail, score_owner_id)
                mapped_steps.append(
                    AnomalyStep(
                        label=f"Anomaly Tick ({e.element})",
                        attack_id=f"anomaly_tick_{e.element}_{e.t}",
                        anomaly_type=anom_type.value,
                        element=e.element or "physical",
                        procs_override=_tick_scale,
                    )
                )
            elif e.kind == "disorder":
                el = e.element or "physical"
                anom_type = ELEMENT_TO_ANOMALY.get(el, AnomalyType.BURN)
                base_mult_bp = ANOMALY_BASE[anom_type][0]
                disorder_mv = e.detail.get("disorder_mv_bp", 0)
                procs_override = float(disorder_mv) / base_mult_bp if base_mult_bp else 1.0
                procs_override *= _refringe_scale(e.detail)
                mapped_steps.append(
                    AnomalyStep(
                        label=f"Disorder ({el})",
                        attack_id=f"disorder_{el}_{e.t}",
                        anomaly_type=anom_type.value,
                        element=el,
                        procs_override=procs_override,
                    )
                )
            elif e.kind == "vortex":
                el = e.element or "physical"
                anom_type = ELEMENT_TO_ANOMALY.get(el, AnomalyType.BURN)
                base_mult_bp = ANOMALY_BASE[anom_type][0]
                vortex_mv = e.detail.get("vortex_mv_bp", 0)
                procs_override = float(vortex_mv) / base_mult_bp if base_mult_bp else 1.0
                procs_override *= _refringe_scale(e.detail)
                mapped_steps.append(
                    AnomalyStep(
                        label=f"Vortex ({el})",
                        attack_id=f"vortex_{el}_{e.t}",
                        anomaly_type=anom_type.value,
                        element=el,
                        procs_override=procs_override,
                    )
                )
            elif e.kind == "luminize":
                # Task 36 (E-8). One step per stored Voidflare. Which of the two
                # populations a step belongs to depends on who the Voidflare was
                # captured from — the store is keyed by the Lumiflux agent, so one
                # store can hold both, and they score differently.
                #
                # Captured from "dps" → the build this optimizer is enumerating
                # discs for. Its ATK/DMG%/PEN/AP have to be recomputed against
                # every candidate, because `base_build` above is disc-STRIPPED:
                # the values the simulation froze are a naked build's, and
                # carrying them would understate the step by the whole disc
                # contribution.
                #
                # Captured from a support → supports are never stripped and never
                # vary across candidates, so the simulation's own number is exact.
                _captured_from = e.detail.get("voidflare_captured_from", "")
                _vf_element = e.detail.get("voidflare_element") or "physical"
                _eff_mult_bp = int(e.detail.get("luminize_effective_mult_bp", 0))
                _frozen = None if _captured_from == "dps" else float(e.damage or 0)
                # P-F2: when SHE is the optimized DPS the frozen number is only
                # half right -- the teammate half is exact, her half is stripped.
                # Carry the two inputs that let the scorer re-fold her half
                # against each candidate's AP. Guard on a non-zero denominator:
                # the rescale divides by `effective_mult_bp`.
                _owner_scaled = (
                    _dps_is_lumiflux
                    and _frozen is not None
                    and _eff_mult_bp > 0
                    and e.detail.get("luminize_owner_agent_id") == "dps"
                )
                mapped_steps.append(
                    LuminizeStep(
                        label=f"Luminize ({_vf_element})",
                        attack_id=f"luminize_{_vf_element}_{e.t}",
                        voidflare_element=_vf_element,
                        effective_mult_bp=_eff_mult_bp,
                        def_ignore=int(e.detail.get("luminize_def_ignore", 0)),
                        constant_factor=float(e.detail.get("luminize_constant_factor", 1.0)),
                        frozen_damage=_frozen,
                        owner_base_mult_bp=(
                            int(e.detail.get("luminize_mult_bp", 0)) if _owner_scaled else None
                        ),
                        owner_ap_bonus_bp=(
                            int(e.detail.get("luminize_ap_bonus_bp", 0)) if _owner_scaled else None
                        ),
                        # Her AnomalyBoostArea as frozen into `constant_factor`.
                        # The scorer divides it out and re-multiplies by the
                        # frame's live value, so a 4pc that grants Attribute
                        # Anomaly DMG (Feathered Fate) finally shows its worth
                        # on Luminize instead of being invisible.
                        owner_anomaly_boost_mult=(
                            int(e.detail.get("anomaly_dmg_bonus_mult", 0)) or None
                            if _owner_scaled
                            else None
                        ),
                    )
                )
            elif e.kind == "stun_trigger":
                mapped_steps.append(StunTriggerStep(label="Stun"))
            elif e.kind == "stun_end":
                mapped_steps.append(StunEndStep(label="Stun End"))
            elif e.kind == "phase_flow_tick" and _dps_is_lumiflux and e.agent_id == "dps":
                # P-F2 second half (hardening Task 15, Piece 2). E-6 ruling (c)
                # excluded Phase Flow ticks from the step list on the grounds
                # that their damage is invariant across the disc axis. That
                # holds while the Lumiflux agent is a SUPPORT -- her build is
                # never stripped and never varies, so the ticks really are
                # constant, and they are not the scored build's damage anyway.
                #
                # When she IS the optimized DPS, both halves of that argument
                # fail: the ticks are her damage and they scale with her discs.
                # Leaving them unscored made her Phase Flow contribute exactly
                # ZERO to disc ranking.
                #
                # Mapped as an ordinary Special-scope hit at the tick's
                # expected-value multiplier, which is what it is -- the
                # simulator computes it with `calculate_build_damage` at
                # AttackScope.SPECIAL.
                #
                # B3 (was a KNOWN APPROXIMATION): the simulator resolves a tick
                # under the OFF-FIELD merge plus PHASE_FLOW_ACTIVE, and a
                # ComboStep used to be scored under the frame's ordinary
                # conditions -- so an ACTIVE-target buff the sim correctly
                # excluded reached the scored tick. `off_field=True` below now
                # drops those rows for this step alone.
                mapped_steps.append(
                    ComboStep(
                        # B3: the simulator resolved this tick under the OFF-FIELD
                        # merge; without the flag it would be re-scored with
                        # ACTIVE-target buffs applied, a bounded over-credit.
                        off_field=True,
                        label="Phase Flow tick",
                        attack_id=f"phase_flow_tick_{e.t}",
                        attack_name="Phase Flow tick",
                        scope=AttackScope.SPECIAL,
                        multiplier=int(e.detail.get("ev_mv_bp", 0)),
                        element=e.element or "lumiflux",
                    )
                )
            elif e.kind in _DELIBERATELY_UNSCORED_EVENT_KINDS:
                pass
            elif (e.damage or 0) > 0 and e.kind not in _warned_unscored_event_kinds:
                # F5 (hardening Task 18). This chain used to fall off the end
                # with no `else`, so any damage-carrying event kind it did not
                # know about was scored as zero, silently. That is precisely
                # the failure mode E-8 acceptance item 4 added strict
                # `TypeError` guards against on the STEP side; the event side
                # was left a sieve. Warning rather than raising because the
                # unhandled kinds predated that work and raising would have
                # broken live requests -- but the next Lumiflux-like mechanic
                # to emit a new event kind now announces itself.
                #
                # #163 cleared most of that backlog. `aftershock` and
                # `kit_formula` are now scored (both are ordinary standard
                # damage -- see `_STANDARD_DAMAGE_EVENT_KINDS`), and `sweeping`
                # turned out never to have been an event kind at all: it is a
                # `cyclone_kind` value. Only `abloom` is still genuinely
                # unhandled, because it is anomaly-derived and needs a step type
                # rather than a ComboStep.
                _warned_unscored_event_kinds.add(e.kind)
                logger.warning(
                    "Optimizer event->step mapping has no case for event kind %r, "
                    "which carries damage (%s). Every instance of it is being "
                    "scored as ZERO, so the optimizer is ranking on an "
                    "understated total. Add a branch above, or list the kind in "
                    "`_DELIBERATELY_UNSCORED_EVENT_KINDS` with a reason. Warned "
                    "once per kind per process.",
                    e.kind,
                    e.damage,
                )

        # A3: one constant per list, appended last. Zero when nothing was dropped
        # (a single-agent rotation, or a target that owns every event), in which
        # case no step is emitted at all and the totals are byte-identical.
        if _teammate_constant > 0.0:
            mapped_steps.append(
                TeammateDamageStep(
                    label="Teammate damage (not attributable)",
                    attack_id=f"teammate_constant_{coarse_am}",
                    frozen_damage=_teammate_constant,
                )
            )
        event_log_by_am[coarse_am] = mapped_steps

    return event_log_by_am


logger = logging.getLogger(__name__)

# Event kinds the optimizer's event->step mapping deliberately does not score
# (F5, hardening Task 18). Listed explicitly so the fallback warning below can
# tell "we decided not to score this" apart from "nobody has looked at this".
_DELIBERATELY_UNSCORED_EVENT_KINDS: frozenset[str] = frozenset(
    {
        # E-6 ruling (c): Phase Flow ticks are excluded from the step list
        # because their damage was argued invariant across the disc axis. That
        # argument holds only while the Lumiflux agent is a SUPPORT. When she
        # is the optimized DPS the branch ABOVE this one catches the tick
        # first and maps it as a real scored step (P-F2, hardening Task 15),
        # so this entry now covers the support case alone.
        "phase_flow_tick",
        # Bookkeeping events, no damage of their own. Every one of these is
        # emitted with `damage=None`, so they would fall past the warn tail
        # silently anyway (it is guarded on `damage > 0`); listing them is
        # what makes `test_event_kind_classification` able to assert that
        # EVERY emitted kind is accounted for, rather than only the noisy ones.
        "switch",
        "lumiflux_point",
        "refringe",
        "anomaly",
        # Was "energy" (#163): no such kind is emitted. The simulator emits
        # `energy_spend`, so the old entry matched nothing and the real kind
        # was unclassified.
        "energy_spend",
        "expire",
        "refresh",
    }
)

# One warning per unhandled kind per process.
_warned_unscored_event_kinds: set[str] = set()


async def resolve_optimize_payload(  # noqa: PLR0912, PLR0915
    session: AsyncSession,
    body: DiscOptimizeRequest,
    combo_repo: ComboRepository,
    build_repo: BuildRepository,
    attack_repo: AttackRepository,
    enemy_repo: EnemyProfileRepository,
    team_repo: TeamRepository | None = None,
) -> ResolvedPayload:
    """Async DB-fetch phase: resolve all entities and build the payload."""
    combo_id_list: list[str] = (
        body.combo_ids if body.combo_ids else [body.combo_id]  # type: ignore[list-item]
    )

    combos: list[Combo] = []
    build = None
    # F6 (hardening Task 18): initialised before the loop rather than only
    # inside `if build is None:`. Reachability today rests on
    # `DiscOptimizeRequest._validate_combo_source` guaranteeing a non-empty
    # combo list -- an invariant living two files away in a Pydantic
    # validator. A future "combo optional" change or a reordering of this
    # loop turns a possibly-unbound local into a 500 (NameError) on the
    # request path. An empty list is also the correct default: it yields a
    # None flux via `resolve_fluxed_element`'s solo/empty-team rule.
    team_members_for_build: list[Any] = []
    for cid in combo_id_list:
        combo = await combo_repo.get_by_id(cid)
        if combo is None:
            raise HTTPException(status_code=404, detail=f"Combo not found: {cid}")
        combos.append(combo)
        if build is None:
            team_id_for_build = body.team_id or combo.team_id
            if team_repo is None:
                raise HTTPException(status_code=500, detail="team_repo required")
            team_for_build = await team_repo.get_by_id(team_id_for_build)
            if team_for_build is None:
                raise HTTPException(status_code=404, detail="Team not found")
            team_members_for_build = [
                team_for_build.build1,
                team_for_build.build2,
                team_for_build.build3,
            ]
            build = team_members_for_build[body.active_index]
            if build is None:
                raise HTTPException(status_code=404, detail="Build not found at active_index")

    enemy = await enemy_repo.get_by_id(body.enemy_profile_id)
    if enemy is None:
        raise HTTPException(status_code=404, detail="Enemy profile not found")

    agent = build.agent  # type: ignore[union-attr]
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found on build")

    # Resolve explicit support builds from team when team_id is provided.
    support_builds: list[Build] | None = None
    if body.team_id and team_repo is not None:
        team = await team_repo.get_by_id(body.team_id)
        if team is None:
            raise HTTPException(status_code=404, detail=f"Team not found: {body.team_id}")
        members = [team.build1, team.build2, team.build3]
        idx = body.active_index
        support_builds = select_support_members(members, idx)
    elif team_members_for_build:
        # The target build itself was resolved from `body.team_id or combo.team_id`
        # above, and so was `fluxed_element` -- but supports were gated on
        # `body.team_id` alone, so a request that named only a combo got the right
        # target out of the combo's team and then simulated it with nobody else on
        # the field. Post-Task 26 that is worse than it used to be: the full team
        # rotation now survives normalization, so every teammate step reaches
        # `simulate()` with no build behind it and is dropped as "Build not found"
        # (`anomaly_simulator.py:1893`) -- Refringe silently off again, by a third
        # route. Same team, same active_index, same slot order as the branch above.
        support_builds = select_support_members(
            list(team_members_for_build), body.active_index
        )

    crit_mode = _CRIT_MODES.get(body.crit_mode)
    if crit_mode is None:
        raise HTTPException(status_code=422, detail=f"Invalid crit_mode: {body.crit_mode}")

    mc_level = (
        body.mindscape_level if body.mindscape_level is not None else build.mindscape_level  # type: ignore[union-attr]
    )
    # DESIGN §2.1 / issue #94: body.stack_counts is the request-scoped value
    # for this whole payload, available here just as body.disabled_buffs is.
    # It is redundant with the later `replace()` when the sim base reaches the
    # "dps" sim build (that seam stays -- it is already a BuildSnapshot by
    # then), but passing it here means the snapshots themselves never silently
    # carry the DB row's value either.
    #
    # Issue #121: this used to be ONE snapshot built with `support_builds=`,
    # feeding both the scorer (which needs the supports) and the simulator
    # (which merges teammate TEAM/ACTIVE mods itself, so folding them in here
    # made it resolve them twice -- fabricated anomaly procs in the scored step
    # list, not a cosmetic stat). `build_snapshot_split` returns one snapshot
    # per requirement; see SnapshotSplit.
    snaps = build_snapshot_split(
        build,
        agent,
        support_builds=support_builds,
        refinement=body.refinement,
        mindscape_level=mc_level,
        disabled_buffs=body.disabled_buffs,
        stack_counts=dict(body.stack_counts),
        custom_buffs=body.custom_buffs,
    )

    element = agent.element.value if hasattr(agent.element, "value") else agent.element
    enemy_snap = enemy_snapshot_from_db(enemy, element)

    fluxed_element = _resolve_fluxed_element(
        override=body.fluxed_element,
        subject_build_id=str(build.id),  # type: ignore[union-attr]
        subject_element=element,
        ordered_team_builds=team_members_for_build,
    )

    conditions = _parse_conditions(body.active_conditions)
    conditions.stack_counts = body.stack_counts

    # Load inventory first so the stateful precompute can enumerate AM combinations.
    if body.disc_ids is not None:
        stmt = select(Disc).where(Disc.id.in_(body.disc_ids)).options(selectinload(Disc.disc_set))
    elif body.inventory_scope == "priority":
        excluded = await build_repo.higher_priority_equipped_disc_ids(build)  # type: ignore[arg-type]
        excluded -= set(body.locked_slots.values())
        stmt = (
            select(Disc)
            .where(Disc.id.notin_(excluded) if excluded else True)  # type: ignore[arg-type]
            .options(selectinload(Disc.disc_set))
        )
    else:
        stmt = (
            select(Disc)
            .where((Disc.build_id.is_(None)) | (Disc.build_id == build.id))  # type: ignore[union-attr]
            .options(selectinload(Disc.disc_set))
        )
    result = await session.execute(stmt)
    discs = list(result.scalars().all())
    inventory = [_disc_to_candidate(d) for d in discs]
    disc_summary_map = {str(d.id): _disc_to_summary(d) for d in discs}
    disc_set_modifiers = _load_set_modifiers(inventory)
    am_2pc_sets = build_am_2pc_sets(disc_set_modifiers)

    # Task 26 (issue #112). This used to DROP every non-target step before
    # simulating, on the reasoning that "the optimizer only evaluates the target".
    # That reasoning is about which damage to *score*; cutting the rotation also
    # decides which state *exists*, and the two are not the same question. Refringe
    # needs Remielle's move to bank a Lumiflux point AND a teammate's anomaly
    # trigger to consume it, Disorder needs a teammate's aura to override -- so a
    # target-only rotation silently switched off every cross-agent mechanic.
    #
    # Now the whole rotation is simulated and ownership is enforced on the
    # resulting *events* (`score_owner_id` below). What survives here is only the
    # normalization: rewrite each step's agent_id into the simulator's role space,
    # so the target is `"dps"` whatever its team slot, and the 422 contract.
    def _normalized_team_steps(c: Combo) -> list[dict]:
        return normalize_team_sequence(
            c.sequence,
            target_build_id=str(build.id),  # type: ignore[union-attr]
            support_builds=support_builds,
            active_index=body.active_index,
            team_members=team_members_for_build,
        )

    event_log_by_am: dict[int, list[Step]] | None = None
    all_step_lists: list[list[Step]] = []
    # Always use the stateful engine. Single-combo: full AM multiplexing via event_log_by_am.
    # Multi-combo: one simulate() call per combo (base AM); event_log_by_am stays None so the
    # optimizer evaluates all combos and takes the max.
    if len(combos) == 1:
        primary_combo = combos[0]
        event_log_by_am = await resolve_stateful_am_step_lists(
            combo=primary_combo,
            build=build,
            base_build=snaps.sim_base,
            enemy=enemy,
            attack_repo=attack_repo,
            inventory=inventory,
            am_2pc_sets=am_2pc_sets,
            conditions=conditions,
            support_builds=support_builds,
            sequence_override=_normalized_team_steps(primary_combo),
            disabled_buffs=body.disabled_buffs,
            score_owner_id="dps",
        )
        all_step_lists = list(event_log_by_am.values())
    else:
        for combo in combos:
            am_map = await resolve_stateful_am_step_lists(
                combo=combo,
                build=build,
                base_build=snaps.sim_base,
                enemy=enemy,
                attack_repo=attack_repo,
                inventory=inventory,
                am_2pc_sets=am_2pc_sets,
                conditions=conditions,
                support_builds=support_builds,
                sequence_override=_normalized_team_steps(combo),
                disabled_buffs=body.disabled_buffs,
                score_owner_id="dps",
            )
            # Use the first (base-AM) entry; per-disc AM lookup is not supported for multi-combo.
            all_step_lists.append(next(iter(am_map.values())))

    frames = None
    if body.allowed_frames is not None:
        frames = [SetFrame(counts=f.counts) for f in body.allowed_frames]

    # Task 15: derive the rotation's Energy bill rather than asking the caller for it. On a
    # channel the caller *cannot* compute it — the bill depends on how long each press is
    # held — and even off one, a hand-supplied number is free to disagree with what the
    # simulator actually spends.
    #
    # Gated on `rotation_duration_s > 0`, and that guard is load-bearing rather than
    # cosmetic. `disc_optimizer` gates only on `rotation_energy_cost > 0`, and its
    # feasibility factor is `energy_gen / cost` where `energy_gen` is proportional to the
    # duration. So handing it a derived cost with the default duration of 0 would compute
    # `0 / cost = 0` and credit EVERY build's EX damage at ZERO — a silent, total ranking
    # corruption for every existing caller. Supplying a duration is the caller's statement
    # that they want energy modelled; without it nothing changes.
    _derived_energy_cost = body.rotation_energy_cost
    if _derived_energy_cost is None and body.rotation_duration_s > 0:
        from app.data.loaders.moves import load_agent_moves  # noqa: PLC0415
        from app.services.anomaly_simulator import _agent_key  # noqa: PLC0415
        from app.services.rotation_cost import derive_rotation_energy_cost  # noqa: PLC0415

        _dps_snap = snaps.sim_base
        _dps_moves = load_agent_moves().get(_agent_key(_dps_snap.agent_name))
        _derived_energy_cost = derive_rotation_energy_cost(
            all_step_lists[0] if all_step_lists else [],
            {"dps": _dps_snap},
            {"dps": getattr(_dps_moves, "moves", {}) or {}},
            owner_id="dps",
        )

    constraints = OptimizerConstraints(
        locked_slots=body.locked_slots,
        required_sets=body.required_sets,
        min_stats=body.min_stats,
        allowed_frames=frames,
        top_n=body.top_n,
        prefilter_top_k=body.prefilter_top_k,
        rotation_energy_cost=_derived_energy_cost,
        rotation_duration_s=body.rotation_duration_s,
    )

    primary_combo = combos[0]
    combo_ids_ordered = [str(c.id) for c in combos]

    return ResolvedPayload(
        scoring_base=snaps.scoring_base,
        scoring_snap=snaps.scoring_snap,
        enemy_snap=enemy_snap,
        all_step_lists=all_step_lists,
        inventory=inventory,
        disc_summary_map=disc_summary_map,
        disc_set_modifiers=disc_set_modifiers,
        constraints=constraints,
        conditions=conditions,
        crit_mode=crit_mode,
        is_stunned=body.is_stunned,
        stun_dmg_mult=body.stun_dmg_mult,
        combo_ids_ordered=combo_ids_ordered,
        combo_id=str(primary_combo.id),
        combo_name=primary_combo.name,
        agent_name=agent.name,
        enemy_name=enemy.name,
        event_log_by_am=event_log_by_am,
        fluxed_element=fluxed_element,
    )


def _estimate_total_space(payload: ResolvedPayload) -> int:
    """Raw per-slot Cartesian-product size before prefilter/Pareto reduction (Task B5).

    Counts inventory candidates per slot (respecting locked_slots) in a single
    pass — no combo scoring, so this stays cheap regardless of inventory size.
    """
    locked = payload.constraints.locked_slots
    counts = dict.fromkeys(range(1, 7), 0)
    for d in payload.inventory:
        if d.slot not in counts:
            continue
        if d.slot in locked and d.disc_id != locked[d.slot]:
            continue
        counts[d.slot] += 1
    total = 1
    for c in counts.values():
        total *= c
    return total


def _build_search_summary(
    *,
    total_space: int,
    evaluated: int,
    is_exact: bool,
    effective_k: int | None,
) -> str:
    """Human-readable one-liner alongside SearchTransparencySchema (Task B5)."""
    if is_exact:
        return f"Searched all {evaluated:,} combinations (exact)."
    summary = f"Searched {evaluated:,} of ~{total_space:,} combinations"
    if effective_k is not None:
        summary += f" (top-K prefilter K={effective_k} applied — "
    else:
        summary += " ("
    summary += "results are near-exact; run exact search to verify)."
    return summary


def _compute_current_build_damage(payload: ResolvedPayload) -> float:
    damages = [
        evaluate_steps_total(
            build=payload.scoring_snap,
            enemy=payload.enemy_snap,
            steps=steps,
            conditions=payload.conditions,
            crit_mode=payload.crit_mode,
            is_stunned=payload.is_stunned,
            stun_dmg_mult=payload.stun_dmg_mult,
        )
        for steps in payload.all_step_lists
    ]
    return max(damages)


def run_optimizer_pipeline(payload: ResolvedPayload) -> DiscOptimizeResponse:
    """Sync CPU-bound phase: run search and build the response."""
    return run_optimizer_pipeline_with_progress(payload, progress_callback=None)


def run_optimizer_pipeline_with_progress(
    payload: ResolvedPayload,
    progress_callback: ProgressCallback | None,
) -> DiscOptimizeResponse:
    """Sync CPU-bound phase with optional progress reporting."""
    result = optimize_discs(
        base_build=payload.scoring_base,
        enemy=payload.enemy_snap,
        combo_steps=payload.all_step_lists[0],
        combo_steps_set=payload.all_step_lists
        if (len(payload.all_step_lists) > 1 and payload.event_log_by_am is None)
        else None,
        event_log_by_am=payload.event_log_by_am,
        am_2pc_sets=(
            build_am_2pc_sets(payload.disc_set_modifiers)
            if payload.event_log_by_am is not None
            else None
        ),
        inventory=payload.inventory,
        disc_set_modifiers=payload.disc_set_modifiers,
        constraints=payload.constraints,
        conditions=payload.conditions,
        crit_mode=payload.crit_mode,
        is_stunned=payload.is_stunned,
        stun_dmg_mult=payload.stun_dmg_mult,
        progress_callback=progress_callback,
        fluxed_element=payload.fluxed_element,
    )

    current_build_damage = _compute_current_build_damage(payload)

    is_exact = result.prefiltered == 0 and result.auto_prefilter_k is None
    total_space = _estimate_total_space(payload)
    effective_k = (
        result.auto_prefilter_k
        if result.auto_prefilter_k is not None
        else payload.constraints.prefilter_top_k
    )
    search_transparency = SearchTransparencySchema(
        total_space=total_space,
        evaluated=result.evaluated,
        pruned_sets=result.pruned_sets,
        pruned_stats=result.pruned_stats,
        prefiltered=result.prefiltered,
        auto_prefilter_k=result.auto_prefilter_k,
        is_exact=is_exact,
        pareto_removed=result.pareto_removed,
        scored_event_kinds=_scored_event_kind_counts(payload),
    )
    search_summary = _build_search_summary(
        total_space=total_space,
        evaluated=result.evaluated,
        is_exact=is_exact,
        effective_k=effective_k,
    )

    return DiscOptimizeResponse(
        combo_id=payload.combo_id,
        combo_name=payload.combo_name,
        agent_name=payload.agent_name,
        enemy_name=payload.enemy_name,
        current_build_damage=current_build_damage,
        builds=[
            OptimizerDiscBuildSchema(
                total_damage=b.total_damage,
                # A3: the constant the step lists carry, surfaced so a consumer
                # can recover the target-attributed share by subtraction rather
                # than us shipping two fields that are equal until it is non-zero.
                teammate_unattributed_damage=_teammate_constant_of(payload),
                disc_ids=b.disc_ids,
                set_counts=b.set_counts,
                per_combo_damage=dict(
                    zip(payload.combo_ids_ordered, b.per_combo_damage, strict=False)
                ),
                discs=[
                    payload.disc_summary_map[disc_id]
                    for disc_id in b.disc_ids
                    if disc_id in payload.disc_summary_map
                ],
                total_stats=b.total_stats,
            )
            for b in result.builds
        ],
        evaluated=result.evaluated,
        pruned_sets=result.pruned_sets,
        pruned_stats=result.pruned_stats,
        prefiltered=result.prefiltered,
        auto_prefilter_k=result.auto_prefilter_k,
        search_transparency=search_transparency,
        search_summary=search_summary,
        fluxed_element=payload.fluxed_element,
    )
