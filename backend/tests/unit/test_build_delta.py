"""Tests for the B4 delta decomposition (DESIGN_explainability.md §3.2).

Fixtures are hand-constructed (not driven through the real damage
calculator) so ``from_total``/``to_total`` can be defined as the *exact*
floor-consistent reconstruction of the given zone bp values — this proves
the decomposition math itself (log-space additivity, telescoping product)
bit-exactly, independent of whether real calculator output ever produces
zero-remainder divisions.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from app.services.build_delta import CANONICAL_ZONE_ORDER, compute_build_delta


def _step(zone_bp: dict[str, int]):
    """A minimal duck-typed stand-in for a StepResult with attribution."""
    return SimpleNamespace(
        attribution=SimpleNamespace(
            zone_formulas={z: SimpleNamespace(result_bp=v) for z, v in zone_bp.items()}
        )
    )


def _reconstruct_total(zone_bp: dict[str, int]) -> int:
    """Exact floor-consistent total from zone bp values (mirrors
    damage_calculator.py's own multiplicative chain order)."""
    total = zone_bp["base"]
    for zone in CANONICAL_ZONE_ORDER[1:]:
        if zone in zone_bp:
            total = total * zone_bp[zone] // 10000
    return total


_BASELINE = {
    "base": 1_000_000,
    "boost": 12_000,
    "crit": 15_000,
    "def": 10_000,
    "res": 8_000,
    "vulnerability": 10_000,
    "stun": 10_000,
}


class TestSingleZoneChange:
    """Only "crit" moves — proves the simple single-step case exactly."""

    def setup_method(self):
        self.from_bp = dict(_BASELINE)
        self.to_bp = {**_BASELINE, "crit": 17_000}
        self.from_total = _reconstruct_total(self.from_bp)
        self.to_total = _reconstruct_total(self.to_bp)
        self.delta = compute_build_delta(
            [_step(self.from_bp)],
            [_step(self.to_bp)],
            from_total=self.from_total,
            to_total=self.to_total,
        )

    def test_from_to_total_passed_through(self):
        assert self.delta.from_total == self.from_total
        assert self.delta.to_total == self.to_total

    def test_unmoved_zones_have_ratio_one_and_zero_share(self):
        by_zone = {z.zone: z for z in self.delta.zone_deltas}
        for zone in ("base", "boost", "def", "res", "vulnerability", "stun"):
            assert by_zone[zone].ratio == 1.0
            assert by_zone[zone].gain_share_pct == 0.0

    def test_moved_zone_carries_the_entire_share(self):
        by_zone = {z.zone: z for z in self.delta.zone_deltas}
        assert by_zone["crit"].from_bp == 15_000
        assert by_zone["crit"].to_bp == 17_000
        assert by_zone["crit"].ratio == pytest.approx(17_000 / 15_000)
        assert by_zone["crit"].gain_share_pct == pytest.approx(100.0)

    def test_gain_share_sums_to_100_pct(self):
        assert sum(z.gain_share_pct for z in self.delta.zone_deltas) == pytest.approx(100.0)

    def test_ratios_telescope_exactly_to_total_ratio(self):
        product = math.prod(z.ratio for z in self.delta.zone_deltas)
        assert self.delta.from_total * product == pytest.approx(self.delta.to_total)


class TestMultiZoneChange:
    """ATK (base) and crit both move — several zones share the gain."""

    def setup_method(self):
        self.from_bp = dict(_BASELINE)
        self.to_bp = {**_BASELINE, "base": 1_100_000, "crit": 16_500, "res": 8_500}
        self.from_total = _reconstruct_total(self.from_bp)
        self.to_total = _reconstruct_total(self.to_bp)
        self.delta = compute_build_delta(
            [_step(self.from_bp)],
            [_step(self.to_bp)],
            from_total=self.from_total,
            to_total=self.to_total,
        )

    def test_gain_share_sums_to_100_pct(self):
        assert sum(z.gain_share_pct for z in self.delta.zone_deltas) == pytest.approx(100.0)

    def test_ratios_telescope_exactly_to_total_ratio(self):
        product = math.prod(z.ratio for z in self.delta.zone_deltas)
        assert self.delta.from_total * product == pytest.approx(self.delta.to_total)

    def test_pct_change_matches_totals(self):
        expected = (self.to_total - self.from_total) / self.from_total * 100
        assert self.delta.pct_change == pytest.approx(expected)


class TestMultiStepAggregatesBase:
    """Two damage steps: the "base" zone sums across them; other zones are
    shared (constant across steps of the same build/run, per scope note)."""

    def setup_method(self):
        self.from_steps = [
            _step({**_BASELINE, "base": 500_000}),
            _step({**_BASELINE, "base": 300_000}),
        ]
        self.to_steps = [
            _step({**_BASELINE, "base": 550_000, "crit": 16_000}),
            _step({**_BASELINE, "base": 330_000, "crit": 16_000}),
        ]
        self.from_total = _reconstruct_total({**_BASELINE, "base": 800_000})
        self.to_total = _reconstruct_total({**_BASELINE, "base": 880_000, "crit": 16_000})
        self.delta = compute_build_delta(
            self.from_steps,
            self.to_steps,
            from_total=self.from_total,
            to_total=self.to_total,
        )

    def test_base_zone_is_summed_across_steps(self):
        by_zone = {z.zone: z for z in self.delta.zone_deltas}
        assert by_zone["base"].from_bp == 800_000
        assert by_zone["base"].to_bp == 880_000

    def test_gain_share_sums_to_100_pct(self):
        assert sum(z.gain_share_pct for z in self.delta.zone_deltas) == pytest.approx(100.0)

    def test_ratios_telescope_exactly_to_total_ratio(self):
        product = math.prod(z.ratio for z in self.delta.zone_deltas)
        assert self.delta.from_total * product == pytest.approx(self.delta.to_total)


class TestNoChange:
    """Identical from/to — every zone unmoved, no divide-by-zero on log(1)."""

    def test_all_ratios_one_all_shares_zero(self):
        bp = dict(_BASELINE)
        total = _reconstruct_total(bp)
        delta = compute_build_delta(
            [_step(bp)], [_step(bp)], from_total=total, to_total=total
        )
        assert delta.pct_change == 0.0
        for z in delta.zone_deltas:
            assert z.ratio == 1.0
            assert z.gain_share_pct == 0.0


class TestAnomalyAndSheerZonesIncluded:
    """Zones outside the standard set (anomaly_prof/sheer_boost) participate
    like any other zone when present."""

    def test_anomaly_prof_zone_change_is_attributed(self):
        base = {
            "base": 1_000_000,
            "boost": 12_000,
            "def": 10_000,
            "res": 8_000,
            "vulnerability": 10_000,
            "stun": 10_000,
            "anomaly_prof": 12_000,
            "anomaly_level": 10_000,
            "anomaly_boost": 10_000,
        }
        to_bp = {**base, "anomaly_prof": 15_000}
        from_total = _reconstruct_total(base)
        to_total = _reconstruct_total(to_bp)
        delta = compute_build_delta(
            [_step(base)], [_step(to_bp)], from_total=from_total, to_total=to_total
        )
        by_zone = {z.zone: z for z in delta.zone_deltas}
        assert "crit" not in by_zone
        assert by_zone["anomaly_prof"].gain_share_pct == pytest.approx(100.0)
        assert sum(z.gain_share_pct for z in delta.zone_deltas) == pytest.approx(100.0)


class TestIsExact:
    """``is_exact`` flags whether the log-space decomposition factorises
    cleanly (every non-base zone constant across steps) or is approximate."""

    def test_single_step_runs_are_exact(self):
        from_bp = dict(_BASELINE)
        to_bp = {**_BASELINE, "crit": 17_000}
        delta = compute_build_delta(
            [_step(from_bp)],
            [_step(to_bp)],
            from_total=_reconstruct_total(from_bp),
            to_total=_reconstruct_total(to_bp),
        )
        assert delta.is_exact is True

    def test_multi_step_same_zones_are_exact(self):
        # Two steps that share identical non-base zone values (only base
        # differs per move) still factorise exactly.
        s1 = {**_BASELINE, "base": 1_000_000}
        s2 = {**_BASELINE, "base": 500_000}
        from_total = _reconstruct_total(s1) + _reconstruct_total(s2)
        to1 = {**s1, "crit": 17_000}
        to2 = {**s2, "crit": 17_000}
        to_total = _reconstruct_total(to1) + _reconstruct_total(to2)
        delta = compute_build_delta(
            [_step(s1), _step(s2)],
            [_step(to1), _step(to2)],
            from_total=from_total,
            to_total=to_total,
        )
        assert delta.is_exact is True

    def test_zone_varying_across_steps_is_not_exact(self):
        # Second step has a stun window (stun=15000) the first lacks — the
        # stun zone varies across steps, so the decomposition is approximate.
        s1 = {**_BASELINE, "base": 1_000_000, "stun": 10_000}
        s2 = {**_BASELINE, "base": 800_000, "stun": 15_000}
        from_total = _reconstruct_total(s1) + _reconstruct_total(s2)
        delta = compute_build_delta(
            [_step(s1), _step(s2)],
            [_step(s1), _step(s2)],
            from_total=from_total,
            to_total=from_total,
        )
        assert delta.is_exact is False

    def test_zone_present_on_only_some_steps_is_not_exact(self):
        # A standard step (no anomaly_prof) mixed with an anomaly step
        # (anomaly_prof present) — the missing-vs-present zone counts as
        # varying, so not exact.
        std = {**_BASELINE, "base": 1_000_000}
        anom = {
            "base": 900_000,
            "boost": 12_000,
            "def": 10_000,
            "res": 8_000,
            "vulnerability": 10_000,
            "stun": 10_000,
            "anomaly_prof": 12_000,
            "anomaly_level": 10_000,
            "anomaly_boost": 10_000,
        }
        total = _reconstruct_total(std) + _reconstruct_total(anom)
        delta = compute_build_delta(
            [_step(std), _step(anom)],
            [_step(std), _step(anom)],
            from_total=total,
            to_total=total,
        )
        assert delta.is_exact is False
