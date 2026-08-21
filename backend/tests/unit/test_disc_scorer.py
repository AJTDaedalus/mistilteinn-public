"""Unit tests for the DAG-driven disc scorer (Phase 7a).

The scorer computes the upgrade-probability distribution of a disc's
damage contribution by enumerating outcomes over multinomial (and
weighted-pick) substat-roll RNG, then summarizes via max / mean /
stddev / percentiles / full PMF.

These tests stub the per-step DAG context + overlay with a
deterministic damage function over the target disc's substats so we
exercise the scorer's distribution logic without spinning up a full
build snapshot. The real DAG is covered by its own test suite.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from app.services.build_damage_service import BuildSnapshot
from app.services.combo_types import ComboStep
from app.services.disc_constants import SUBSTAT_BASE_PER_ROLL_BY_RARITY
from app.services.disc_optimizer import DiscCandidate
from app.services.disc_scorer import (
    BASE_VALUES,
    MAX_ROLLS_BY_RARITY,
    DiscScoreResult,
    score_disc_potential,
)
from app.services.modifiers import AttackScope
from app.services.stat_calculator import DiscStats


@pytest.fixture
def stub_dag(monkeypatch):
    """Replace the per-step context + overlay with a deterministic stub.

    ``build_damage_step_context`` returns an opaque sentinel; the
    overlay reads the target disc (always last in ``disc_stats``) and
    feeds it through the caller-supplied damage function.
    """

    def install(damage_fn):
        def fake_overlay(_ctx, disc):
            return float(damage_fn(disc))

        monkeypatch.setattr(
            "app.services.disc_scorer.build_damage_step_context",
            lambda **_: object(),
        )
        monkeypatch.setattr(
            "app.services.disc_scorer.compute_damage_with_accumulated_disc",
            fake_overlay,
        )

    return install


_SINGLE_STEP = ComboStep(
    label="x",
    attack_id="a",
    attack_name="x",
    scope=AttackScope.BASIC,
    multiplier=10000,
    element="fire",
)


def _common_args() -> dict:
    return {
        "base_build": BuildSnapshot(),
        "enemy": object(),
        "combo_steps": [_SINGLE_STEP],
        "conditions": object(),
    }


def _subs_to_map(disc_or_dict: dict | DiscStats) -> dict[str, int]:
    if isinstance(disc_or_dict, DiscStats):
        d = asdict(disc_or_dict)
        d.pop("set_bonuses", None)
        return d
    return {s["stat"]: s["value"] for s in disc_or_dict.get("substats", [])}


def _full_4sub_disc(**overrides) -> DiscCandidate:
    """An S-rank disc with all four substats present at one roll each."""
    base = {
        "disc_id": "d",
        "slot": 4,
        "set_id": 1,
        "main_stat_type": "atk_pct",
        "substats": [
            {"stat": "crit_rate", "value": BASE_VALUES["crit_rate"]},
            {"stat": "crit_dmg", "value": BASE_VALUES["crit_dmg"]},
            {"stat": "anomaly_proficiency", "value": BASE_VALUES["anomaly_proficiency"]},
            {"stat": "pen_flat", "value": BASE_VALUES["pen_flat"]},
        ],
    }
    base.update(overrides)
    return DiscCandidate(**base)


def _three_sub_disc(**overrides) -> DiscCandidate:
    """An S-rank disc with only three substats (4th yet to unlock)."""
    base = {
        "disc_id": "d",
        "slot": 4,
        "set_id": 1,
        "main_stat_type": "atk_pct",
        "substats": [
            {"stat": "crit_rate", "value": BASE_VALUES["crit_rate"]},
            {"stat": "crit_dmg", "value": BASE_VALUES["crit_dmg"]},
            {"stat": "pen_flat", "value": BASE_VALUES["pen_flat"]},
        ],
    }
    base.update(overrides)
    return DiscCandidate(**base)


class TestArgValidation:
    def test_unknown_rarity_raises(self, stub_dag):
        stub_dag(lambda _d: 100)
        with pytest.raises(ValueError, match="rarity"):
            score_disc_potential(
                **_common_args(),
                disc=_full_4sub_disc(),
                disc_rarity="Z",
            )

    def test_too_few_substats_for_s_rank_raises(self, stub_dag):
        """S-rank requires 3 or 4 legal substats; 2 is malformed."""
        stub_dag(lambda _d: 100)
        disc = DiscCandidate(
            disc_id="d",
            slot=4,
            set_id=1,
            main_stat_type="atk_pct",
            substats=[
                {"stat": "crit_rate", "value": BASE_VALUES["crit_rate"]},
                {"stat": "crit_dmg", "value": BASE_VALUES["crit_dmg"]},
            ],
        )
        with pytest.raises(ValueError, match="substats"):
            score_disc_potential(**_common_args(), disc=disc, disc_rarity="S")

    def test_returns_expected_shape(self, stub_dag):
        stub_dag(lambda _d: 100)
        result = score_disc_potential(
            **_common_args(),
            disc=_full_4sub_disc(),
            disc_rarity="S",
        )
        assert isinstance(result, DiscScoreResult)
        assert result.current_damage == 100
        assert isinstance(result.distribution, list)


class TestRollCounting:
    def test_full_4sub_disc_at_base_uses_4_rolls(self, stub_dag):
        stub_dag(lambda _d: 1)
        result = score_disc_potential(
            **_common_args(),
            disc=_full_4sub_disc(),
            disc_rarity="S",
        )
        assert result.rolls_used == 4
        assert result.remaining_rolls == MAX_ROLLS_BY_RARITY["S"] - 4

    def test_main_stat_substat_entries_not_counted(self, stub_dag):
        """Defensive: a substat matching the main stat is illegal (skip)."""
        stub_dag(lambda _d: 1)
        disc = _full_4sub_disc()
        disc = DiscCandidate(
            **{
                **disc.__dict__,
                "main_stat_type": "crit_rate",
                "substats": [
                    {"stat": "crit_rate", "value": BASE_VALUES["crit_rate"] * 5},
                    {"stat": "crit_dmg", "value": BASE_VALUES["crit_dmg"]},
                    {"stat": "anomaly_proficiency", "value": BASE_VALUES["anomaly_proficiency"]},
                    {"stat": "pen_flat", "value": BASE_VALUES["pen_flat"]},
                ],
            },
        )
        result = score_disc_potential(
            **_common_args(),
            disc=disc,
            disc_rarity="S",
        )
        # 5 illegal crit_rate rolls dropped; only 3 legal rolls counted.
        assert result.rolls_used == 3

    def test_unknown_substat_not_counted(self, stub_dag):
        stub_dag(lambda _d: 1)
        disc = DiscCandidate(
            disc_id="d",
            slot=4,
            set_id=1,
            main_stat_type="atk_pct",
            substats=[
                {"stat": "crit_rate", "value": BASE_VALUES["crit_rate"]},
                {"stat": "crit_dmg", "value": BASE_VALUES["crit_dmg"]},
                {"stat": "pen_flat", "value": BASE_VALUES["pen_flat"]},
                {"stat": "mystery_stat", "value": 99999},
            ],
        )
        result = score_disc_potential(
            **_common_args(),
            disc=disc,
            disc_rarity="S",
        )
        assert result.rolls_used == 3


class TestMultinomialEnumerationFour:
    def test_distribution_probabilities_sum_to_one(self, stub_dag):
        """Multinomial PMF must integrate to 1 (no probability leaks)."""
        stub_dag(lambda _d: 100 + sum(_subs_to_map(_d).values()))
        result = score_disc_potential(
            **_common_args(),
            disc=_full_4sub_disc(),
            disc_rarity="S",
        )
        total_prob = sum(p for _, p in result.distribution)
        assert total_prob == pytest.approx(1.0)

    def test_max_improvement_matches_all_rolls_into_best_stat(self, stub_dag):
        """When CD has 2x per-roll value, the best case is all 5 rolls on CD."""

        def damage(disc):
            subs = _subs_to_map(disc)
            return 100 + 2 * subs.get("crit_dmg", 0) + subs.get("crit_rate", 0)

        stub_dag(damage)

        disc = _full_4sub_disc()
        result = score_disc_potential(
            **_common_args(),
            disc=disc,
            disc_rarity="S",
        )
        # current = 100 + 2*480 + 240 = 1300
        # best   = 100 + 2*480*6 + 240 = 6100 → +4800
        assert result.max_improvement == pytest.approx(4800)

    def test_mean_improvement_equals_expected_value_uniform_split(self, stub_dag):
        """Linear damage function → E[delta] = N * mean_per_roll over uniform 4."""

        def damage(disc):
            subs = _subs_to_map(disc)
            # Each substat contributes its raw value (in the disc's own units).
            return sum(subs.values())

        stub_dag(damage)

        disc = _full_4sub_disc()
        remaining = MAX_ROLLS_BY_RARITY["S"] - 4
        # Each roll is uniform over 4 stats. Expected per-roll delta:
        # (240 + 480 + 9 + 9) / 4 = 184.5
        expected_mean_per_roll = (
            BASE_VALUES["crit_rate"]
            + BASE_VALUES["crit_dmg"]
            + BASE_VALUES["anomaly_proficiency"]
            + BASE_VALUES["pen_flat"]
        ) / 4
        result = score_disc_potential(
            **_common_args(),
            disc=disc,
            disc_rarity="S",
        )
        assert result.mean_improvement == pytest.approx(
            remaining * expected_mean_per_roll,
        )

    def test_zero_remaining_yields_singleton_distribution(self, stub_dag):
        """A maxed disc has only one outcome: itself."""
        stub_dag(lambda _d: 1000)
        # 9 rolls: 4 initial + 5 stacked onto crit_dmg.
        disc = _full_4sub_disc()
        disc = DiscCandidate(
            **{
                **disc.__dict__,
                "substats": [
                    {"stat": "crit_rate", "value": BASE_VALUES["crit_rate"]},
                    {"stat": "crit_dmg", "value": BASE_VALUES["crit_dmg"] * 6},
                    {"stat": "anomaly_proficiency", "value": BASE_VALUES["anomaly_proficiency"]},
                    {"stat": "pen_flat", "value": BASE_VALUES["pen_flat"]},
                ],
            },
        )
        result = score_disc_potential(
            **_common_args(),
            disc=disc,
            disc_rarity="S",
        )
        assert result.remaining_rolls == 0
        assert len(result.distribution) == 1
        assert result.distribution[0] == (0.0, pytest.approx(1.0))
        assert result.max_improvement == 0.0
        assert result.mean_improvement == 0.0


class TestUnlockFourthSubstat:
    def test_3sub_disc_distribution_sums_to_one(self, stub_dag):
        """k=3 path branches over weighted 4th-substat picks; total prob = 1."""
        stub_dag(lambda _d: 100 + sum(_subs_to_map(_d).values()))
        result = score_disc_potential(
            **_common_args(),
            disc=_three_sub_disc(),
            disc_rarity="S",
        )
        total = sum(p for _, p in result.distribution)
        assert total == pytest.approx(1.0)

    def test_substat_weights_steer_4th_pick(self, stub_dag):
        """Heavily weighting one 4th-pick concentrates the PMF on it."""
        # Only allow CD as the 4th substat (zero weight elsewhere).
        biased_weights = {**dict.fromkeys(BASE_VALUES, 0), "crit_dmg": 1}
        # Existing 3 subs already include crit_dmg in our fixture, so use a
        # 3-sub disc whose substats DON'T include crit_dmg.
        disc = DiscCandidate(
            disc_id="d",
            slot=4,
            set_id=1,
            main_stat_type="atk_pct",
            substats=[
                {"stat": "crit_rate", "value": BASE_VALUES["crit_rate"]},
                {"stat": "anomaly_proficiency", "value": BASE_VALUES["anomaly_proficiency"]},
                {"stat": "pen_flat", "value": BASE_VALUES["pen_flat"]},
            ],
        )

        def damage(d):
            return 100 + _subs_to_map(d).get("crit_dmg", 0)

        stub_dag(damage)

        result = score_disc_potential(
            **_common_args(),
            disc=disc,
            disc_rarity="S",
            substat_weights=biased_weights,
        )
        # With CD as the only candidate, every outcome has CD=base + extras.
        # mean_improvement equals full-CD path's E[crit_dmg gain] = base_value
        # + remaining_rolls / 4 * base_value.
        # current damage with no CD: 100. After unlock: +480 minimum.
        assert result.mean_improvement >= BASE_VALUES["crit_dmg"]

    def test_3sub_disc_uses_one_more_total_roll_than_no_unlock_path(
        self,
        stub_dag,
    ):
        """A 3-sub S-rank places 8 substat rolls vs a 4-sub's 9.

        The unlock event itself counts as one of the disc's max rolls.
        """
        stub_dag(lambda _d: 1)
        result = score_disc_potential(
            **_common_args(),
            disc=_three_sub_disc(),
            disc_rarity="S",
        )
        # 3 initial rolls used; remaining = 9 - 3 = 6. The first of those
        # goes to unlocking the 4th substat; the other 5 are multinomial.
        assert result.rolls_used == 3
        assert result.remaining_rolls == MAX_ROLLS_BY_RARITY["S"] - 3


class TestSummaryStatistics:
    def test_max_is_largest_delta_in_pmf(self, stub_dag):
        stub_dag(lambda _d: 100 + _subs_to_map(_d).get("crit_dmg", 0))
        result = score_disc_potential(
            **_common_args(),
            disc=_full_4sub_disc(),
            disc_rarity="S",
        )
        assert result.max_improvement == max(d for d, _ in result.distribution)

    def test_mean_equals_probability_weighted_delta(self, stub_dag):
        stub_dag(lambda _d: 100 + _subs_to_map(_d).get("crit_dmg", 0))
        result = score_disc_potential(
            **_common_args(),
            disc=_full_4sub_disc(),
            disc_rarity="S",
        )
        manual_mean = sum(d * p for d, p in result.distribution)
        assert result.mean_improvement == pytest.approx(manual_mean)

    def test_stddev_is_sqrt_of_variance(self, stub_dag):
        stub_dag(lambda _d: 100 + _subs_to_map(_d).get("crit_dmg", 0))
        result = score_disc_potential(
            **_common_args(),
            disc=_full_4sub_disc(),
            disc_rarity="S",
        )
        mean = result.mean_improvement
        variance = sum(p * (d - mean) ** 2 for d, p in result.distribution)
        assert result.stddev_improvement == pytest.approx(variance**0.5)

    def test_constant_damage_yields_zero_spread(self, stub_dag):
        """Damage independent of substats → all outcomes equal → no variance."""
        stub_dag(lambda _d: 500)
        result = score_disc_potential(
            **_common_args(),
            disc=_full_4sub_disc(),
            disc_rarity="S",
        )
        assert result.max_improvement == 0
        assert result.mean_improvement == 0
        assert result.stddev_improvement == pytest.approx(0)
        assert result.p10 == 0
        assert result.p50 == 0
        assert result.p90 == 0

    def test_percentiles_ordered_low_to_high(self, stub_dag):
        """p10 ≤ p50 ≤ p90 always."""
        stub_dag(lambda _d: 100 + _subs_to_map(_d).get("crit_dmg", 0))
        result = score_disc_potential(
            **_common_args(),
            disc=_full_4sub_disc(),
            disc_rarity="S",
        )
        assert result.p10 <= result.p50 <= result.p90


class TestRarityVariants:
    def test_a_rank_disc_no_unlock_path(self, stub_dag):
        """A-rank stays at 3 substats forever — no 4th-substat unlock."""
        stub_dag(lambda _d: 100 + _subs_to_map(_d).get("crit_dmg", 0))
        a_base = SUBSTAT_BASE_PER_ROLL_BY_RARITY["A"]
        a_disc = DiscCandidate(
            disc_id="a",
            slot=4,
            set_id=1,
            main_stat_type="atk_pct",
            substats=[
                {"stat": "crit_rate", "value": a_base["crit_rate"]},
                {"stat": "crit_dmg", "value": a_base["crit_dmg"]},
                {"stat": "pen_flat", "value": a_base["pen_flat"]},
            ],
        )
        result = score_disc_potential(
            **_common_args(),
            disc=a_disc,
            disc_rarity="A",
        )
        # A-rank has 3 initial + 2 upgrades = 5 max, 2 remaining over k=3 subs.
        assert result.remaining_rolls == 2
        # Distribution probabilities still sum to 1.
        assert sum(p for _, p in result.distribution) == pytest.approx(1.0)


class TestBaselineDamageOverride:
    """``baseline_damage`` shifts what improvements are measured against."""

    def test_default_baseline_is_disc_as_is(self, stub_dag):
        """No override → improvements are vs the disc's own current damage."""
        stub_dag(lambda d: 100 + _subs_to_map(d).get("crit_dmg", 0))
        result = score_disc_potential(
            **_common_args(),
            disc=_full_4sub_disc(),
            disc_rarity="S",
        )
        # current_damage = 100 + 480 (one CD roll on the fixture).
        assert result.current_damage == pytest.approx(100 + BASE_VALUES["crit_dmg"])
        assert result.baseline_damage == result.current_damage
        # Smallest delta is zero (the no-CD-rolls outcome would be negative,
        # but every outcome on a 4-sub disc adds rolls so >= 0 is the floor).
        assert min(d for d, _ in result.distribution) >= 0

    def test_override_baseline_shifts_all_deltas_uniformly(self, stub_dag):
        """Different baseline → deltas shift by (default_baseline - new_baseline)."""
        stub_dag(lambda d: 100 + _subs_to_map(d).get("crit_dmg", 0))
        without = score_disc_potential(
            **_common_args(),
            disc=_full_4sub_disc(),
            disc_rarity="S",
        )
        external_baseline = 50.0  # lower than current_damage of 580
        with_override = score_disc_potential(
            **_common_args(),
            disc=_full_4sub_disc(),
            disc_rarity="S",
            baseline_damage=external_baseline,
        )
        # PMF shape unchanged; just shifted by (current - external_baseline).
        shift = without.current_damage - external_baseline
        assert with_override.baseline_damage == pytest.approx(external_baseline)
        assert with_override.mean_improvement == pytest.approx(
            without.mean_improvement + shift,
        )
        assert with_override.max_improvement == pytest.approx(
            without.max_improvement + shift,
        )
        # Probabilities preserved on a per-outcome basis.
        without_probs = sorted(p for _, p in without.distribution)
        with_probs = sorted(p for _, p in with_override.distribution)
        assert without_probs == pytest.approx(with_probs)

    def test_override_can_produce_negative_improvements(self, stub_dag):
        """A worse candidate disc compared to a strong current build → negative deltas."""
        stub_dag(lambda d: 100 + _subs_to_map(d).get("crit_dmg", 0))
        # Pretend the current build's slot disc deals 10000 — way better than
        # anything this candidate can do at max level.
        result = score_disc_potential(
            **_common_args(),
            disc=_full_4sub_disc(),
            disc_rarity="S",
            baseline_damage=10000.0,
        )
        assert result.mean_improvement < 0
        assert result.max_improvement < 0


