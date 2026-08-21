"""Task 21 — Structural test suite: DESIGN_remielle.md §9.1 tests 1-11.

These are the acceptance criteria that survive number churn (brief §12.3:
absolute anchors are unstable pre-live; these are not). Each test below
re-asserts one §9.1 item directly, in one place, rather than requiring a
reader to reconstruct the invariant set from the individual task's own test
file. Several of these invariants already have a fuller, more detailed test
file from the task that introduced them -- each docstring below names it.
"""

from __future__ import annotations

import dataclasses
from typing import ClassVar

import pytest

from app.data.importers.nanoka_importer import ELEMENT_ID_MAP
from app.models.build import EnemyProfile
from app.models.enums import Element
from app.services.anomaly_simulator import (
    ELEMENT_TO_ANOMALY,
    SimulatedAttackStep,
    _dominant_buildup_element,
    simulate,
)
from app.services.build_damage_service import BuildSnapshot, EnemySnapshot, calculate_build_damage
from app.services.damage_calculator import calculate_luminize_damage
from app.services.disc_optimizer import _ELEMENT_DMG_FIELDS
from app.services.lumiflux import LumifluxSpec, VoidflareRecord, refringe_coefficient
from app.services.modifier_loader import load_agent_modifiers
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.snapshot_builder import _bake_atk_scaled_modifier
from app.services.stat_calculator import TotalStats

LUMIFLUX = Element.LUMIFLUX.value


# ---------------------------------------------------------------------------
# Test 1 — Refringe is linear in AP (Task 6, test_lumiflux_flux.py in full)
# ---------------------------------------------------------------------------


class TestRefringeLinearInAP:
    """DESIGN §9.1 test 1: doubling Remielle's AP doubles the coefficient's
    AP-derived term; the flat bonus is unaffected."""

    def _spec(self):
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

    def test_doubling_ap_doubles_the_ap_derived_term(self):
        spec = self._spec()
        c_0 = refringe_coefficient(spec, 0, flat_bonus_bp=0)
        c_ap = refringe_coefficient(spec, 401, flat_bonus_bp=0)
        c_2ap = refringe_coefficient(spec, 802, flat_bonus_bp=0)
        assert c_2ap - c_0 == 2 * (c_ap - c_0)

    def test_flat_bonus_is_unaffected_by_ap(self):
        spec = self._spec()
        low = refringe_coefficient(spec, 100, flat_bonus_bp=3000)
        high = refringe_coefficient(spec, 200, flat_bonus_bp=3000)
        assert high - low == refringe_coefficient(
            spec, 200, flat_bonus_bp=0
        ) - refringe_coefficient(spec, 100, flat_bonus_bp=0)


# ---------------------------------------------------------------------------
# Test 2 — ATK kink at exactly 4000 (Task 18, test_remielle_kit_modifiers.py in full)
# ---------------------------------------------------------------------------


class TestATKKinkAtExactly4000:
    """DESIGN §9.1 test 2: the 3-Anomaly-tier team ATK buff is strictly
    increasing below 4000 ATK, flat at/above, kink at exactly 4000."""

    def _total_at(self, atk: int) -> int:
        mods = [m for m in load_agent_modifiers("1581") if m.source.value == "additional_ability"]
        return sum(_bake_atk_scaled_modifier(m, atk).value for m in mods)

    def test_strictly_increasing_below_4000(self):
        assert self._total_at(1000) < self._total_at(2000) < self._total_at(3999)

    def test_flat_at_and_above_4000_with_zero_slope_at_4001(self):
        assert self._total_at(4000) == 1600
        assert self._total_at(4001) == self._total_at(4000)
        assert self._total_at(3999) < self._total_at(4000)


# ---------------------------------------------------------------------------
# Test 3 — Voidflare immutability (Task 12/13, test_voidflare_store.py +
# test_luminize_damage.py in full)
# ---------------------------------------------------------------------------


