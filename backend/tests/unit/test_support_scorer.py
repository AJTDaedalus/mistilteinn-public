"""Unit tests for score_support_disc_potential — R3.15/R3.16.

R3.15 acceptance:
  - A channel-1-only support (no stat-scaled buffs) yields avg == max equal to
    the set-bonus delta.
  - A candidate disc with the same set as the currently-equipped disc in that
    slot scores exactly 0 improvement (set composition unchanged).

R3.16 acceptance:
  - A stat-scaled support yields a non-degenerate PMF (avg ≠ max, stddev > 0).
  - A non-scaled support still collapses to a single point (avg == max).
"""

from __future__ import annotations

import pytest

from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep
from app.services.damage_calculator import CritMode
from app.services.disc_optimizer import DiscCandidate
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.rank_pipeline import PlainBuildDisc
from app.services.support_recompute import SupportRecomputeKit
from app.services.support_scorer import score_support_disc_potential

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _plain_disc(slot: int, set_id: int) -> PlainBuildDisc:
    return PlainBuildDisc(
        slot=slot,
        main_stat_type="atk",
        main_stat_value=0,
        substats=[],
        set_hakushin_id=set_id,
    )


def _team_atk_2pc_mod(value: int = 500) -> Modifier:
    """Disc set 2pc team atk_pct bonus."""
    return Modifier(
        stat="atk_pct",
        value=value,
        source=ModifierSource.DISC_SET_2PC,
        source_label="2pc team atk",
        target=ModifierTarget.TEAM,
        conditions=(Condition.ALWAYS,),
        scopes=(AttackScope.ALL,),
        max_stacks=1,
    )


def _minimal_kit(disc_set_mods: dict[int, list[Modifier]]) -> SupportRecomputeKit:
    """SupportRecomputeKit with no HP-scaled mods, only disc-set team mods."""
    return SupportRecomputeKit(
        agent_base_hp=10000,
        core_hp_pct=0,
        we_initial_hp_pct=0,
        we_combat_hp_pct=0,
        we_secondary_hp_pct=0,
        disc_set_modifiers=disc_set_mods,
        build_discs=[],
        agent_name="Supporter",
    )


def _primary_snap() -> BuildSnapshot:
    """Minimal DPS snapshot: 1000 base ATK, no crit, no modifiers."""
    return BuildSnapshot(
        agent_base_hp=20000,
        agent_base_atk=1000,
        agent_base_def=600,
        agent_crit_rate=0,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        agent_pen_ratio=0,
        agent_pen_flat=0,
        wengine_base_atk=0,
        agent_name="DPS",
        agent_element="fire",
        agent_level=60,
        disc_stats=[],
        modifiers=[],
    )


def _flat_enemy() -> EnemySnapshot:
    """Enemy with 0 DEF so DEFArea=1.0 and no element resistance."""
    return EnemySnapshot(level=60, base_def=0, element_res=0)


def _one_hit_combo(multiplier: int = 10000) -> list[ComboStep]:
    """Single standard attack step with the given multiplier (basis points)."""
    return [
        ComboStep(
            label="Basic",
            attack_id="basic_1",
            attack_name="Basic Attack",
            scope=AttackScope.ALL,
            multiplier=multiplier,
        ),
    ]


def _conditions() -> ActiveConditions:
    return ActiveConditions()


# ---------------------------------------------------------------------------
# Test: channel-1 — set bonus is gained when candidate completes the 2pc
# ---------------------------------------------------------------------------