class TestRarityVariantsContinued:
    def test_b_rank_no_remaining_rolls(self, stub_dag):
        """B-rank caps at 3 rolls — no upgrade rolls ever."""
        stub_dag(lambda _d: 1)
        b_base = SUBSTAT_BASE_PER_ROLL_BY_RARITY["B"]
        b_disc = DiscCandidate(
            disc_id="b",
            slot=4,
            set_id=1,
            main_stat_type="atk_pct",
            substats=[
                {"stat": "crit_rate", "value": b_base["crit_rate"]},
                {"stat": "crit_dmg", "value": b_base["crit_dmg"]},
                {"stat": "pen_flat", "value": b_base["pen_flat"]},
            ],
        )
        result = score_disc_potential(
            **_common_args(),
            disc=b_disc,
            disc_rarity="B",
        )
        assert result.remaining_rolls == 0
        assert result.max_improvement == 0
        assert len(result.distribution) == 1


class TestMultiplexedScoring:
    def test_multiplexed_scoring_selects_correct_am_index(self, monkeypatch):
        """dict sentinel routes S6-AM candidate to the high-AM log; no-AM to the base log."""
        # base_agent_am=100; S6-AM disc adds 60 → coarse_am 160
        # AM=100 → step with multiplier 1000; AM=160 → step with multiplier 2000
        _step = lambda mult: [  # noqa: E731
            ComboStep(
                label="BA",
                attack_id="a1",
                attack_name="A",
                scope=AttackScope.BASIC,
                multiplier=mult,
                element="fire",
            )
        ]
        step_sets = {100: _step(1000), 160: _step(2000)}

        def fake_context(**kwargs):
            class FakeCtx:
                pass

            ctx = FakeCtx()
            ctx.multiplier = kwargs.get("multiplier", 1000)
            return ctx

        def fake_overlay(ctx, disc):
            mult = getattr(ctx, "multiplier", 1000)
            return float(mult)

        monkeypatch.setattr(
            "app.services.disc_scorer.build_damage_step_context",
            fake_context,
        )
        monkeypatch.setattr(
            "app.services.disc_scorer.compute_damage_with_accumulated_disc",
            fake_overlay,
        )

        class MockDisc:
            def __init__(self, slot, set_id, main_stat_type, main_stat_value=0):
                class MockSet:
                    def __init__(self, hid):
                        self.hakushin_id = hid

                self.slot = slot
                self.set_hakushin_id = set_id
                self.disc_set = MockSet(set_id)
                self.main_stat_type = main_stat_type
                self.main_stat_value = main_stat_value

        # base_agent_am=100, no S6 AM → coarse_am=100 → step multiplier 1000
        discs_base = [MockDisc(i, 1, "atk" if i == 6 else "hp") for i in range(1, 7)]
        # FB 2pc, no S6 AM → still coarse_am=100 (FB is AP, not AM)
        discs_fb_only = [
            MockDisc(i, 31300 if i in (5, 6) else 1, "atk" if i == 6 else "hp")
            for i in range(1, 7)
        ]
        # S6 AM with main_stat_value=60 → coarse_am=160 → step multiplier 2000
        discs_s6 = [
            MockDisc(i, 1, "anomaly_mastery" if i == 6 else "hp", 60 if i == 6 else 0)
            for i in range(1, 7)
        ]
        # FB 2pc + S6 AM → still coarse_am=160 (FB adds no AM axis)
        discs_fb_s6 = [
            MockDisc(
                i,
                31300 if i in (5, 6) else 1,
                "anomaly_mastery" if i == 6 else "hp",
                60 if i == 6 else 0,
            )
            for i in range(1, 7)
        ]

        candidate = DiscCandidate(
            disc_id="d",
            slot=4,
            set_id=1,
            main_stat_type="crit_rate",
            substats=[
                {"stat": "crit_rate", "value": BASE_VALUES["crit_rate"]},
                {"stat": "crit_dmg", "value": BASE_VALUES["crit_dmg"]},
                {"stat": "anomaly_proficiency", "value": BASE_VALUES["anomaly_proficiency"]},
                {"stat": "pen_flat", "value": BASE_VALUES["pen_flat"]},
            ],
        )

        base_args = {k: v for k, v in _common_args().items() if k != "combo_steps"}
        base_args["base_build"] = BuildSnapshot(agent_anomaly_mastery=100)

        def score(discs):
            return score_disc_potential(
                **base_args,
                combo_steps=step_sets,
                disc=candidate,
                disc_rarity="S",
                build_discs=discs,
            )

        res_base = score(discs_base)
        res_fb_only = score(discs_fb_only)
        res_s6 = score(discs_s6)
        res_fb_s6 = score(discs_fb_s6)

        # Base and FB-only both coarse_am=100 → multiplier 1000
        assert res_base.current_damage == pytest.approx(1000.0)
        assert res_fb_only.current_damage == pytest.approx(1000.0), (
            "FB-only should map to coarse_am=100, same as base — FB gives AP not AM"
        )
        # S6 AM and FB+S6 AM both coarse_am=160 → multiplier 2000
        assert res_s6.current_damage == pytest.approx(2000.0)
        assert res_fb_s6.current_damage == pytest.approx(2000.0), (
            "FB+S6 AM should map to coarse_am=160, same as S6 AM alone — FB adds no axis"
        )

    def test_slot6_am_vs_non_am_candidate_select_different_logs(self, monkeypatch):
        """A slot-6-AM candidate and a non-AM candidate pick different event logs."""
        _step = lambda mult: [  # noqa: E731
            ComboStep(
                label="BA",
                attack_id="a1",
                attack_name="A",
                scope=AttackScope.BASIC,
                multiplier=mult,
                element="fire",
            )
        ]
        step_sets = {100: _step(1000), 160: _step(2000)}

        def fake_context(**kwargs):
            class FakeCtx:
                pass

            ctx = FakeCtx()
            ctx.multiplier = kwargs.get("multiplier", 1000)
            return ctx

        monkeypatch.setattr(
            "app.services.disc_scorer.build_damage_step_context",
            fake_context,
        )
        monkeypatch.setattr(
            "app.services.disc_scorer.compute_damage_with_accumulated_disc",
            lambda ctx, _: float(getattr(ctx, "multiplier", 1000)),
        )

        _s4subs = [
            {"stat": "crit_rate", "value": BASE_VALUES["crit_rate"]},
            {"stat": "crit_dmg", "value": BASE_VALUES["crit_dmg"]},
            {"stat": "anomaly_proficiency", "value": BASE_VALUES["anomaly_proficiency"]},
            {"stat": "pen_flat", "value": BASE_VALUES["pen_flat"]},
        ]
        non_am_candidate = DiscCandidate(
            disc_id="d_non_am",
            slot=6,
            set_id=1,
            main_stat_type="atk_pct",
            main_stat_value=0,
            substats=_s4subs,
        )
        am_candidate = DiscCandidate(
            disc_id="d_am",
            slot=6,
            set_id=1,
            main_stat_type="anomaly_mastery",
            main_stat_value=60,
            substats=_s4subs,
        )

        base_build = BuildSnapshot(agent_anomaly_mastery=100)
        base_args = {k: v for k, v in _common_args().items() if k != "combo_steps"}
        base_args["base_build"] = base_build

        res_non_am = score_disc_potential(
            **base_args,
            combo_steps=step_sets,
            disc=non_am_candidate,
            disc_rarity="S",
        )
        res_am = score_disc_potential(
            **base_args,
            combo_steps=step_sets,
            disc=am_candidate,
            disc_rarity="S",
        )

        assert res_non_am.current_damage == pytest.approx(1000.0), (
            "non-AM candidate should use AM=100 log"
        )
        assert res_am.current_damage == pytest.approx(2000.0), "AM candidate should use AM=160 log"