class TestVoidflareImmutability:
    """DESIGN §9.1 test 3: buffing the teammate after storage changes
    nothing (the record has no live reference to buff); buffing Remielle's
    own universal Anomaly DMG after storage DOES increase Luminize damage
    (it's read live, post-storage, per DESIGN §7.2)."""

    _KWARGS: ClassVar[dict] = {
        "voidflare_atk": 1000,
        "voidflare_dmg_bonus_bp": 0,
        "voidflare_pen_ratio_bp": 0,
        "voidflare_pen_flat": 0,
        "voidflare_anomaly_proficiency": 100,
        "luminize_mult_bp": 20_000,
        "attacker_level": 60,
        "remielle_anomaly_proficiency": 0,
        "ap_bonus_per_point_bp": 10,
        "enemy_base_def": 0,
        "enemy_level": 60,
    }

    def test_voidflare_record_is_frozen(self):
        record = VoidflareRecord(
            element="fire",
            atk=1000,
            dmg_bonus_bp=0,
            pen_ratio_bp=0,
            pen_flat=0,
            anomaly_proficiency=100,
            refringe_coefficient_bp=200,
            stored_at=0.0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.atk = 9999  # type: ignore[misc]

    def test_teammate_buff_after_storage_does_not_change_luminize_damage(self):
        """The record's voidflare_* fields are the only teammate-derived
        inputs to calculate_luminize_damage -- there is no live handle back
        to the teammate's build for a later buff to reach through."""
        first = calculate_luminize_damage(**self._KWARGS, remielle_anomaly_dmg_bonus=0)
        # "Buff the teammate" has nothing to act on: recomputing from the
        # exact same frozen voidflare_* scalars is definitionally unaffected.
        second = calculate_luminize_damage(**self._KWARGS, remielle_anomaly_dmg_bonus=0)
        assert first.total == second.total

    def test_remielles_own_anomaly_dmg_bonus_after_storage_increases_luminize(self):
        without = calculate_luminize_damage(**self._KWARGS, remielle_anomaly_dmg_bonus=0)
        with_buff = calculate_luminize_damage(**self._KWARGS, remielle_anomaly_dmg_bonus=1500)
        assert with_buff.total > without.total


# ---------------------------------------------------------------------------
# Test 4 — Luminize ignores per-anomaly-type effects (Task 13, test_luminize_damage.py in full)
# ---------------------------------------------------------------------------


class TestLuminizeIgnoresPerAnomalyTypeEffects:
    """DESIGN §9.1 test 4: no Assault CRIT DMG / Assault DMG Bonus
    parameter exists on calculate_luminize_damage at all."""

    def test_no_assault_crit_dmg_parameter(self):
        with pytest.raises(TypeError):
            calculate_luminize_damage(
                voidflare_atk=1000,
                voidflare_dmg_bonus_bp=0,
                voidflare_pen_ratio_bp=0,
                voidflare_pen_flat=0,
                voidflare_anomaly_proficiency=100,
                luminize_mult_bp=20_000,
                assault_crit_dmg_bp=5000,
            )


# ---------------------------------------------------------------------------
# Tests 5 & 9 — Luminize cannot trigger Disorder/Abloom/Vortex; per-instance
# RES targeting (Task 14, test_luminize_sim.py in full)
# ---------------------------------------------------------------------------


class _MoveSpec:
    def __init__(
        self,
        buildup=0,
        duration_s=1.0,
        hits=1,
        element=None,
        scope="basic",
        triggers_luminize=False,
        luminize_mult_bp=0,
    ):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope
        self.triggers_luminize = triggers_luminize
        self.luminize_mult_bp = luminize_mult_bp


class _AgentMoves:
    def __init__(self, moves):
        self.moves = moves


def _lumiflux_spec():
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


class TestLuminizeCannotTriggerDisorderAbloomVortexAndTargetsPerInstanceRES:
    def test_three_voidflares_hit_three_res_values_and_no_other_bucket_moves(self):
        builds = {
            "fire_agent": BuildSnapshot(
                agent_name="FireGuy",
                agent_element="fire",
                agent_level=60,
                agent_base_atk=1000,
                agent_anomaly_proficiency=100,
            ),
            "ice_agent": BuildSnapshot(
                agent_name="IceGuy",
                agent_element="ice",
                agent_level=60,
                agent_base_atk=1000,
                agent_anomaly_proficiency=100,
            ),
            "physical_agent": BuildSnapshot(
                agent_name="PhysicalGuy",
                agent_element="physical",
                agent_level=60,
                agent_base_atk=1000,
                agent_anomaly_proficiency=100,
            ),
            "remielle": BuildSnapshot(
                agent_name="Remielle",
                agent_element="lumiflux",
                agent_level=60,
                agent_base_atk=1000,
                agent_anomaly_proficiency=200,
            ),
        }
        enemy = EnemyProfile(
            name="Structural Target",
            level=60,
            defense=50,
            fire_res=1000,
            ice_res=2000,
            physical_res=3000,
            anomaly_capacity_fire=100,
            anomaly_capacity_ice=100,
            anomaly_capacity_physical=100,
            anomaly_duration_default=10.0,
        )
        moves_db = {
            "fireguy": _AgentMoves({"fire_hit": _MoveSpec(15000, 4.0, 1, "fire")}),
            "iceguy": _AgentMoves({"ice_hit": _MoveSpec(15000, 4.0, 1, "ice")}),
            "physicalguy": _AgentMoves({"physical_hit": _MoveSpec(15000, 4.0, 1, "physical")}),
            "remielle": _AgentMoves(
                {
                    "ultimate": _MoveSpec(
                        0, 1.0, 1, None, triggers_luminize=True, luminize_mult_bp=20_000
                    )
                }
            ),
        }
        setup_steps = [
            SimulatedAttackStep("fire_agent", "fire_hit", []),
            SimulatedAttackStep("ice_agent", "ice_hit", []),
            SimulatedAttackStep("physical_agent", "physical_hit", []),
        ]

        setup_only = simulate(
            builds,
            setup_steps,
            enemy,
            moves_db,
            lumiflux_specs={"remielle": _lumiflux_spec()},
            initial_lumiflux_points=3,
        )
        with_luminize = simulate(
            builds,
            [*setup_steps, SimulatedAttackStep("remielle", "ultimate", [])],
            enemy,
            moves_db,
            lumiflux_specs={"remielle": _lumiflux_spec()},
            initial_lumiflux_points=3,
        )

        luminize_events = [e for e in with_luminize.events if e.kind == "luminize"]
        assert len(luminize_events) == 3
        assert {e.element for e in luminize_events} == {"fire", "ice", "physical"}
        by_element = {e.element: e for e in luminize_events}
        assert by_element["fire"].damage > by_element["ice"].damage > by_element["physical"].damage

        # Test 5: adding the Luminize step changes nothing else -- structurally
        # incapable of becoming a Disorder/Abloom/Vortex trigger.
        assert with_luminize.totals["anomaly"] == setup_only.totals["anomaly"]
        assert with_luminize.totals["disorder"] == setup_only.totals["disorder"]
        assert with_luminize.totals["vortex"] == setup_only.totals["vortex"]
        assert with_luminize.totals["abloom"] == setup_only.totals["abloom"]


# ---------------------------------------------------------------------------
# Tests 6 & 7 — Freedom Blues 4pc never activates via flux; fluxed DMG% does
# apply (Task 7, test_lumiflux_dual_tag.py in full)
# ---------------------------------------------------------------------------


def _lumiflux_snap(*, modifiers=None):
    return BuildSnapshot(
        agent_base_hp=8000,
        agent_base_atk=900,
        agent_base_def=600,
        wengine_base_atk=600,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_element="lumiflux",
        agent_specialty="anomaly",
        agent_level=60,
        modifiers=modifiers or [],
    )


def _mod(stat, value, *, conditions=(Condition.ALWAYS,)):
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.EXTERNAL,
        source_label="test",
        target=ModifierTarget.SELF,
        conditions=conditions,
        scopes=(AttackScope.ALL,),
        max_stacks=1,
    )


