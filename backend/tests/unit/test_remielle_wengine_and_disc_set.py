"""Task 19 — Ode of Resurrected Wings (W-Engine) + Feathered Fate (disc set)
kit JSONs (DESIGN_remielle.md §6).
"""

from app.services.buff_resolver import ActiveConditions, resolve_modifiers
from app.services.damage_calculator import calculate_luminize_damage
from app.services.modifier_loader import load_disc_set_modifiers, load_wengine_modifiers
from app.services.modifiers import Condition

ODE_ID = "14158"
FEATHERED_FATE_ID = "34100"

_LUMINIZE_KWARGS = {
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


class TestOdeOfResurrectedWings:
    def test_r1_values(self):
        mods = load_wengine_modifiers(ODE_ID, refinement=1)
        by_stat = {m.stat: m for m in mods}
        assert by_stat["anomaly_proficiency_flat"].value == 96
        assert by_stat["anomaly_dmg_bonus"].value == 2000
        assert by_stat["dmg_bonus"].value == 3000

    def test_r5_values(self):
        mods = load_wengine_modifiers(ODE_ID, refinement=5)
        by_stat = {m.stat: m for m in mods}
        assert by_stat["anomaly_proficiency_flat"].value == 135
        assert by_stat["anomaly_dmg_bonus"].value == 3200
        assert by_stat["dmg_bonus"].value == 4800

    def test_ap_is_always_active_dmg_rows_are_refringe_gated(self):
        mods = load_wengine_modifiers(ODE_ID, refinement=1)
        by_stat = {m.stat: m for m in mods}
        assert by_stat["anomaly_proficiency_flat"].conditions == (Condition.ALWAYS,)
        # Both DMG rows carry the equipper gate as well -- see
        # TestOdeRefringeRowsRequireALumifluxEquipper for why.
        assert set(by_stat["anomaly_dmg_bonus"].conditions) == {
            Condition.REFRINGE_TRIGGERED,
            Condition.EQUIPPER_IS_LUMIFLUX,
        }
        assert set(by_stat["dmg_bonus"].conditions) == {
            Condition.REFRINGE_TRIGGERED,
            Condition.EQUIPPER_IS_LUMIFLUX,
        }

    def test_self_dmg_row_is_self_squad_row_is_team(self):
        mods = load_wengine_modifiers(ODE_ID, refinement=1)
        by_stat = {m.stat: m for m in mods}
        assert by_stat["anomaly_dmg_bonus"].target.value == "self"
        assert by_stat["dmg_bonus"].target.value == "team"


class TestOdeRefringeRowsRequireALumifluxEquipper:
    """Audit finding S1-E / hardening Task 3.

    `REFRINGE_TRIGGERED` is injected **sim-wide** for the 30s after any
    Lumiflux agent's Refringe -- it is not scoped to the equipper. So on
    `refringe_triggered` alone, both DMG rows fired for *whoever* held this
    W-Engine while Remielle was inside her window, which contradicts the DB
    text: "When **the equipper** triggers a Refringe reaction...". Only a
    Lumiflux agent can trigger a Refringe, so the equipper gate is the
    faithful encoding.

    Conditions are ANDed (`ActiveConditions.all_active`), and
    `equipper_is_lumiflux` auto-resolves from the equipper's own element at
    snapshot time -- the same pattern feathered_fate.json[2] already uses.
    """

    def _resolved(self, *, equipper: Condition, refringe: bool, refinement: int = 1):
        mods = load_wengine_modifiers(ODE_ID, refinement=refinement)
        active = {Condition.ALWAYS, equipper}
        if refringe:
            active.add(Condition.REFRINGE_TRIGGERED)
        return resolve_modifiers(mods, ActiveConditions(active=active))

    def test_non_lumiflux_equipper_in_a_refringe_window_gets_nothing(self):
        """The S1-E leak, inverted: a Fire equipper riding Remielle's window."""
        resolved = self._resolved(equipper=Condition.EQUIPPER_IS_FIRE, refringe=True)
        assert resolved.anomaly_dmg_bonus == 0
        assert resolved.total_dmg_bonus == 0

    def test_lumiflux_equipper_outside_a_refringe_window_gets_nothing(self):
        """The other half of the AND: the equipper gate does not make the
        rows unconditional."""
        resolved = self._resolved(equipper=Condition.EQUIPPER_IS_LUMIFLUX, refringe=False)
        assert resolved.anomaly_dmg_bonus == 0
        assert resolved.total_dmg_bonus == 0

    def test_lumiflux_equipper_in_a_refringe_window_gets_the_r1_values(self):
        resolved = self._resolved(equipper=Condition.EQUIPPER_IS_LUMIFLUX, refringe=True)
        assert resolved.anomaly_dmg_bonus == 2000
        assert resolved.total_dmg_bonus == 3000

    def test_lumiflux_equipper_in_a_refringe_window_gets_the_r5_values(self):
        resolved = self._resolved(
            equipper=Condition.EQUIPPER_IS_LUMIFLUX, refringe=True, refinement=5
        )
        assert resolved.anomaly_dmg_bonus == 3200
        assert resolved.total_dmg_bonus == 4800

    def test_the_always_on_ap_row_is_untouched_by_the_gate(self):
        """The equipper gate is on the two Refringe rows only -- the flat AP
        grant is unconditional for any equipper, per the DB text."""
        resolved = self._resolved(equipper=Condition.EQUIPPER_IS_FIRE, refringe=False)
        assert resolved.stat_bonuses["anomaly_proficiency_flat"] == 96


class TestFeatheredFate:
    def test_2pc_and_4pc_ap_grants(self):
        mods = load_disc_set_modifiers(FEATHERED_FATE_ID)
        ap_rows = [m for m in mods if m.stat == "anomaly_proficiency_flat"]
        assert sorted(m.value for m in ap_rows) == [30, 50]
        assert all(m.conditions == (Condition.ALWAYS,) for m in ap_rows)

    def test_4pc_attribute_anomaly_dmg_gates_on_lumiflux_equipper(self):
        mods = load_disc_set_modifiers(FEATHERED_FATE_ID)
        anomaly_dmg_row = next(m for m in mods if m.stat == "anomaly_dmg_bonus")
        assert anomaly_dmg_row.value == 1500
        assert anomaly_dmg_row.conditions == (Condition.EQUIPPER_IS_LUMIFLUX,)
        assert anomaly_dmg_row.target.value == "self"

    def test_lumiflux_gate_resolves_for_a_lumiflux_equipper(self):
        mods = load_disc_set_modifiers(FEATHERED_FATE_ID)
        conditions = ActiveConditions(active={Condition.ALWAYS, Condition.EQUIPPER_IS_LUMIFLUX})
        resolved = resolve_modifiers(mods, conditions)
        assert resolved.anomaly_dmg_bonus == 1500

    def test_lumiflux_gate_blocks_for_a_non_lumiflux_equipper(self):
        mods = load_disc_set_modifiers(FEATHERED_FATE_ID)
        conditions = ActiveConditions(active={Condition.ALWAYS, Condition.EQUIPPER_IS_FIRE})
        resolved = resolve_modifiers(mods, conditions)
        assert resolved.anomaly_dmg_bonus == 0


class TestFeatheredFateReachesLuminizePostStorage:
    """DESIGN §7.2: the 4pc +15% is universal Attribute Anomaly DMG, so it
    must buff Luminize even though the Voidflare itself is frozen at
    capture -- Remielle's OWN current anomaly_dmg_bonus still applies."""

    def test_4pc_bonus_raises_luminize_damage_for_a_lumiflux_equipper(self):
        without_4pc = calculate_luminize_damage(
            **_LUMINIZE_KWARGS, remielle_anomaly_dmg_bonus=0
        )
        with_4pc = calculate_luminize_damage(
            **_LUMINIZE_KWARGS, remielle_anomaly_dmg_bonus=1500
        )
        assert with_4pc.total > without_4pc.total
        assert with_4pc.anomaly_boost_mult == without_4pc.anomaly_boost_mult + 1500


class TestEquipperConditionsNeverSurfaceAsUserCheckboxes:
    """Adjacent code gap found by the S1-E audit (hardening Task 3).

    `equipper_is_*` conditions are resolved automatically at snapshot time
    against the equipper's own specialty/element, so they must never reach
    `GET /builds/{id}/conditions` as user-toggleable checkboxes.
    `Condition.EQUIPPER_IS_LUMIFLUX` was declared for Remielle but never added
    to `_SKIP_CONDITIONS`, so it leaked into the UI as a checkbox the user
    could set to the wrong value.

    Asserted as an invariant over the whole enum rather than as a one-off pin
    on the condition just added, so the next element or specialty added to
    `Condition` cannot reintroduce the same gap silently.
    """

    def test_every_equipper_condition_is_skipped(self):
        from app.api.v1.builds import _SKIP_CONDITIONS

        equipper_conditions = {c for c in Condition if c.value.startswith("equipper_is_")}
        assert equipper_conditions, "enum should declare equipper conditions"
        assert equipper_conditions <= _SKIP_CONDITIONS

    def test_lumiflux_specifically(self):
        from app.api.v1.builds import _SKIP_CONDITIONS

        assert Condition.EQUIPPER_IS_LUMIFLUX in _SKIP_CONDITIONS
