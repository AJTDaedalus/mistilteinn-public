"""Unit tests for the team calculator (Phase 5A — DPS-only).

The team calculator orchestrates over combo_evaluator: it folds team-target
modifiers from support builds into the DPS snapshot, auto-derives
team-composition conditions, and evaluates the DPS's combo with that
augmented context.

Phase 5A scope:
  - Only the DPS build's damage is computed.
  - Supports contribute via target=team modifiers + auto-conditions only.
  - No off-field DPS contribution from supports yet.
  - No field-time weighting yet.
A future Phase 5B will add full multi-DPS evaluation with field-time
allocation; the per-step result schema already supports per-source
attribution so the optimizer can sum contributions.
"""

from __future__ import annotations

from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.team_calculator import (
    TeamMember,
    calculate_team_combo,
)


def _mod(
    stat: str = "atk_pct",
    value: int = 1000,
    *,
    target: ModifierTarget = ModifierTarget.SELF,
    conditions: tuple[Condition, ...] = (Condition.ALWAYS,),
    source_label: str = "test",
) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.CORE_SKILL,
        source_label=source_label,
        target=target,
        conditions=conditions,
        scopes=(AttackScope.ALL,),
        max_stacks=1,
    )


def _member(
    *,
    build_id: str = "b-1",
    agent_name: str = "A",
    element: str = "ice",
    specialty: str = "attack",
    faction_id: int = 0,
    modifiers: list[Modifier] | None = None,
) -> TeamMember:
    return TeamMember(
        build_id=build_id,
        agent_name=agent_name,
        agent_element=element,
        agent_specialty=specialty,
        agent_faction_id=faction_id,
        modifiers=modifiers or [],
    )


def _snap(*, modifiers: list[Modifier] | None = None) -> BuildSnapshot:
    return BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element="ice",
        modifiers=modifiers or [],
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
    )


