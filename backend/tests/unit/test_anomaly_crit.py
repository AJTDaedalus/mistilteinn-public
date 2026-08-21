"""Anomaly CRIT — the kit-granted exemption to "anomaly damage does not crit" (issue #162).

Two properties this file exists to protect:

1. **The default is hard.** Anomaly damage does not crit unless a kit grants it,
   and that must hold in *every* crit mode — including ``CritMode.CRIT``, where
   the standard `crit_multiplier` would happily return ``10000 + crit_dmg``
   without ever consulting the rate.
2. **The pool is separate.** Disc CRIT Rate / CRIT DMG must never reach anomaly
   damage. ZO models this as `anom_crit_` / `anom_crit_dmg_` alongside, never
   inside, `crit_` / `crit_dmg_`.

Pins are absolute integers with the arithmetic derived in-comment, per D-KV4 —
a ratio assertion would pass against a chain that had moved by a constant factor.
"""

from __future__ import annotations

import pytest

from app.models.enums import ANOMALY_TO_ELEMENT, ELEMENT_TO_ANOMALY
from app.models.enums import AnomalyType as ModelAnomalyType
from app.services.buff_resolver import ELEMENT_SCOPE_HONORED_STATS, resolve_modifiers
from app.services.damage_calculator import (
    AnomalyType,
    CritMode,
    calculate_anomaly_damage,
)
from app.services.modifiers import ActiveConditions, Modifier, ModifierSource, ModifierTarget

_BASE_ARGS = {
    "anomaly_type": AnomalyType.ASSAULT,
    "atk": 3000,
    "anomaly_proficiency": 400,
    "attacker_level": 60,
    "enemy_base_def": 60,
    "enemy_level": 60,
}


class TestDefaultIsNonCrit:
    """Property 1 — absent a kit grant, anomaly damage does not crit."""

    def test_no_grant_leaves_the_zone_neutral(self) -> None:
        result = calculate_anomaly_damage(**_BASE_ARGS)
        assert result.anomaly_crit_mult == 10000

    @pytest.mark.parametrize("mode", list(CritMode))
    def test_zero_rate_is_neutral_in_every_crit_mode(self, mode: CritMode) -> None:
        """`CritMode.CRIT` must not turn an ungranted anomaly into a guaranteed crit.

        This is the regression that motivated guarding on the rate rather than
        the mode: `crit_multiplier(0, 5000, CritMode.CRIT)` returns 15000, so
        delegating unconditionally would have made every anomaly in the game
        crit for 50% whenever a caller asked for crit-mode damage.
        """
        result = calculate_anomaly_damage(
            **_BASE_ARGS, anomaly_crit_rate=0, anomaly_crit_dmg=5000, crit_mode=mode
        )
        assert result.anomaly_crit_mult == 10000

    def test_crit_dmg_without_a_rate_contributes_nothing(self) -> None:
        """An orphaned CRIT DMG grant must not credit damage that cannot occur."""
        granted = calculate_anomaly_damage(**_BASE_ARGS, anomaly_crit_dmg=9999)
        assert granted.total == calculate_anomaly_damage(**_BASE_ARGS).total

    def test_disc_crit_stats_are_not_a_parameter_of_this_function(self) -> None:
        """The separate-pool property, enforced structurally.

        `calculate_anomaly_damage` takes no `crit_rate` / `crit_dmg`. If someone
        adds them as an alias for the anomaly pool this fails, which is the
        point — ZO keeps `anom_crit_` distinct from `crit_`, and a disc's CRIT
        Rate must not reach anomaly damage.
        """
        import inspect

        params = inspect.signature(calculate_anomaly_damage).parameters
        assert "crit_rate" not in params
        assert "crit_dmg" not in params
        assert "anomaly_crit_rate" in params
        assert "anomaly_crit_dmg" in params


class TestGrantedCrit:
    """Property 2 — a kit grant produces the ZO `anomaly_crit_mult_` zone."""

    def test_expected_mode_matches_the_zo_zone(self) -> None:
        """Jane core Lv.7 against an enemy in Gnawed, expected-value mode.

        DB `core_skills` level 7: base CRIT Rate 40%, +0.16%/AP, CRIT DMG 50%.
        At AP 400: rate = 4000 + 400*16 = 10400 bp, clamped to 10000 (ZO clamps
        `anom_cappedCrit_` to [0, 1] the same way).

        AnomalyCritArea = 10000 + clamp(rate) * crit_dmg / 10000
                        = 10000 + 10000 * 5000 // 10000
                        = 15000
        """
        result = calculate_anomaly_damage(
            **_BASE_ARGS,
            anomaly_crit_rate=4000 + 400 * 16,
            anomaly_crit_dmg=5000,
            crit_mode=CritMode.EXPECTED,
        )
        assert result.anomaly_crit_mult == 15000

    def test_sub_cap_rate_scales_linearly(self) -> None:
        """AnomalyCritArea = 10000 + 2500 * 5000 // 10000 = 11250."""
        result = calculate_anomaly_damage(
            **_BASE_ARGS,
            anomaly_crit_rate=2500,
            anomaly_crit_dmg=5000,
            crit_mode=CritMode.EXPECTED,
        )
        assert result.anomaly_crit_mult == 11250

    def test_m2_adds_to_crit_dmg_not_rate(self) -> None:
        """Jane M2: "+50% CRIT DMG when Assault DMG triggers a critical hit".

        At a 25% rate: 10000 + 2500 * (5000 + 5000) // 10000 = 12500.
        """
        result = calculate_anomaly_damage(
            **_BASE_ARGS,
            anomaly_crit_rate=2500,
            anomaly_crit_dmg=5000 + 5000,
            crit_mode=CritMode.EXPECTED,
        )
        assert result.anomaly_crit_mult == 12500

    def test_no_crit_mode_suppresses_a_real_grant(self) -> None:
        result = calculate_anomaly_damage(
            **_BASE_ARGS,
            anomaly_crit_rate=5000,
            anomaly_crit_dmg=5000,
            crit_mode=CritMode.NO_CRIT,
        )
        assert result.anomaly_crit_mult == 10000

    def test_the_zone_actually_reaches_the_damage_total(self) -> None:
        """Guards the "modifier resolves but never reaches the calc" failure mode.

        A pure-formula assertion on `anomaly_crit_mult` would still pass if the
        zone were computed and then dropped from the chain multiply, which is
        exactly how `anomaly_mastery_excess` silently no-opped.
        """
        plain = calculate_anomaly_damage(**_BASE_ARGS)
        crit = calculate_anomaly_damage(
            **_BASE_ARGS, anomaly_crit_rate=10000, anomaly_crit_dmg=5000
        )
        # 1.5x zone, applied multiplicatively into per_proc.
        assert crit.per_proc == plain.per_proc * 15000 // 10000
        assert crit.total > plain.total