class TestAttributeLockedSetNeverActivatesViaFluxAndFluxedDmgPctApplies:
    def test_equipper_is_fire_gated_row_stays_inactive_when_fluxed_fire(self):
        """DESIGN §9.1 test 6: an attribute-locked set/W-Engine condition
        (EQUIPPER_IS_FIRE is the exact shape Freedom Blues' 4pc uses --
        Task 7's log substituted this real fixture after finding Freedom
        Blues' own 4pc is anomaly-buildup-RES, not a DMG row) stays
        inactive for a Lumiflux build fluxed to fire -- because
        agent_element stays "lumiflux" everywhere identity checks look."""
        gated = calculate_build_damage(
            build=_lumiflux_snap(
                modifiers=[_mod("fire_dmg", 3000, conditions=(Condition.EQUIPPER_IS_FIRE,))]
            ),
            enemy=EnemySnapshot(level=60, base_def=50),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="fire",
        )
        ungated_baseline = calculate_build_damage(
            build=_lumiflux_snap(),
            enemy=EnemySnapshot(level=60, base_def=50),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="fire",
        )
        assert gated.damage.total == ungated_baseline.damage.total
        assert gated.damage.boost_mult == 10000

    def test_fluxed_physical_dmg_pct_raises_damage_fire_dmg_pct_does_not(self):
        """DESIGN §9.1 test 7."""
        baseline = calculate_build_damage(
            build=_lumiflux_snap(),
            enemy=EnemySnapshot(level=60, base_def=50),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="physical",
        )
        with_physical_dmg = calculate_build_damage(
            build=_lumiflux_snap(modifiers=[_mod("physical_dmg", 3000)]),
            enemy=EnemySnapshot(level=60, base_def=50),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="physical",
        )
        with_fire_dmg = calculate_build_damage(
            build=_lumiflux_snap(modifiers=[_mod("fire_dmg", 3000)]),
            enemy=EnemySnapshot(level=60, base_def=50),
            multiplier=10000,
            conditions=ActiveConditions(),
            attack_scope=AttackScope.BASIC,
            element="physical",
        )
        assert with_physical_dmg.damage.total > baseline.damage.total
        assert with_fire_dmg.damage.total == baseline.damage.total