class TestTeamBuffPropagation:
    def test_team_target_modifier_from_support_buffs_dps(self):
        """Support's target=team modifier should boost DPS damage."""
        dps = _member(build_id="dps-1", agent_name="DPS")
        sup_buff = _mod(
            "atk_pct", 5000, target=ModifierTarget.TEAM, source_label="Support ATK Buff"
        )
        sup = _member(build_id="sup-1", agent_name="Sup", modifiers=[sup_buff])

        with_team = calculate_team_combo(
            dps_member=dps,
            support_members=[sup],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        without_team = calculate_team_combo(
            dps_member=dps,
            support_members=[],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert with_team.combo_result.total_damage > without_team.combo_result.total_damage

    def test_self_target_modifier_from_support_does_not_leak(self):
        """Support's target=self modifier must not affect DPS."""
        dps = _member(build_id="dps-1")
        sup_self = _mod(
            "atk_pct", 5000, target=ModifierTarget.SELF, source_label="Support Self Buff"
        )
        sup = _member(build_id="sup-1", modifiers=[sup_self])

        with_sup = calculate_team_combo(
            dps_member=dps,
            support_members=[sup],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        baseline = calculate_team_combo(
            dps_member=dps,
            support_members=[],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert with_sup.combo_result.total_damage == baseline.combo_result.total_damage


class TestAutoConditions:
    def test_stun_specialty_activates_stun_in_team(self):
        """A team containing a Stun-specialty agent activates STUN_IN_TEAM."""
        dps = _member(build_id="dps", specialty="attack")
        stunner = _member(build_id="stun", specialty="stun")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[stunner],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "stun_in_team" in result.auto_conditions

    def test_support_specialty_activates_support_in_team(self):
        dps = _member(build_id="dps", specialty="attack")
        supporter = _member(build_id="sup", specialty="support")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[supporter],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "support_in_team" in result.auto_conditions

    def test_anomaly_specialty_activates_anomaly_in_team(self):
        dps = _member(build_id="dps", specialty="attack")
        anom = _member(build_id="anom", specialty="anomaly")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[anom],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "anomaly_in_team" in result.auto_conditions

    def test_same_element_two_or_more_activates_condition(self):
        dps = _member(build_id="dps", element="ice")
        ally = _member(build_id="ally", element="ice")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[ally],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_element_in_team" in result.auto_conditions

    def test_different_elements_no_same_element_condition(self):
        dps = _member(build_id="dps", element="ice")
        ally = _member(build_id="ally", element="fire")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[ally],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_element_in_team" not in result.auto_conditions

    def test_same_faction_two_or_more_activates_condition(self):
        dps = _member(build_id="dps", faction_id=5)
        ally = _member(build_id="ally", faction_id=5)
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[ally],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_faction_in_team" in result.auto_conditions

    def test_attack_specialty_activates_attack_in_team(self):
        dps = _member(build_id="dps", specialty="attack")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "attack_in_team" in result.auto_conditions

    def test_defense_specialty_activates_defense_in_team(self):
        dps = _member(build_id="dps", specialty="attack")
        defender = _member(build_id="def", specialty="defense")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[defender],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "defense_in_team" in result.auto_conditions

    def test_same_attribute_or_stun_fires_on_shared_element(self):
        """Previously unwired (D-KV14/C5): a shared element alone must fire it."""
        dps = _member(build_id="dps", element="ice", specialty="attack")
        ally = _member(build_id="ally", element="ice", specialty="attack")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[ally],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_attribute_or_stun_in_team" in result.auto_conditions

    def test_same_attribute_or_stun_fires_on_stun_specialty_alone(self):
        dps = _member(build_id="dps", element="ice", specialty="attack")
        stunner = _member(build_id="stun", element="fire", specialty="stun")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[stunner],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_attribute_or_stun_in_team" in result.auto_conditions

    def test_same_attribute_or_stun_absent_without_either(self):
        dps = _member(build_id="dps", element="ice", specialty="attack")
        other = _member(build_id="other", element="fire", specialty="anomaly")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[other],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_attribute_or_stun_in_team" not in result.auto_conditions

    def test_same_specialty_or_faction_fires_on_shared_specialty(self):
        """Previously unwired (D-KV14/C5): shared specialty alone must fire it."""
        dps = _member(build_id="dps", specialty="attack", faction_id=0)
        ally = _member(build_id="ally", specialty="attack", faction_id=99)
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[ally],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_specialty_or_faction_in_team" in result.auto_conditions

    def test_same_specialty_or_faction_fires_on_shared_faction(self):
        dps = _member(build_id="dps", specialty="attack", faction_id=7)
        ally = _member(build_id="ally", specialty="stun", faction_id=7)
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[ally],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_specialty_or_faction_in_team" in result.auto_conditions

    def test_same_attribute_or_faction_fires_on_shared_element(self):
        """New condition (D-KV14/C5): ZO's most common additional-ability gate."""
        dps = _member(build_id="dps", element="electric", faction_id=0)
        ally = _member(build_id="ally", element="electric", faction_id=99)
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[ally],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_attribute_or_faction_in_team" in result.auto_conditions

    def test_same_attribute_or_faction_fires_on_shared_faction(self):
        dps = _member(build_id="dps", element="ice", faction_id=7)
        ally = _member(build_id="ally", element="fire", faction_id=7)
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[ally],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_attribute_or_faction_in_team" in result.auto_conditions

    def test_same_attribute_or_faction_absent_without_either(self):
        dps = _member(build_id="dps", element="ice", faction_id=1)
        ally = _member(build_id="ally", element="fire", faction_id=2)
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[ally],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_attribute_or_faction_in_team" not in result.auto_conditions

    def test_same_attribute_or_faction_or_stun_fires_on_shared_element(self):
        """D-KV23 (Task 17 Batch 6, Ellen): third union axis, Stun."""
        dps = _member(build_id="dps", element="ice", specialty="attack", faction_id=0)
        ally = _member(build_id="ally", element="ice", specialty="attack", faction_id=99)
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[ally],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_attribute_or_faction_or_stun_in_team" in result.auto_conditions

    def test_same_attribute_or_faction_or_stun_fires_on_stun_teammate(self):
        dps = _member(build_id="dps", element="ice", specialty="attack", faction_id=0)
        stunner = _member(build_id="stun", element="fire", specialty="stun", faction_id=1)
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[stunner],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_attribute_or_faction_or_stun_in_team" in result.auto_conditions

    def test_same_attribute_or_faction_or_stun_absent_without_any(self):
        dps = _member(build_id="dps", element="ice", specialty="attack", faction_id=1)
        ally = _member(build_id="ally", element="fire", specialty="anomaly", faction_id=2)
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[ally],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_attribute_or_faction_or_stun_in_team" not in result.auto_conditions

    def test_owner_relative_aab_team_owner_fires_other_does_not(self):
        """A/A/B team (D-KV14/C5 acceptance): A's owner-relative SAME_* fires
        because the *other* A shares its element; B's does not, since no
        other member shares B's. Same physical team, DPS role swapped."""
        a1 = _member(build_id="a1", element="ice")
        a2 = _member(build_id="a2", element="ice")
        b = _member(build_id="b", element="fire")

        a_view = calculate_team_combo(
            dps_member=a1,
            support_members=[a2, b],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        b_view = calculate_team_combo(
            dps_member=b,
            support_members=[a1, a2],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_element_in_team" in a_view.auto_conditions
        assert "same_element_in_team" not in b_view.auto_conditions

    def test_auto_condition_unlocks_buff_on_dps(self):
        """A DPS modifier conditional on STUN_IN_TEAM should activate
        when a stunner joins."""
        cond_buff = _mod(
            "atk_pct", 4000, conditions=(Condition.STUN_IN_TEAM,), source_label="cond"
        )
        dps = _member(build_id="dps", specialty="attack")
        stunner = _member(build_id="stun", specialty="stun")

        with_stunner = calculate_team_combo(
            dps_member=dps,
            support_members=[stunner],
            dps_snapshot=_snap(modifiers=[cond_buff]),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        solo = calculate_team_combo(
            dps_member=dps,
            support_members=[],
            dps_snapshot=_snap(modifiers=[cond_buff]),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert with_stunner.combo_result.total_damage > solo.combo_result.total_damage


class TestAttribution:
    def test_applied_team_buffs_lists_active_support_modifiers(self):
        sup_buff = _mod("atk_pct", 5000, target=ModifierTarget.TEAM, source_label="ATK Boost")
        dps = _member(build_id="dps", agent_name="DPS")
        sup = _member(build_id="sup", agent_name="Lucy", modifiers=[sup_buff])
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[sup],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert len(result.applied_team_buffs) == 1
        b = result.applied_team_buffs[0]
        assert b.source_build_id == "sup"
        assert b.source_agent_name == "Lucy"
        assert b.source_label == "ATK Boost"
        assert b.stat == "atk_pct"
        assert b.value == 5000

    def test_inactive_conditional_buff_not_listed(self):
        """A conditional team buff whose condition isn't met should not appear."""
        cond_buff = _mod(
            "atk_pct",
            5000,
            target=ModifierTarget.TEAM,
            conditions=(Condition.ENEMY_STUNNED,),
            source_label="On-Stun Buff",
        )
        dps = _member(build_id="dps")
        sup = _member(build_id="sup", modifiers=[cond_buff])
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[sup],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert result.applied_team_buffs == []

    def test_self_buffs_from_support_not_listed(self):
        """Support's self-target modifiers must not appear in attribution."""
        self_only = _mod("atk_pct", 5000, target=ModifierTarget.SELF, source_label="Self Buff")
        dps = _member(build_id="dps")
        sup = _member(build_id="sup", modifiers=[self_only])
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[sup],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert result.applied_team_buffs == []

    def test_support_gate_uses_own_owner_relative_view_not_dps(self):
        """A support's SAME_ELEMENT gate must fire from *its own* perspective.

        DPS is ice (no element-mate). support1 (fire) and support2 (fire)
        share an element with each other, not with the DPS. support1's own
        team buff, gated on SAME_ELEMENT_IN_TEAM, must still fire (support2
        shares its element) even though the DPS's own owner-relative view
        does not have same_element_in_team active at all.
        """
        gated_buff = _mod(
            "atk_pct",
            5000,
            target=ModifierTarget.TEAM,
            conditions=(Condition.SAME_ELEMENT_IN_TEAM,),
            source_label="Fire Synergy",
        )
        dps = _member(build_id="dps", element="ice")
        sup1 = _member(build_id="sup1", element="fire", modifiers=[gated_buff])
        sup2 = _member(build_id="sup2", element="fire")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[sup1, sup2],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert "same_element_in_team" not in result.auto_conditions
        assert len(result.applied_team_buffs) == 1
        assert result.applied_team_buffs[0].source_build_id == "sup1"


class TestResultMetadata:
    def test_dps_metadata_returned(self):
        dps = _member(build_id="dps-uuid", agent_name="Burnice")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert result.dps_build_id == "dps-uuid"
        assert result.dps_agent_name == "Burnice"

    def test_combo_result_present(self):
        dps = _member(build_id="dps")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert result.combo_result.total_damage > 0
        assert len(result.combo_result.steps) == 1


def _step_for(agent_id: str) -> ComboStep:
    """Build a ComboStep attributed to the given agent."""
    return ComboStep(
        label=f"BA1-{agent_id}",
        attack_id=f"att-{agent_id}",
        attack_name="Basic 1",
        scope=AttackScope.BASIC,
        multiplier=10000,
        element="ice",
        agent_id=agent_id,
    )


class TestPhase5BEvaluation:
    def test_by_agent_sums_to_grand_total(self):
        """With 3 agents, per-agent damage totals sum to the grand total."""
        snap_a = _snap()
        snap_b = _snap()
        snap_c = _snap()

        member_a = _member(build_id="A", agent_name="A")
        member_b = _member(build_id="B", agent_name="B")
        member_c = _member(build_id="C", agent_name="C")

        result = calculate_team_combo(
            dps_member=member_a,
            support_members=[member_b, member_c],
            dps_snapshot=snap_a,
            enemy=_enemy(),
            combo_steps=[_step_for("A"), _step_for("B"), _step_for("C")],
            conditions=ActiveConditions(),
            member_snapshots={"A": snap_a, "B": snap_b, "C": snap_c},
        )

        assert len(result.by_agent) == 3
        total_by_agent = sum(int(c.damage) for c in result.by_agent)
        assert total_by_agent == result.combo_result.total_damage

    def test_team_buff_from_b_boosts_a_step_damage(self):
        """A target=team modifier on B should measurably increase A's step damage."""
        snap_a = _snap()
        snap_b = _snap()

        team_buff = _mod("atk_pct", 5000, target=ModifierTarget.TEAM, source_label="B ATK")
        member_a = _member(build_id="A", agent_name="A")
        member_b_with_buff = _member(build_id="B", agent_name="B", modifiers=[team_buff])
        member_b_no_buff = _member(build_id="B", agent_name="B")

        step_a = _step_for("A")

        result_with_buff = calculate_team_combo(
            dps_member=member_a,
            support_members=[member_b_with_buff],
            dps_snapshot=snap_a,
            enemy=_enemy(),
            combo_steps=[step_a],
            conditions=ActiveConditions(),
            member_snapshots={"A": snap_a, "B": snap_b},
        )
        result_no_buff = calculate_team_combo(
            dps_member=member_a,
            support_members=[member_b_no_buff],
            dps_snapshot=snap_a,
            enemy=_enemy(),
            combo_steps=[step_a],
            conditions=ActiveConditions(),
            member_snapshots={"A": snap_a, "B": snap_b},
        )

        a_dmg_with = next(c.damage for c in result_with_buff.by_agent if c.build_id == "A")
        a_dmg_without = next(c.damage for c in result_no_buff.by_agent if c.build_id == "A")
        assert a_dmg_with > a_dmg_without

    def test_shared_enemy_state_threads_through_owner_switches(self):
        """Stun triggered during agent A's step should boost agent B's subsequent step."""
        from app.services.combo_types import StunTriggerStep

        snap_a = _snap()
        snap_b = _snap()

        member_a = _member(build_id="A", agent_name="A")
        member_b = _member(build_id="B", agent_name="B")

        stun = StunTriggerStep(label="[STUN]")

        result_stunned = calculate_team_combo(
            dps_member=member_a,
            support_members=[member_b],
            dps_snapshot=snap_a,
            enemy=_enemy(),
            combo_steps=[_step_for("A"), stun, _step_for("B")],
            conditions=ActiveConditions(),
            member_snapshots={"A": snap_a, "B": snap_b},
        )
        result_no_stun = calculate_team_combo(
            dps_member=member_a,
            support_members=[member_b],
            dps_snapshot=snap_a,
            enemy=_enemy(),
            combo_steps=[_step_for("A"), _step_for("B")],
            conditions=ActiveConditions(),
            member_snapshots={"A": snap_a, "B": snap_b},
        )

        # Stun multiplier boosts all in-stun hits, so stunned total > no-stun total.
        assert result_stunned.combo_result.total_damage > result_no_stun.combo_result.total_damage

    def test_phase5a_path_unchanged_when_no_member_snapshots(self):
        """Omitting member_snapshots preserves Phase 5A behavior: by_agent is empty."""
        dps = _member(build_id="dps-1", agent_name="DPS")
        result = calculate_team_combo(
            dps_member=dps,
            support_members=[],
            dps_snapshot=_snap(),
            enemy=_enemy(),
            combo_steps=[_step()],
            conditions=ActiveConditions(),
        )
        assert result.by_agent == []
        assert result.combo_result.total_damage > 0
