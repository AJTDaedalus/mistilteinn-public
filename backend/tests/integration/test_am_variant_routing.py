"""Integration test for Phaethon's Melody AM-variant event-log routing (Task 1.6f).

Verifies that score_disc_potential routes to the correct precomputed event-log
bucket when a candidate completes a Phaethon's Melody 2pc (AM-granting set),
and that a non-AM (AP) set produces no extra variant.

Does not require Docker/DB: exercises the real modifier JSON files and the
full disc-scorer service against plain Python objects.
"""

from __future__ import annotations

from app.services.am_variants import (
    build_am_2pc_sets,
    enumerate_coarse_am_values,
    resolve_coarse_am,
)
from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import AnomalyStep, ComboStep
from app.services.disc_optimizer import DiscCandidate
from app.services.disc_scorer import score_disc_potential
from app.services.modifier_loader import load_disc_set_modifiers
from app.services.modifiers import AttackScope
from app.services.rank_pipeline import PlainBuildDisc

# ---------------------------------------------------------------------------
# Phaethon's Melody — hakushin_id used in the real modifier JSON.
# ---------------------------------------------------------------------------
_PM_SET_ID = 33000
_AP_SET_ID = 31300  # Freedom Blues — grants AP, NOT AM → no extra variant
_BASE_AM = 100

# Phaethon's 2pc: AM +8% (800 bp).  floor(100 * 10800 / 10000) = 108.
_PM_AM = 108


def _make_combo_step(multiplier: int = 10000) -> ComboStep:
    return ComboStep(
        label="Hit",
        attack_id="hit_0",
        attack_name="Hit",
        scope=AttackScope.ALL,
        multiplier=multiplier,
    )


def _make_anomaly_step() -> AnomalyStep:
    return AnomalyStep(
        label="Shock",
        attack_id="shock_0",
        anomaly_type="shock",
        element="electric",
        procs_override=1,
    )


def _make_base_build() -> BuildSnapshot:
    """Minimal electric anomaly attacker snapshot."""
    return BuildSnapshot(
        agent_base_atk=1000,
        agent_base_hp=10000,
        agent_base_def=500,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=100,
        agent_anomaly_mastery=_BASE_AM,
        agent_element="electric",
        disc_stats=[],
        modifiers=[],
    )


def _make_enemy() -> EnemySnapshot:
    return EnemySnapshot(level=60, base_def=50, element_res=0)


_S_RANK_SUBSTATS = [
    {"stat": "crit_rate", "value": 240, "rolls": 1},
    {"stat": "crit_dmg", "value": 480, "rolls": 1},
    {"stat": "pen_flat", "value": 9, "rolls": 1},
]


def _make_pm_candidate(slot: int = 6) -> DiscCandidate:
    """Slot-6 Phaethon's Melody candidate (no AM main stat — just the set membership)."""
    return DiscCandidate(
        disc_id=f"pm-cand-{slot}",
        slot=slot,
        set_id=_PM_SET_ID,
        main_stat_type="atk_pct",
        main_stat_value=3000,
        substats=_S_RANK_SUBSTATS,
    )


def _make_non_pm_candidate(slot: int = 6) -> DiscCandidate:
    """Slot-6 non-PM candidate (different set, identical stats otherwise)."""
    return DiscCandidate(
        disc_id="non-pm-cand-6",
        slot=slot,
        set_id=99901,  # fictional set, no AM bonus
        main_stat_type="atk_pct",
        main_stat_value=3000,
        substats=_S_RANK_SUBSTATS,
    )