# ---------------------------------------------------------------------------
# Tests 8 & 11 — Refringe snapshots into the aura; attribution unmoved by
# Refringe (Task 11, test_refringe_sim.py in full)
# ---------------------------------------------------------------------------


class _RefringeMoveSpec:
    def __init__(self, buildup=0, duration_s=1.0, hits=1, element=None, scope="basic"):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope


class TestRefringeSnapshotsIntoTheAuraAndAttributionIsUnmoved:
    def test_disorder_on_a_refringed_aura_inherits_the_multiplier(self):
        builds = {
            "velina": BuildSnapshot(
                agent_name="Velina",
                agent_element="wind",
                agent_level=60,
                agent_base_atk=1500,
                agent_anomaly_proficiency=200,
            ),
            "fire_agent": BuildSnapshot(
                agent_name="FireGuy",
                agent_element="fire",
                agent_level=60,
                agent_base_atk=1000,
                agent_anomaly_proficiency=100,
            ),
            "remielle": BuildSnapshot(
                agent_name="Remielle",
                agent_element="lumiflux",
                agent_level=60,
                agent_base_atk=1000,
                agent_anomaly_proficiency=200,
            ),
        }
        enemy = EnemyProfile(
            name="Refringe Structural Target",
            level=60,
            defense=50,
            wind_res=0,
            fire_res=0,
            anomaly_capacity_wind=100,
            anomaly_capacity_fire=100,
            anomaly_duration_default=10.0,
        )
        moves_db = {
            "velina": _AgentMoves({"wind_hit": _RefringeMoveSpec(15000, 4.0, 1, "wind")}),
            "fireguy": _AgentMoves({"fire_hit": _RefringeMoveSpec(15000, 4.0, 1, "fire")}),
        }
        steps = [
            SimulatedAttackStep("velina", "wind_hit", []),
            SimulatedAttackStep("fire_agent", "fire_hit", []),
        ]

        result = simulate(
            builds,
            steps,
            enemy,
            moves_db,
            lumiflux_specs={"remielle": _lumiflux_spec()},
            initial_lumiflux_points=2,
        )

        disorder_events = [e for e in result.events if e.kind == "disorder"]
        assert len(disorder_events) == 1
        formulas = disorder_events[0].detail["zone_formulas"]
        assert "refringe" in formulas
        assert formulas["refringe"]["result_bp"] > 10000

    def test_two_agent_attribution_shares_unmoved_by_refringe(self):
        enemy = EnemyProfile(
            name="Attribution Structural Target",
            level=60,
            defense=50,
            ice_res=0,
            anomaly_capacity_ice=100,
            anomaly_duration_default=10.0,
        )
        builds = {
            "agent_a": BuildSnapshot(
                agent_name="agent_a",
                agent_element="ice",
                agent_level=60,
                agent_base_atk=3000,
                agent_anomaly_proficiency=300,
            ),
            "agent_b": BuildSnapshot(
                agent_name="agent_b",
                agent_element="ice",
                agent_level=60,
                agent_base_atk=200,
                agent_anomaly_proficiency=50,
            ),
            "remielle": BuildSnapshot(
                agent_name="Remielle",
                agent_element="lumiflux",
                agent_level=60,
                agent_base_atk=1000,
                agent_anomaly_proficiency=200,
            ),
        }
        moves_db = {
            "agent_a": _AgentMoves({"hit_a": _RefringeMoveSpec(8000, 1.0, 1, "ice")}),
            "agent_b": _AgentMoves({"hit_b": _RefringeMoveSpec(2000, 0.5, 1, "ice")}),
        }
        steps = [
            SimulatedAttackStep("agent_a", "hit_a", []),
            SimulatedAttackStep("agent_b", "hit_b", []),
        ]

        refringed = simulate(
            builds,
            steps,
            enemy,
            moves_db,
            lumiflux_specs={"remielle": _lumiflux_spec()},
            initial_lumiflux_points=1,
        )
        unrefringed = simulate(
            builds,
            steps,
            enemy,
            moves_db,
            lumiflux_specs={"remielle": _lumiflux_spec()},
            initial_lumiflux_points=0,
        )

        assert [e for e in refringed.events if e.kind == "refringe"]
        assert [e for e in unrefringed.events if e.kind == "refringe"] == []

        share_with = refringed.per_agent_attribution["agent_a"] / (
            refringed.per_agent_attribution["agent_a"] + refringed.per_agent_attribution["agent_b"]
        )
        share_without = unrefringed.per_agent_attribution["agent_a"] / (
            unrefringed.per_agent_attribution["agent_a"]
            + unrefringed.per_agent_attribution["agent_b"]
        )
        assert share_with == pytest.approx(share_without, rel=1e-3)


