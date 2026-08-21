"""Shared attributed-evaluation service (DESIGN_explainability.md §1.3).

The calculate endpoint (Task B2) and the keystone endpoint (Task B3) both
need to run a team combo with full per-step attribution; the keystone
additionally needs to swap in a candidate six-disc set before stats are
resolved. Rather than two evaluation paths that could drift apart, both
route through ``evaluate_combo_attributed`` -- it always runs
``calculate_team_combo`` (which already always computes ``StepAttribution``
per step), optionally substituting ``disc_overrides`` onto the relevant
member snapshot(s) first.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from app.services.damage_calculator import CritMode
from app.services.team_calculator import (
    AgentContribution,
    AppliedTeamBuff,
    TeamMember,
    calculate_team_combo,
)

if TYPE_CHECKING:
    from app.services.buff_roster import BuffRosterEntry
    from app.services.build_damage_service import BuildSnapshot
    from app.services.combo_types import ComboEvaluationResult, ComboStep
    from app.services.modifiers import ActiveConditions


@dataclass(frozen=True)
class AttributedComboResult:
    """Result of ``evaluate_combo_attributed`` -- always fully attributed.

    Same shape as ``TeamCalculationResult``; kept as a distinct type so
    callers can rely on ``combo_result.steps[*].attribution`` always being
    populated, which is only guaranteed through this entry point.
    """

    combo_result: ComboEvaluationResult
    dps_build_id: str
    dps_agent_name: str
    auto_conditions: list[str]
    applied_team_buffs: list[AppliedTeamBuff]
    by_agent: list[AgentContribution] = field(default_factory=list)
    buff_roster: list[BuffRosterEntry] = field(default_factory=list)


def _apply_disc_overrides(
    member_snapshots: dict[str, BuildSnapshot],
    disc_overrides: dict[str, list[dict]] | None,
) -> dict[str, BuildSnapshot]:
    """Return snapshots with overridden builds' ``disc_stats`` swapped in.

    Unknown build_ids in ``disc_overrides`` (not present in
    ``member_snapshots``) are ignored -- there is no snapshot to override.
    """
    if not disc_overrides:
        return member_snapshots
    overridden = dict(member_snapshots)
    for build_id, disc_stats in disc_overrides.items():
        if build_id in overridden:
            overridden[build_id] = replace(overridden[build_id], disc_stats=disc_stats)
    return overridden


def evaluate_combo_attributed(
    *,
    dps_member: TeamMember,
    support_members: list[TeamMember],
    member_snapshots: dict[str, BuildSnapshot],
    enemy: Any,
    combo_steps: list[ComboStep],
    conditions: ActiveConditions,
    crit_mode: CritMode = CritMode.EXPECTED,
    is_stunned: bool = False,
    stun_dmg_mult: int = 15000,
    disc_overrides: dict[str, list[dict]] | None = None,
) -> AttributedComboResult:
    """Evaluate a team combo with full attribution, optionally on overridden discs.

    ``disc_overrides`` maps build_id -> raw disc-stat dicts (the same shape
    ``BuildSnapshot.disc_stats`` already carries); when present for a build,
    those discs replace the equipped set on that build's snapshot *before*
    stat resolution (``accumulate_disc_stats`` runs downstream inside the
    normal calc path, unchanged). ``None`` reproduces today's equipped-disc
    calculate path exactly.
    """
    snapshots = _apply_disc_overrides(member_snapshots, disc_overrides)

    team_result = calculate_team_combo(
        dps_member=dps_member,
        support_members=support_members,
        dps_snapshot=snapshots[dps_member.build_id],
        enemy=enemy,
        combo_steps=combo_steps,
        conditions=conditions,
        crit_mode=crit_mode,
        is_stunned=is_stunned,
        stun_dmg_mult=stun_dmg_mult,
        member_snapshots=snapshots,
    )

    return AttributedComboResult(
        combo_result=team_result.combo_result,
        dps_build_id=team_result.dps_build_id,
        dps_agent_name=team_result.dps_agent_name,
        auto_conditions=team_result.auto_conditions,
        applied_team_buffs=team_result.applied_team_buffs,
        by_agent=team_result.by_agent,
        buff_roster=team_result.buff_roster,
    )
