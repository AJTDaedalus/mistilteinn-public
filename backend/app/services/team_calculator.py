"""Team calculator — orchestrates combo evaluation with team-context buffs.

Phase 5A scope (DPS-only):
    - One designated DPS build is selected per request; the team's other
      members contribute via ``target=team`` modifiers and via auto-derived
      team-composition conditions (e.g. ``STUN_IN_TEAM``) that unlock
      conditional buffs on the DPS.
    - Only the DPS's combo damage is computed. Supports do not contribute
      off-field damage yet.

Phase 5B (done):
    - Full multi-agent team evaluation: each member's combo steps are
      owned via ``agent_id`` on ``ComboStep``; per-step builds are resolved
      in the simulator; ``by_agent`` breakdown is populated. The optimizer
      and ranker filter combo steps to the target agent via
      ``sequence_override`` in ``resolve_stateful_am_step_lists``.

The calculator is stateless and pure: it takes value objects (TeamMembers,
a pre-built DPS ``BuildSnapshot``, an ``EnemySnapshot``, and a list of
``ComboStep``) and returns a ``TeamCalculationResult``. The API layer is
responsible for loading DB models, building snapshots, and translating
saved combos into combo steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from app.services.anomaly_simulator import simulate_combo_steps
from app.services.buff_resolver import resolve_modifiers
from app.services.buff_roster import BuffRosterEntry, pivot_buff_roster
from app.services.combo_types import sim_result_to_combo_evaluation
from app.services.damage_calculator import CritMode
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierTarget,
)

if TYPE_CHECKING:
    from typing import Any

    from app.services.build_damage_service import BuildSnapshot
    from app.services.combo_types import ComboEvaluationResult, ComboStep


# Specialty → team-composition condition unlocked by its presence.
# Keys match Agent.specialty values (lower-case) as stored in DB / snapshots.
# Presence family: team-global, include the owner (see Condition docstring).
_SPECIALTY_TO_CONDITION: dict[str, Condition] = {
    "stun": Condition.STUN_IN_TEAM,
    "anomaly": Condition.ANOMALY_IN_TEAM,
    "support": Condition.SUPPORT_IN_TEAM,
    "rupture": Condition.RUPTURE_IN_TEAM,
    "attack": Condition.ATTACK_IN_TEAM,
    "defense": Condition.DEFENSE_IN_TEAM,
}


@dataclass(frozen=True)
class TeamMember:
    """One member of a 3-agent team.

    ``modifiers`` carries the member's kit / W-Engine / disc-set / mindscape
    modifiers that are *potentially visible to teammates* — i.e. modifiers
    with ``target=team``. Self-targeted modifiers may be included; they'll
    be filtered out for cross-member application but are still tracked for
    Phase 5B multi-agent evaluation (done: see ``calculate_team_combo`` with ``member_snapshots``).
    """

    build_id: str
    agent_name: str
    agent_element: str
    agent_specialty: str
    agent_faction_id: int
    modifiers: list[Modifier] = field(default_factory=list)


@dataclass(frozen=True)
class AppliedTeamBuff:
    """One team-target modifier from a support that contributed to the DPS.

    Used for UI attribution: "Lucy's ATK Boost gave +50% ATK". Only
    modifiers whose conditions are met in the final merged context are
    listed here.
    """

    source_build_id: str
    source_agent_name: str
    source_label: str
    stat: str
    value: int


@dataclass(frozen=True)
class AgentContribution:
    """Per-agent damage attribution for Phase 5B multi-agent evaluation."""

    agent_name: str
    build_id: str
    damage: float
    pct: float


@dataclass(frozen=True)
class TeamCalculationResult:
    """Team-context combo evaluation result for the DPS."""

    combo_result: ComboEvaluationResult
    dps_build_id: str
    dps_agent_name: str
    auto_conditions: list[str]
    applied_team_buffs: list[AppliedTeamBuff]
    by_agent: list[AgentContribution] = field(default_factory=list)
    # Build-level "every resolved buff, once" panel for the DPS's evaluated
    # snapshot (DESIGN_explainability.md §2.3). Always populated -- cheap,
    # pure re-labelling of contributions already computed for stat
    # resolution; API layer decides whether to surface it (with_attribution).
    buff_roster: list[BuffRosterEntry] = field(default_factory=list)


def _build_buff_roster(
    snap: BuildSnapshot,
    conditions: ActiveConditions,
) -> list[BuffRosterEntry]:
    """Pivot the resolved buffs on *snap* into a build-level roster."""
    resolved = resolve_modifiers(
        snap.modifiers,
        conditions,
        attack_scope=AttackScope.ALL,
        target_filter=ModifierTarget.SELF,
    )
    return pivot_buff_roster(resolved)


def _derive_owner_relative_conditions(
    owner: TeamMember,
    others: list[TeamMember],
) -> set[Condition]:
    """SAME_*/union-family conditions for *owner*, checking only *others*.

    Owner-relative (D-KV14): "another squad member shares X" excludes the
    owner from the check. Call once per member whose modifiers are about
    to be resolved, passing every *other* team member as ``others``.
    """
    active: set[Condition] = set()
    shares_element = any(o.agent_element == owner.agent_element for o in others)
    shares_faction = bool(owner.agent_faction_id) and any(
        o.agent_faction_id == owner.agent_faction_id for o in others
    )
    shares_specialty = any(o.agent_specialty == owner.agent_specialty for o in others)
    other_is_stun = any(o.agent_specialty == "stun" for o in others)

    if shares_element:
        active.add(Condition.SAME_ELEMENT_IN_TEAM)
    if shares_faction:
        active.add(Condition.SAME_FACTION_IN_TEAM)
    if shares_element or other_is_stun:
        active.add(Condition.SAME_ATTRIBUTE_OR_STUN_IN_TEAM)
    if shares_specialty or shares_faction:
        active.add(Condition.SAME_SPECIALTY_OR_FACTION_IN_TEAM)
    if shares_element or shares_faction:
        active.add(Condition.SAME_ATTRIBUTE_OR_FACTION_IN_TEAM)
    if shares_element or shares_faction or other_is_stun:
        active.add(Condition.SAME_ATTRIBUTE_OR_FACTION_OR_STUN_IN_TEAM)
    return active


def _derive_auto_conditions(
    dps: TeamMember,
    supports: list[TeamMember],
) -> set[Condition]:
    """Auto-derive team-composition conditions for *dps*, treating it as owner.

    Presence-family conditions (STUN/ANOMALY/SUPPORT/RUPTURE/ATTACK/
    DEFENSE_IN_TEAM) are team-global: triggered by any member having the
    specialty, including the DPS itself.

    SAME_*/union-family conditions are owner-relative: they only look at
    *supports* (the DPS is excluded from its own check). Call this once per
    member whose modifiers are being resolved -- ``dps`` is that member,
    ``supports`` is everyone else on the team.
    """
    all_members = [dps, *supports]
    active: set[Condition] = set()

    for m in all_members:
        cond = _SPECIALTY_TO_CONDITION.get(m.agent_specialty)
        if cond is not None:
            active.add(cond)

    # Remielle's tiered ATK buff (DESIGN_remielle.md §6.1, Task 17): same
    # presence-family semantics as the bare *_IN_TEAM checks above
    # (team-global, include the owner) but counting rather than merely
    # detecting. Both may be active at once in a 3-Anomaly team -- the
    # kit JSON authors three ADDITIVE rows gated on
    # SAME_SPECIALTY_OR_FACTION_IN_TEAM / COUNT_2 / COUNT_3 respectively, so
    # a 3-Anomaly squad needs all three conditions simultaneously true for
    # the rows to stack correctly (Task 18).
    anomaly_count = sum(1 for m in all_members if m.agent_specialty == "anomaly")
    if anomaly_count >= 2:  # noqa: PLR2004
        active.add(Condition.ANOMALY_COUNT_2_IN_TEAM)
    if anomaly_count >= 3:  # noqa: PLR2004
        active.add(Condition.ANOMALY_COUNT_3_IN_TEAM)

    active |= _derive_owner_relative_conditions(dps, supports)
    return active


def _merge_conditions(
    user_conditions: ActiveConditions,
    auto: set[Condition],
) -> ActiveConditions:
    """Merge auto-derived conditions into the user-provided ActiveConditions."""
    return ActiveConditions(
        active=user_conditions.active | auto | {Condition.ALWAYS},
        stack_counts=dict(user_conditions.stack_counts),
    )


def _collect_team_modifiers(supports: list[TeamMember]) -> list[Modifier]:
    """Collect target=team and target=active modifiers from support members.

    Self-targeted support modifiers are dropped — they belong to that
    support's own damage path (handled in Phase 5B via ``member_snapshots``), not the DPS's.
    """
    out: list[Modifier] = []
    for sup in supports:
        out.extend(
            m for m in sup.modifiers if m.target in (ModifierTarget.TEAM, ModifierTarget.ACTIVE)
        )
    return out


def _attribute_team_buffs(
    supports: list[TeamMember],
    all_members: list[TeamMember],
    user_conditions: ActiveConditions,
) -> list[AppliedTeamBuff]:
    """List the team-target and active-target modifiers from supports that are actually active.

    Scope filtering is intentionally ignored here — attribution describes
    "which buffs are live for this team/context", not "which buffs hit
    this specific attack step". A buff scoped to BASIC still counts as an
    active team buff even if the current combo is all ULT.

    Each support's SAME_*/union conditions are derived from *its own*
    owner-relative view (itself excluded from its own check), not the DPS's —
    a support's ability gate depends on what its teammates share with *it*.

    **Stage buffs (#64) are deliberately absent from this list.** It answers "what are my
    teammates granting me", and a Deadly-Assault / Shiyu buff is granted by the encounter,
    not by a team member -- it has no `source_build_id` to attribute it to. It reaches the
    arithmetic through the primary's snapshot and is surfaced on the explain path by the
    buff roster and the per-zone attribution, which is where a source-less buff belongs.
    (On `dev` it did appear here, once per support -- but that was the double-count
    described in `_load_team_context`, not attribution working.)
    """
    applied: list[AppliedTeamBuff] = []
    for sup in supports:
        others = [m for m in all_members if m.build_id != sup.build_id]
        sup_conditions = _merge_conditions(user_conditions, _derive_auto_conditions(sup, others))
        for mod in sup.modifiers:
            if mod.target not in (ModifierTarget.TEAM, ModifierTarget.ACTIVE):
                continue
            if not sup_conditions.is_met(mod.conditions):
                continue
            applied.append(
                AppliedTeamBuff(
                    source_build_id=sup.build_id,
                    source_agent_name=sup.agent_name,
                    source_label=mod.source_label,
                    stat=mod.stat,
                    value=mod.value,
                ),
            )
    return applied


def _augment_for_member(
    member_id: str,
    snap: BuildSnapshot,
    all_members: list[TeamMember],
) -> BuildSnapshot:
    """Return a snapshot augmented with target=team mods from all other members."""
    other_members = [m for m in all_members if m.build_id != member_id]
    team_mods = _collect_team_modifiers(other_members)
    return replace(snap, modifiers=[*snap.modifiers, *team_mods])


def calculate_team_combo(
    *,
    dps_member: TeamMember,
    support_members: list[TeamMember],
    dps_snapshot: BuildSnapshot,
    enemy: Any,
    combo_steps: list[ComboStep],
    conditions: ActiveConditions,
    crit_mode: CritMode = CritMode.EXPECTED,  # noqa: ARG001 — stateful path always uses EXPECTED
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,  # noqa: ARG001 — stateful path uses enemy model's default
    member_snapshots: dict[str, BuildSnapshot] | None = None,
    fluxed_overrides: dict[str, str] | None = None,
) -> TeamCalculationResult:
    """Evaluate a combo under team context.

    Phase 5A (``member_snapshots=None``):
        Only the DPS's damage is computed with team-target buffs from supports
        folded into the DPS snapshot.  ``by_agent`` is empty.

    Phase 5B (``member_snapshots`` provided):
        Each key maps a build_id (matching ``ComboStep.agent_id`` values) to
        that member's raw snapshot.  Each snapshot is augmented with
        target=team mods from all *other* members, then passed to the
        simulator.  ``by_agent`` lists each member's damage contribution.
        One shared enemy/stun state threads through the full step sequence.
    """
    all_members = [dps_member, *support_members]
    auto = _derive_auto_conditions(dps_member, support_members)
    merged_conditions = _merge_conditions(conditions, auto)
    applied = _attribute_team_buffs(support_members, all_members, conditions)

    if member_snapshots is not None:
        member_by_id = {m.build_id: m for m in all_members}

        augmented_snaps = {
            mid: _augment_for_member(mid, snap, all_members)
            for mid, snap in member_snapshots.items()
        }

        sim_result = simulate_combo_steps(
            build=dps_snapshot,
            combo_steps=combo_steps,
            enemy=enemy,
            member_snapshots=augmented_snaps,
            base_conditions=[c.value for c in merged_conditions.active],
            is_stunned=is_stunned,
            fluxed_overrides=fluxed_overrides,
        )
        # Use the primary member's augmented snapshot for stat display (crit_dmg, etc.).
        primary_snap = augmented_snaps.get(dps_member.build_id, dps_snapshot)
        combo_result = sim_result_to_combo_evaluation(
            sim_result,
            combo_steps,
            primary_snap,
            merged_conditions,
        )

        grand_total = sum(sim_result.per_agent_attribution.values())
        by_agent: list[AgentContribution] = []
        for build_id, dmg in sim_result.per_agent_attribution.items():
            member = member_by_id.get(build_id)
            if member is None:
                continue
            pct = (dmg / grand_total * 100) if grand_total else 0.0
            by_agent.append(
                AgentContribution(
                    agent_name=member.agent_name,
                    build_id=build_id,
                    damage=float(dmg),
                    pct=pct,
                )
            )

        return TeamCalculationResult(
            combo_result=combo_result,
            dps_build_id=dps_member.build_id,
            dps_agent_name=dps_member.agent_name,
            auto_conditions=sorted(c.value for c in auto),
            applied_team_buffs=applied,
            by_agent=by_agent,
            buff_roster=_build_buff_roster(primary_snap, merged_conditions),
        )

    # Phase 5A: DPS-only path (original behaviour).
    team_mods = _collect_team_modifiers(support_members)
    augmented = replace(
        dps_snapshot,
        modifiers=[*dps_snapshot.modifiers, *team_mods],
    )

    # Route through the stateful engine (Task 3 / Phase 4).
    # crit_mode: stateful engine always uses CritMode.EXPECTED; crit_mode param ignored.
    # stack_counts: not forwarded (known limitation, same class as Tasks 2-3).
    sim_result = simulate_combo_steps(
        build=augmented,
        combo_steps=combo_steps,
        enemy=enemy,
        base_conditions=[c.value for c in merged_conditions.active],
        is_stunned=is_stunned,
        fluxed_overrides=fluxed_overrides,
    )
    combo_result = sim_result_to_combo_evaluation(
        sim_result,
        combo_steps,
        augmented,
        merged_conditions,
    )

    return TeamCalculationResult(
        combo_result=combo_result,
        dps_build_id=dps_member.build_id,
        dps_agent_name=dps_member.agent_name,
        auto_conditions=sorted(c.value for c in auto),
        applied_team_buffs=applied,
        by_agent=[],
        buff_roster=_build_buff_roster(augmented, merged_conditions),
    )