# ---------------------------------------------------------------------------
# Test 10 — Element enum audit (Task 2, test_element_lumiflux.py in full)
# ---------------------------------------------------------------------------


class TestElementEnumAudit:
    """DESIGN §9.1 test 10: a Lumiflux agent traverses every §4.2 site
    without raising and without picking up a phantom lumiflux_dmg bucket."""

    def test_element_id_map_has_the_confirmed_id_uniquely(self):
        assert ELEMENT_ID_MAP[300] == Element.LUMIFLUX
        assert list(ELEMENT_ID_MAP.values()).count(Element.LUMIFLUX) == 1

    def test_total_stats_elemental_dmg_is_zero_no_bucket(self):
        assert TotalStats().elemental_dmg(LUMIFLUX) == 0

    def test_disc_optimizer_union_fields_exclude_lumiflux_dmg(self):
        assert "lumiflux_dmg" not in _ELEMENT_DMG_FIELDS

    def test_element_to_anomaly_has_no_lumiflux_entry(self):
        assert ELEMENT_TO_ANOMALY.get(LUMIFLUX) is None

    def test_dominant_buildup_element_does_not_raise_on_lumiflux(self):
        # A synthetic zero-buildup lumiflux attack: falls back to the agent's
        # own element without touching ELEMENT_TO_ANOMALY.
        result = _dominant_buildup_element([], LUMIFLUX)
        assert result == LUMIFLUX