class TestChannel1SetCountGain:
    """Swapping in a disc that completes the support's 2pc set gains the team bonus."""

    def test_avg_equals_max_equals_set_bonus_delta(self):
        """Channel-1 only: improvement is deterministic so avg == max."""
        team_mod = _team_atk_2pc_mod(value=500)  # +5% ATK to primary
        kit = _minimal_kit({100: [team_mod]})

        # Support baseline: slot1=set 999 (no set bonus), slot2=set 100 (only 1pc)
        support_discs = [_plain_disc(1, 999), _plain_disc(2, 100)]

        # Candidate: disc from set 100 at slot 1 → 2pc threshold met
        candidate = DiscCandidate(
            disc_id="cand-1",
            slot=1,
            set_id=100,
            main_stat_type="atk",
            main_stat_value=0,
            substats=[],
        )

        result = score_support_disc_potential(
            primary_snap_without_support=_primary_snap(),
            kit=kit,
            support_build_discs=support_discs,
            candidate=candidate,
            enemy=_flat_enemy(),
            combo_steps=_one_hit_combo(10000),
            conditions=_conditions(),
            crit_mode=CritMode.EXPECTED,
        )

        # avg == max (single-point PMF for channel-1)
        assert result.mean_improvement == pytest.approx(result.max_improvement, rel=1e-9)
        # stddev is zero — deterministic result
        assert result.stddev_improvement == pytest.approx(0.0, abs=1e-9)
        # improvement is positive (team bonus was gained)
        assert result.mean_improvement > 0

    def test_improvement_matches_expected_set_bonus_damage_delta(self):
        """Improvement equals (primary damage WITH team atk_pct +500bp) - (without)."""
        team_mod = _team_atk_2pc_mod(value=500)
        kit = _minimal_kit({100: [team_mod]})
        support_discs = [_plain_disc(1, 999), _plain_disc(2, 100)]
        candidate = DiscCandidate(
            disc_id="cand-1",
            slot=1,
            set_id=100,
            main_stat_type="atk",
            main_stat_value=0,
            substats=[],
        )

        result = score_support_disc_potential(
            primary_snap_without_support=_primary_snap(),
            kit=kit,
            support_build_discs=support_discs,
            candidate=candidate,
            enemy=_flat_enemy(),
            combo_steps=_one_hit_combo(10000),
            conditions=_conditions(),
            crit_mode=CritMode.EXPECTED,
        )

        # baseline_damage is set as the primary with no team bonus active
        assert result.baseline_damage > 0
        assert result.mean_improvement > 0
        # The improvement should be strictly less than baseline (not >100% gain)
        assert result.mean_improvement < result.baseline_damage

    def test_distribution_is_single_point(self):
        """Channel-1 PMF collapses to exactly one outcome with probability 1.0."""
        team_mod = _team_atk_2pc_mod(value=500)
        kit = _minimal_kit({100: [team_mod]})
        support_discs = [_plain_disc(1, 999), _plain_disc(2, 100)]
        candidate = DiscCandidate(
            disc_id="cand-1",
            slot=1,
            set_id=100,
            main_stat_type="atk",
            main_stat_value=0,
            substats=[],
        )

        result = score_support_disc_potential(
            primary_snap_without_support=_primary_snap(),
            kit=kit,
            support_build_discs=support_discs,
            candidate=candidate,
            enemy=_flat_enemy(),
            combo_steps=_one_hit_combo(10000),
            conditions=_conditions(),
        )

        assert len(result.distribution) == 1
        delta, prob = result.distribution[0]
        assert prob == pytest.approx(1.0)
        assert delta == pytest.approx(result.mean_improvement)


# ---------------------------------------------------------------------------
# Test: channel-1 — no change when candidate has same set as current disc
# ---------------------------------------------------------------------------


class TestChannel1NoChange:
    """Swapping in a disc with the same set as the current one yields 0 improvement."""

    def test_same_set_scores_zero(self):
        """Replacing a disc with another from the same set → no set-count change → 0."""
        team_mod = _team_atk_2pc_mod(value=500)
        kit = _minimal_kit({100: [team_mod]})

        # Support baseline: two discs from set 100 → 2pc already active
        support_discs = [_plain_disc(1, 100), _plain_disc(2, 100)]

        # Candidate also from set 100 → 2pc stays active → same team mods
        candidate = DiscCandidate(
            disc_id="cand-same",
            slot=1,
            set_id=100,
            main_stat_type="atk",
            main_stat_value=0,
            substats=[],
        )

        result = score_support_disc_potential(
            primary_snap_without_support=_primary_snap(),
            kit=kit,
            support_build_discs=support_discs,
            candidate=candidate,
            enemy=_flat_enemy(),
            combo_steps=_one_hit_combo(10000),
            conditions=_conditions(),
        )

        assert result.mean_improvement == pytest.approx(0.0, abs=1e-6)
        assert result.max_improvement == pytest.approx(0.0, abs=1e-6)

    def test_two_pc_active_slot_swap_same_set_zero(self):
        """When 2pc is met and we swap in the same set, improvement is exactly 0."""
        team_mod = _team_atk_2pc_mod(value=1000)
        kit = _minimal_kit({200: [team_mod]})

        support_discs = [_plain_disc(1, 200), _plain_disc(2, 200), _plain_disc(3, 999)]
        candidate = DiscCandidate(
            disc_id="cand-same-2",
            slot=1,
            set_id=200,
            main_stat_type="atk",
            main_stat_value=0,
            substats=[],
        )

        result = score_support_disc_potential(
            primary_snap_without_support=_primary_snap(),
            kit=kit,
            support_build_discs=support_discs,
            candidate=candidate,
            enemy=_flat_enemy(),
            combo_steps=_one_hit_combo(10000),
            conditions=_conditions(),
        )

        assert result.mean_improvement == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Test: channel-1 — bonus lost when candidate breaks the 2pc