def _make_locked_pm_disc(slot: int = 5) -> PlainBuildDisc:
    """One locked Phaethon's Melody disc in slot 5 — candidate in slot 6 completes the 2pc."""
    return PlainBuildDisc(
        slot=slot,
        main_stat_type="atk_pct",
        main_stat_value=3000,
        substats=[],
        set_hakushin_id=_PM_SET_ID,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_pm_am_2pc_sets() -> dict:
    """Load the real modifier file for Phaethon's Melody and build the AM-2pc map."""
    pm_mods = load_disc_set_modifiers(str(_PM_SET_ID))
    assert pm_mods, "phaethons_melody.json must be present and parseable"
    all_mods = {_PM_SET_ID: pm_mods}
    am_sets = build_am_2pc_sets(all_mods)
    assert _PM_SET_ID in am_sets, "Phaethon's Melody 2pc should be in AM 2pc set map"
    return am_sets


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPhaethonsMelodyAmRouting:
    """Phaethon's Melody 2pc routes to the higher-AM event-log bucket."""

    def test_pm_candidate_resolves_higher_am(self):
        """Completing the PM 2pc raises coarse AM from 100 → 108."""
        am_2pc_sets = _get_pm_am_2pc_sets()
        locked = [_make_locked_pm_disc(slot=5)]

        pm_cand = _make_pm_candidate(slot=6)
        non_pm_cand = _make_non_pm_candidate(slot=6)

        am_with_pm = resolve_coarse_am(_BASE_AM, [pm_cand, *locked], am_2pc_sets)
        am_without_pm = resolve_coarse_am(_BASE_AM, [non_pm_cand, *locked], am_2pc_sets)

        assert am_with_pm == _PM_AM, f"Expected {_PM_AM}, got {am_with_pm}"
        assert am_without_pm == _BASE_AM, f"Expected {_BASE_AM}, got {am_without_pm}"
        assert am_with_pm > am_without_pm

    def test_scorer_picks_higher_am_log_for_pm_candidate(self):
        """score_disc_potential returns higher damage for PM candidate via anomaly-step log."""
        am_2pc_sets = _get_pm_am_2pc_sets()

        # High-AM log has an extra anomaly step; low-AM log does not.
        std_step = _make_combo_step(multiplier=10000)
        anom_step = _make_anomaly_step()
        event_log_by_am = {
            _BASE_AM: [std_step],  # no anomaly → lower total
            _PM_AM: [std_step, anom_step],  # anomaly step → higher total
        }

        base_build = _make_base_build()
        enemy = _make_enemy()
        locked = [_make_locked_pm_disc(slot=5)]

        pm_cand = _make_pm_candidate(slot=6)
        non_pm_cand = _make_non_pm_candidate(slot=6)

        pm_result = score_disc_potential(
            base_build=base_build,
            enemy=enemy,
            combo_steps=event_log_by_am,
            disc=pm_cand,
            disc_rarity="S",
            conditions={},
            build_discs=locked,
            am_2pc_sets=am_2pc_sets,
        )
        non_pm_result = score_disc_potential(
            base_build=base_build,
            enemy=enemy,
            combo_steps=event_log_by_am,
            disc=non_pm_cand,
            disc_rarity="S",
            conditions={},
            build_discs=locked,
            am_2pc_sets=am_2pc_sets,
        )

        # PM candidate routes to the high-AM log (has anomaly step) → higher damage.
        assert pm_result.current_damage > non_pm_result.current_damage, (
            f"PM damage ({pm_result.current_damage:.1f}) should exceed "
            f"non-PM damage ({non_pm_result.current_damage:.1f})"
        )

    def test_pm_log_has_more_anomaly_steps_than_base_log(self):
        """The high-AM bucket contains more anomaly steps — anomaly count differs."""
        std_step = _make_combo_step()
        anom_step = _make_anomaly_step()
        event_log_by_am = {
            _BASE_AM: [std_step],
            _PM_AM: [std_step, anom_step],
        }

        base_anomaly_count = sum(
            1 for s in event_log_by_am[_BASE_AM] if isinstance(s, AnomalyStep)
        )
        pm_anomaly_count = sum(1 for s in event_log_by_am[_PM_AM] if isinstance(s, AnomalyStep))

        assert pm_anomaly_count > base_anomaly_count, (
            "Higher-AM log must have more anomaly steps than lower-AM log"
        )


class TestNonAmSetProducesNoExtraVariant:
    """A set that grants AP (not AM) does not produce an additional AM variant."""

    def test_ap_set_discs_yield_single_am_value(self):
        """Freedom Blues (AP set) in inventory → enumerate returns only base AM."""
        ap_mods = load_disc_set_modifiers(str(_AP_SET_ID))
        all_mods = {_AP_SET_ID: ap_mods}
        am_2pc_sets = build_am_2pc_sets(all_mods)

        # AP set must NOT appear in the AM 2pc map.
        assert _AP_SET_ID not in am_2pc_sets, (
            f"Set {_AP_SET_ID} grants AP, not AM — must be absent from am_2pc_sets"
        )

        # Inventory: two Freedom Blues discs (completes the 2pc, but AP only).
        inventory = [
            DiscCandidate(
                disc_id=f"fb-{i}",
                slot=i,
                set_id=_AP_SET_ID,
                main_stat_type="atk_pct",
                main_stat_value=3000,
            )
            for i in range(1, 3)
        ]
        values = enumerate_coarse_am_values(_BASE_AM, inventory, am_2pc_sets)
        assert values == [_BASE_AM], (
            f"AP-only inventory must yield a single AM variant ({_BASE_AM}), got {values}"
        )

    def test_pm_inventory_yields_two_am_values(self):
        """Inventory with ≥2 PM discs → enumerate returns 2 distinct AM values."""
        am_2pc_sets = _get_pm_am_2pc_sets()

        inventory = [
            DiscCandidate(
                disc_id=f"pm-{i}",
                slot=i,
                set_id=_PM_SET_ID,
                main_stat_type="atk_pct",
                main_stat_value=3000,
            )
            for i in range(1, 3)
        ]
        values = enumerate_coarse_am_values(_BASE_AM, inventory, am_2pc_sets)
        assert len(values) == 2, f"Expected 2 distinct AM values, got {values}"
        assert _BASE_AM in values
        assert _PM_AM in values
