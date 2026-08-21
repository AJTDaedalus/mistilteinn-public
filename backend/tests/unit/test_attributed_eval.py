"""Unit tests for the shared attributed-evaluation service (Task B1, DESIGN §1.3).

``evaluate_combo_attributed`` is the single path both the calculate endpoint
(B2) and the keystone endpoint (B3) will route through, so they cannot
diverge. These tests only cover B1's own scope: parity with
``calculate_team_combo`` when no override is given, and that a disc override
actually changes the resolved stats before damage is computed.
"""

from __future__ import annotations

from app.services.attributed_eval import evaluate_combo_attributed
from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep
from app.services.modifiers import ActiveConditions, AttackScope
from app.services.team_calculator import TeamMember, calculate_team_combo


def _dps() -> TeamMember:
    return TeamMember(
        build_id="dps-1",
        agent_name="DPS",
        agent_element="ice",
        agent_specialty="attack",
        agent_faction_id=0,
    )


def _snap(*, disc_stats: list[dict] | None = None) -> BuildSnapshot:
    return BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element="ice",
        disc_stats=disc_stats or [],
    )


def _enemy() -> EnemySnapshot:
    return EnemySnapshot(level=60, base_def=50, element_res=0)


def _step() -> ComboStep:
    return ComboStep(
        label="BA1",
        attack_id="att-1",
        attack_name="Basic 1",
        scope=AttackScope.BASIC,
        multiplier=10000,
        element="ice",
        agent_id="dps-1",
    )


def _disc_atk_main(value: int) -> dict:
    return {"main_stat_type": "atk", "main_stat_value": value, "substats": []}


class TestParityWithCalculateTeamCombo:
    def test_no_overrides_matches_calculate_team_combo_exactly(self):
        dps = _dps()
        snap = _snap()

        attributed = evaluate_combo_attributed(
            dps_member=dps,
            support_members=[],
            member_snapshots={dps.build_id: snap},
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        baseline = calculate_team_combo(
            dps_member=dps,
            support_members=[],
            dps_snapshot=snap,
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
            member_snapshots={dps.build_id: snap},
        )

        assert attributed.combo_result.total_damage == baseline.combo_result.total_damage
        assert attributed.dps_build_id == baseline.dps_build_id
        assert attributed.dps_agent_name == baseline.dps_agent_name
        assert attributed.auto_conditions == baseline.auto_conditions
        assert attributed.by_agent == baseline.by_agent

    def test_result_is_distinct_type_from_team_calculation_result(self):
        """AttributedComboResult is its own type (DESIGN §1.3), not a re-export."""
        dps = _dps()
        result = evaluate_combo_attributed(
            dps_member=dps,
            support_members=[],
            member_snapshots={dps.build_id: _snap()},
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert type(result).__name__ == "AttributedComboResult"


class TestDiscOverrides:
    def test_disc_overrides_none_is_equipped_discs(self):
        dps = _dps()
        equipped = _snap(disc_stats=[_disc_atk_main(500)])

        with_equipped = evaluate_combo_attributed(
            dps_member=dps,
            support_members=[],
            member_snapshots={dps.build_id: equipped},
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
            disc_overrides=None,
        )
        baseline = calculate_team_combo(
            dps_member=dps,
            support_members=[],
            dps_snapshot=equipped,
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
            member_snapshots={dps.build_id: equipped},
        )
        assert with_equipped.combo_result.total_damage == baseline.combo_result.total_damage

    def test_disc_override_changes_damage(self):
        dps = _dps()
        equipped = _snap(disc_stats=[_disc_atk_main(500)])

        equipped_result = evaluate_combo_attributed(
            dps_member=dps,
            support_members=[],
            member_snapshots={dps.build_id: equipped},
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        overridden_result = evaluate_combo_attributed(
            dps_member=dps,
            support_members=[],
            member_snapshots={dps.build_id: equipped},
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
            disc_overrides={dps.build_id: [_disc_atk_main(5000)]},
        )
        assert (
            overridden_result.combo_result.total_damage > equipped_result.combo_result.total_damage
        )

    def test_disc_override_does_not_mutate_input_snapshot(self):
        """The override must not leak into the caller's snapshot dict."""
        dps = _dps()
        equipped = _snap(disc_stats=[_disc_atk_main(500)])
        snapshots = {dps.build_id: equipped}

        evaluate_combo_attributed(
            dps_member=dps,
            support_members=[],
            member_snapshots=snapshots,
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
            disc_overrides={dps.build_id: [_disc_atk_main(9999)]},
        )
        assert snapshots[dps.build_id].disc_stats == [_disc_atk_main(500)]

    def test_unknown_override_build_id_is_ignored(self):
        """An override for a build_id not present in member_snapshots is a no-op."""
        dps = _dps()
        equipped = _snap(disc_stats=[_disc_atk_main(500)])

        result = evaluate_combo_attributed(
            dps_member=dps,
            support_members=[],
            member_snapshots={dps.build_id: equipped},
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
            disc_overrides={"nonexistent-build": [_disc_atk_main(9999)]},
        )
        baseline = evaluate_combo_attributed(
            dps_member=dps,
            support_members=[],
            member_snapshots={dps.build_id: equipped},
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert result.combo_result.total_damage == baseline.combo_result.total_damage


class TestAttributionThreading:
    """Task B2: attribution actually reaches ComboStepResult (LOG_explainability
    2026-07-03 flagged that ``sim_result_to_combo_evaluation`` dropped it
    entirely -- ``TimelineEvent.attribution`` closes that gap)."""

    def test_step_attribution_is_populated(self):
        dps = _dps()
        result = evaluate_combo_attributed(
            dps_member=dps,
            support_members=[],
            member_snapshots={dps.build_id: _snap()},
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        step = result.combo_result.steps[0]
        assert step.attribution is not None
        assert step.attribution.crit_rate.total >= 0
        assert step.attribution.zone_formulas["boost"].result_bp == step.damage.boost_mult
        assert step.attribution.zone_formulas["def"].result_bp == step.damage.def_mult

    def test_step_formula_intermediates_are_populated(self):
        dps = _dps()
        result = evaluate_combo_attributed(
            dps_member=dps,
            support_members=[],
            member_snapshots={dps.build_id: _snap()},
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        step = result.combo_result.steps[0]
        assert step.damage.level_factor_val > 0
        assert step.damage.effective_enemy_def >= 0


class TestBuffRoster:
    def test_buff_roster_present_on_result(self):
        dps = _dps()
        result = evaluate_combo_attributed(
            dps_member=dps,
            support_members=[],
            member_snapshots={dps.build_id: _snap()},
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert isinstance(result.buff_roster, list)