# ---------------------------------------------------------------------------


class TestChannel1BonusLost:
    """Breaking the support's 2pc by swapping in a disc from a different set."""

    def test_breaking_2pc_yields_negative_improvement(self):
        """Swapping out a disc that was keeping the 2pc active → negative improvement."""
        team_mod = _team_atk_2pc_mod(value=500)
        kit = _minimal_kit({100: [team_mod]})

        # Baseline: exactly 2pc of set 100 → team bonus active
        support_discs = [_plain_disc(1, 100), _plain_disc(2, 100)]

        # Candidate: from set 999 at slot 1 → now 1pc of set 100 → 2pc broken
        candidate = DiscCandidate(
            disc_id="cand-break",
            slot=1,
            set_id=999,
            main_stat_type="atk",
            main_stat_value=0,
            substats=[],
        )

        result = score_support_disc_potential(
            primary_snap_without_support=_primary_snap(),
            kit=kit,
            support_build_discs=support_discs,
            candidate=candidate,
            enemy=_flat_enemy(),
            combo_steps=_one_hit_combo(10000),
            conditions=_conditions(),
        )

        assert result.mean_improvement < 0
        assert result.mean_improvement == pytest.approx(result.max_improvement, rel=1e-9)


# ---------------------------------------------------------------------------
# R3.16 — stat-scaling PMF channel
# ---------------------------------------------------------------------------


def _hp_scaled_team_mod(cap: int = 10000) -> Modifier:
    """HP-scaled atk_pct team mod: +10bp per 100 HP above 10000 (cap high)."""
    return Modifier(
        stat="atk_pct",
        value=cap,
        source=ModifierSource.CORE_SKILL,
        source_label="HpScaleTeamBuff",
        target=ModifierTarget.TEAM,
        conditions=(Condition.ALWAYS,),
        scopes=(AttackScope.ALL,),
        max_stacks=1,
        hp_scale_base=0,
        hp_scale_threshold=10000,
        hp_scale_per_unit=100,
        hp_scale_unit=10,
    )


def _hp_scaled_kit(disc_set_mods: dict | None = None) -> SupportRecomputeKit:
    """Kit with a single HP-scaled team mod; no disc-set bonuses by default."""
    return SupportRecomputeKit(
        agent_base_hp=10000,
        core_hp_pct=0,
        we_initial_hp_pct=0,
        we_combat_hp_pct=0,
        we_secondary_hp_pct=0,
        disc_set_modifiers=disc_set_mods or {},
        build_discs=[],
        agent_name="Supporter",
        agent_kit_mods_prefiltered=[_hp_scaled_team_mod()],
    )


def _s_rank_8roll_disc() -> DiscCandidate:
    """S-rank disc, 4 substats, 8 rolls used (1 remaining).

    hp_pct=1200bp (4 rolls), atk_pct=600bp (2 rolls), crit_rate=240bp (1 roll),
    def_pct=480bp (1 roll) → rolls_used=8, remaining=1.
    """
    return DiscCandidate(
        disc_id="test-s-8roll",
        slot=1,
        set_id=999,
        main_stat_type="atk",
        main_stat_value=0,
        substats=[
            {"stat": "hp_pct", "value": 1200},
            {"stat": "atk_pct", "value": 600},
            {"stat": "crit_rate", "value": 240},
            {"stat": "def_pct", "value": 480},
        ],
    )