class TestElementScoping:
    """The grants that exist are element-scoped; the buckets must honour that."""

    def test_both_buckets_are_element_scope_honored(self) -> None:
        assert "anomaly_crit_rate" in ELEMENT_SCOPE_HONORED_STATS
        assert "anomaly_crit_dmg" in ELEMENT_SCOPE_HONORED_STATS

    def test_anomaly_to_element_is_a_true_inverse(self) -> None:
        for element, anomaly in ELEMENT_TO_ANOMALY.items():
            assert ANOMALY_TO_ELEMENT[anomaly] is element
        assert len(ANOMALY_TO_ELEMENT) == len(ELEMENT_TO_ANOMALY)

    def test_every_calculator_anomaly_type_maps_to_an_element(self) -> None:
        """A new anomaly type must not silently lose its element mapping.

        `calculate_build_anomaly` looks the element up by value to scope the
        crit buckets; an unmapped type would raise KeyError at request time.
        """
        for anom in AnomalyType:
            assert ModelAnomalyType(anom.value) in ANOMALY_TO_ELEMENT

    def test_a_physical_scoped_grant_is_filtered_out_for_a_fire_anomaly(self) -> None:
        """Jane's Physical Assault grant must not reach a teammate's Burn."""
        mod = Modifier(
            stat="anomaly_crit_rate",
            value=4000,
            source=ModifierSource.CORE_SKILL,
            target=ModifierTarget.TEAM,
            element_scope=["physical"],
        )
        conditions = ActiveConditions()

        physical = resolve_modifiers(
            [mod], conditions, target_filter=ModifierTarget.TEAM, damage_element="physical"
        )
        fire = resolve_modifiers(
            [mod], conditions, target_filter=ModifierTarget.TEAM, damage_element="fire"
        )

        assert physical.anomaly_crit_rate == 4000
        assert fire.anomaly_crit_rate == 0


class TestAbloomKeepsItsOwnPoolButSharesTheShape:
    """C2 (#162): consistency without merging.

    C2 originally proposed folding Aria M1's Abloom crit into the general
    anomaly-crit pool. The two grants that exist are scoped on different axes —
    Jane's by ELEMENT (`anom_crit_.physical`), Aria's by DAMAGE SOURCE (Abloom
    alone) — and `element_scope` gates by element, so a shared bucket would hand
    Jane's Assault CRIT to a Physical Abloom she has no grant over. Same
    wrong-wiring class as M1's flattened Luminize RES-ignore (D-KV6).

    So the buckets stay separate and the *shape* is shared.
    """

    def test_abloom_crit_matches_the_anomaly_crit_zone_exactly(self) -> None:
        """Same rate/DMG must produce the same multiplier in both calculators."""
        from app.services.damage_calculator import calculate_abloom_damage

        anomaly = calculate_anomaly_damage(
            **_BASE_ARGS, anomaly_crit_rate=2500, anomaly_crit_dmg=5000
        )
        abloom = calculate_abloom_damage(
            abloom_mv_bp=10000,
            original_anomaly_dmg=10000,
            ap=100,
            crit_rate_bp=2500,
            crit_dmg_bp=5000,
        )
        assert abloom.crit_mult == anomaly.anomaly_crit_mult == 11250

    @pytest.mark.parametrize("mode", list(CritMode))
    def test_a_zero_rate_is_a_hard_no_in_every_mode(self, mode: CritMode) -> None:
        """The B1a guard, applied to Abloom.

        Without it, `CritMode.CRIT` would crit an Abloom whose kit grants no
        crit — every agent but Aria at M1.
        """
        from app.services.damage_calculator import calculate_abloom_damage

        res = calculate_abloom_damage(
            abloom_mv_bp=10000,
            original_anomaly_dmg=10000,
            ap=100,
            crit_rate_bp=0,
            crit_dmg_bp=5000,
            crit_mode=mode,
        )
        assert res.crit_mult == 10000

    def test_the_pools_are_distinct_parameters(self) -> None:
        """Structural: neither calculator can be fed the other's bucket by accident."""
        import inspect

        from app.services.damage_calculator import calculate_abloom_damage

        abloom_params = inspect.signature(calculate_abloom_damage).parameters
        anomaly_params = inspect.signature(calculate_anomaly_damage).parameters
        assert "anomaly_crit_rate" not in abloom_params
        assert "crit_rate_bp" not in anomaly_params
