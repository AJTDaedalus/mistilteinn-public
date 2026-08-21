"""Task 17 — New Condition members for Remielle (DESIGN_remielle.md §6).

Covers: ANOMALY_COUNT_2/3_IN_TEAM derivation (presence family, team-global,
include-owner), EQUIPPER_IS_LUMIFLUX (mirrors its five siblings), and that a
solo-Anomaly squad (just Remielle) does not activate the owner-relative AA
gate (SAME_SPECIALTY_OR_FACTION_IN_TEAM).
"""

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.lumiflux import LumifluxSpec
from app.services.modifiers import Condition, Modifier, ModifierSource, ModifierTarget
from app.services.snapshot_builder import resolve_equipper_conditions
from app.services.team_calculator import TeamMember, _derive_auto_conditions


def _member(name, specialty, element, faction_id=1, build_id=None):
    return TeamMember(
        build_id=build_id or name,
        agent_name=name,
        agent_element=element,
        agent_specialty=specialty,
        agent_faction_id=faction_id,
    )


class TestAnomalyCountDerivation:
    def test_three_anomaly_squad_fires_count_2_and_count_3(self):
        remielle = _member("Remielle", "anomaly", "lumiflux")
        a2 = _member("A2", "anomaly", "fire")
        a3 = _member("A3", "anomaly", "ice")
        active = _derive_auto_conditions(remielle, [a2, a3])
        assert Condition.ANOMALY_COUNT_2_IN_TEAM in active
        assert Condition.ANOMALY_COUNT_3_IN_TEAM in active

    def test_two_anomaly_squad_fires_count_2_only(self):
        remielle = _member("Remielle", "anomaly", "lumiflux")
        a2 = _member("A2", "anomaly", "fire")
        support = _member("Support", "support", "ice")
        active = _derive_auto_conditions(remielle, [a2, support])
        assert Condition.ANOMALY_COUNT_2_IN_TEAM in active
        assert Condition.ANOMALY_COUNT_3_IN_TEAM not in active

    def test_solo_anomaly_squad_fires_neither(self):
        """Remielle alone (with two non-Anomaly teammates) -- presence-family
        count is 1, below both thresholds."""
        remielle = _member("Remielle", "anomaly", "lumiflux")
        support = _member("Support", "support", "ice")
        attack = _member("Attack", "attack", "fire")
        active = _derive_auto_conditions(remielle, [support, attack])
        assert Condition.ANOMALY_COUNT_2_IN_TEAM not in active
        assert Condition.ANOMALY_COUNT_3_IN_TEAM not in active

    def test_solo_anomaly_squad_does_not_activate_the_aa_gate(self):
        """Remielle as the only Anomaly (and only shared-faction) agent must
        NOT satisfy her own Additional Ability's owner-relative activation
        gate (SAME_SPECIALTY_OR_FACTION_IN_TEAM) -- that gate explicitly
        excludes the owner (D-KV14), unlike the presence-family counts above."""
        remielle = _member("Remielle", "anomaly", "lumiflux", faction_id=99)
        support = _member("Support", "support", "ice", faction_id=1)
        attack = _member("Attack", "attack", "fire", faction_id=2)
        active = _derive_auto_conditions(remielle, [support, attack])
        assert Condition.SAME_SPECIALTY_OR_FACTION_IN_TEAM not in active

    def test_count_conditions_are_team_global_not_owner_relative(self):
        """Unlike SAME_SPECIALTY_OR_FACTION_IN_TEAM, the count conditions
        include the owner's own specialty in the tally -- a non-Anomaly
        owner with 2 Anomaly teammates still fires COUNT_2."""
        dps = _member("Dps", "attack", "physical")
        a1 = _member("A1", "anomaly", "fire")
        a2 = _member("A2", "anomaly", "ice")
        active = _derive_auto_conditions(dps, [a1, a2])
        assert Condition.ANOMALY_COUNT_2_IN_TEAM in active