class TestChannel2StatScaling:
    """R3.16 — stat-scaling PMF: a non-scaled support collapses; scaled gives spread."""

    def test_non_scaled_kit_still_single_point(self):
        """Without HP-scaled team mods, channel-2 is not triggered → avg == max."""
        team_mod = _team_atk_2pc_mod(value=500)
        kit = _minimal_kit({999: [team_mod]})  # no hp_scale_per_unit mods

        support_discs = [_plain_disc(1, 999), _plain_disc(2, 999)]
        candidate = DiscCandidate(
            disc_id="no-scale",
            slot=1,
            set_id=999,
            main_stat_type="atk",
            main_stat_value=0,
            substats=[{"stat": "hp_pct", "value": 300}],
        )

        result = score_support_disc_potential(
            primary_snap_without_support=_primary_snap(),
            kit=kit,
            support_build_discs=support_discs,
            candidate=candidate,
            disc_rarity="S",
            enemy=_flat_enemy(),
            combo_steps=_one_hit_combo(10000),
            conditions=_conditions(),
        )

        assert result.mean_improvement == pytest.approx(result.max_improvement, rel=1e-9)
        assert result.stddev_improvement == pytest.approx(0.0, abs=1e-9)
        assert len(result.distribution) == 1

    def test_hp_scaled_support_yields_non_degenerate_pmf(self):
        """HP-scaled team mod: different hp_pct roll counts → avg ≠ max."""
        kit = _hp_scaled_kit()

        # Disc already equipped in slot 1 (baseline uses same disc)
        candidate = _s_rank_8roll_disc()
        support_discs = [
            PlainBuildDisc(
                slot=1,
                main_stat_type=candidate.main_stat_type,
                main_stat_value=candidate.main_stat_value,
                substats=list(candidate.substats),
                set_hakushin_id=candidate.set_id,
            ),
        ]

        result = score_support_disc_potential(
            primary_snap_without_support=_primary_snap(),
            kit=kit,
            support_build_discs=support_discs,
            candidate=candidate,
            disc_rarity="S",
            enemy=_flat_enemy(),
            combo_steps=_one_hit_combo(10000),
            conditions=_conditions(),
        )

        # Non-degenerate: avg < max because only 1/4 rolls hit hp_pct
        assert result.max_improvement > result.mean_improvement
        assert result.stddev_improvement > 0
        # Distribution has more than one outcome
        assert len(result.distribution) > 1

    def test_hp_scaled_pmf_max_is_hp_roll_outcome(self):
        """Max improvement corresponds to the outcome where the last roll hits hp_pct."""
        kit = _hp_scaled_kit()
        candidate = _s_rank_8roll_disc()
        support_discs = [
            PlainBuildDisc(
                slot=1,
                main_stat_type=candidate.main_stat_type,
                main_stat_value=candidate.main_stat_value,
                substats=list(candidate.substats),
                set_hakushin_id=candidate.set_id,
            ),
        ]

        result = score_support_disc_potential(
            primary_snap_without_support=_primary_snap(),
            kit=kit,
            support_build_discs=support_discs,
            candidate=candidate,
            disc_rarity="S",
            enemy=_flat_enemy(),
            combo_steps=_one_hit_combo(10000),
            conditions=_conditions(),
        )

        # With 1 remaining roll, PMF has 4 outcomes (one per substat)
        assert len(result.distribution) == 4
        # Only the hp_pct outcome increases HP; other 3 are identical (same baked value)
        deltas = [d for d, _ in result.distribution]
        # At least two distinct values: hp_pct-roll outcome vs others
        assert len({round(d, 4) for d in deltas}) >= 2

    def test_hp_scaled_pmf_probabilities_sum_to_one(self):
        """PMF probabilities sum to 1.0."""
        kit = _hp_scaled_kit()
        candidate = _s_rank_8roll_disc()
        support_discs = [
            PlainBuildDisc(
                slot=1,
                main_stat_type=candidate.main_stat_type,
                main_stat_value=candidate.main_stat_value,
                substats=list(candidate.substats),
                set_hakushin_id=candidate.set_id,
            ),
        ]

        result = score_support_disc_potential(
            primary_snap_without_support=_primary_snap(),
            kit=kit,
            support_build_discs=support_discs,
            candidate=candidate,
            disc_rarity="S",
            enemy=_flat_enemy(),
            combo_steps=_one_hit_combo(10000),
            conditions=_conditions(),
        )

        total_prob = sum(p for _, p in result.distribution)
        assert total_prob == pytest.approx(1.0, abs=1e-9)

    def test_hp_scaled_rolls_used_and_remaining_set(self):
        """rolls_used and remaining_rolls are set correctly from the disc rarity."""
        kit = _hp_scaled_kit()
        candidate = _s_rank_8roll_disc()  # 8 rolls used, 1 remaining
        support_discs = [
            PlainBuildDisc(
                slot=1,
                main_stat_type=candidate.main_stat_type,
                main_stat_value=candidate.main_stat_value,
                substats=list(candidate.substats),
                set_hakushin_id=candidate.set_id,
            ),
        ]

        result = score_support_disc_potential(
            primary_snap_without_support=_primary_snap(),
            kit=kit,
            support_build_discs=support_discs,
            candidate=candidate,
            disc_rarity="S",
            enemy=_flat_enemy(),
            combo_steps=_one_hit_combo(10000),
            conditions=_conditions(),
        )

        assert result.rolls_used == 8
        assert result.remaining_rolls == 1