class TestEquipperIsLumiflux:
    def test_resolves_for_a_lumiflux_support(self):
        mod = Modifier(
            stat="dmg_bonus",
            value=1000,
            source=ModifierSource.CORE_SKILL,
            source_label="test",
            target=ModifierTarget.TEAM,
            conditions=(Condition.EQUIPPER_IS_LUMIFLUX,),
        )
        resolved = resolve_equipper_conditions(mod, "anomaly", "lumiflux")
        assert resolved is not None
        assert Condition.EQUIPPER_IS_LUMIFLUX not in resolved.conditions

    def test_does_not_resolve_for_a_non_lumiflux_support(self):
        mod = Modifier(
            stat="dmg_bonus",
            value=1000,
            source=ModifierSource.CORE_SKILL,
            source_label="test",
            target=ModifierTarget.TEAM,
            conditions=(Condition.EQUIPPER_IS_LUMIFLUX,),
        )
        resolved = resolve_equipper_conditions(mod, "anomaly", "fire")
        assert resolved is None

    def test_behaves_identically_to_its_siblings(self):
        """Same resolve/drop shape as EQUIPPER_IS_FIRE for a matching vs.
        non-matching element -- no special-cased behavior for Lumiflux."""
        fire_mod = Modifier(
            stat="dmg_bonus",
            value=1000,
            source=ModifierSource.CORE_SKILL,
            source_label="test",
            target=ModifierTarget.TEAM,
            conditions=(Condition.EQUIPPER_IS_FIRE,),
        )
        lumiflux_mod = Modifier(
            stat="dmg_bonus",
            value=1000,
            source=ModifierSource.CORE_SKILL,
            source_label="test",
            target=ModifierTarget.TEAM,
            conditions=(Condition.EQUIPPER_IS_LUMIFLUX,),
        )
        assert resolve_equipper_conditions(fire_mod, "anomaly", "fire") is not None
        assert resolve_equipper_conditions(fire_mod, "anomaly", "lumiflux") is None
        assert resolve_equipper_conditions(lumiflux_mod, "anomaly", "lumiflux") is not None
        assert resolve_equipper_conditions(lumiflux_mod, "anomaly", "fire") is None


def _pf_spec():
    return LumifluxSpec(
        point_cap=4,
        voidflare_cap=3,
        refringe_ap_ratio_bp=2,
        refringe_flat_bonuses={},
        luminize_multipliers={},
        luminize_ap_bonus_bp=10,
        phase_flow_tick_s=5.0,
        phase_flow_duration_s=40.0,
        flight_attack_points=(0, 1, 2),
        flight_attack_mv_bp=(8130, 20320, 16250),
        flight_attack_daze_bp=(27500, 37820, 37820),
    )


def _pf_move_spec(buildup=0, duration_s=1.0, hits=1, element=None):
    class _MoveSpec:
        def __init__(self):
            self.buildup = buildup
            self.duration_s = duration_s
            self.hits = hits
            self.element = element
            self.scope = "basic"

    return _MoveSpec()


class _Attack:
    def __init__(self, element, damage_base=10_000):
        self.id = "atk"
        self.name = "hit"
        self.element = element
        self.damage_base = damage_base
        self.damage_growth = 0
        self.anomaly_buildup = 0
        self.skill_key = "Basic"
        self.hit_index = 0


class _AgentMoves:
    def __init__(self, moves):
        self.moves = moves


class TestSimStateConditions:
    def test_phase_flow_active_is_team_wide_while_her_window_is_open(self):
        """A TEAM-target modifier gated on PHASE_FLOW_ACTIVE must buff a
        teammate's damage while Remielle's own window is open, and not
        once it's closed -- true for whoever is acting, not just her."""
        pf_buff = Modifier(
            stat="dmg_bonus",
            value=3000,
            source=ModifierSource.CORE_SKILL,
            source_label="Phase Flow squad DMG",
            target=ModifierTarget.TEAM,
            conditions=(Condition.PHASE_FLOW_ACTIVE,),
        )
        remielle = BuildSnapshot(
            agent_name="Remielle",
            agent_element="lumiflux",
            agent_level=60,
            agent_base_atk=1000,
            modifiers=[pf_buff],
        )
        dps = BuildSnapshot(
            agent_name="DpsGuy", agent_element="fire", agent_level=60, agent_base_atk=1000
        )
        enemy = EnemyProfile(name="Target", level=60, defense=50, fire_res=0)
        moves_db = {"dpsguy": _AgentMoves({"hit": _pf_move_spec(0, 1.0, 1, "fire")})}
        attacks = [_Attack("fire")]

        inside_window = simulate(
            {"remielle": remielle, "dps": dps},
            [SimulatedAttackStep("dps", "hit", attacks)],
            enemy,
            moves_db,
            lumiflux_specs={"remielle": _pf_spec()},
            phase_flow_windows={"remielle": [(0.0, 10.0)]},
        )
        outside_window = simulate(
            {"remielle": remielle, "dps": dps},
            [SimulatedAttackStep("dps", "hit", attacks)],
            enemy,
            moves_db,
            lumiflux_specs={"remielle": _pf_spec()},
            phase_flow_windows={"remielle": [(20.0, 30.0)]},
        )

        hits_in = [e for e in inside_window.events if e.kind == "hit"]
        hits_out = [e for e in outside_window.events if e.kind == "hit"]
        assert hits_in[0].damage > hits_out[0].damage
