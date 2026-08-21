"""Unit tests for am_variants — resolve_coarse_am and build_am_2pc_sets."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.am_variants import (
    build_am_2pc_sets,
    resolve_coarse_am,
    resolve_coarse_am_from_counts,
)
from app.services.modifiers import Condition, Modifier, ModifierSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mod_2pc_flat(stat: str = "anomaly_mastery", value: int = 60) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.DISC_SET_2PC,
        source_label="2pc: AM flat",
        conditions=(Condition.ALWAYS,),
    )


def _mod_2pc_pct(value: int = 800) -> Modifier:
    return Modifier(
        stat="anomaly_mastery_pct",
        value=value,
        source=ModifierSource.DISC_SET_2PC,
        source_label="2pc: AM%",
        conditions=(Condition.ALWAYS,),
    )


def _mod_4pc_am(value: int = 60) -> Modifier:
    return Modifier(
        stat="anomaly_mastery",
        value=value,
        source=ModifierSource.DISC_SET_4PC,
        source_label="4pc: AM",
        conditions=(Condition.ALWAYS,),
    )


def _mod_2pc_non_am(stat: str = "anomaly_proficiency_flat", value: int = 30) -> Modifier:
    """Freedom Blues / similar AP-granting 2pc — must NOT count as AM."""
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.DISC_SET_2PC,
        source_label="2pc: AP",
        conditions=(Condition.ALWAYS,),
    )


@dataclass
class _Disc:
    """DiscCandidate-shaped stub (uses .set_id)."""

    slot: int
    main_stat_type: str
    main_stat_value: int
    set_id: int


@dataclass
class _PlainDisc:
    """PlainBuildDisc-shaped stub (uses .set_hakushin_id, not .set_id)."""

    slot: int
    main_stat_type: str
    main_stat_value: int
    set_hakushin_id: int


# ---------------------------------------------------------------------------
# build_am_2pc_sets
# ---------------------------------------------------------------------------


class TestBuildAm2PcSets:
    def test_pct_2pc_included(self):
        result = build_am_2pc_sets({33000: [_mod_2pc_pct(800)]})
        assert 33000 in result
        assert result[33000][0].stat == "anomaly_mastery_pct"

    def test_flat_2pc_included(self):
        result = build_am_2pc_sets({99: [_mod_2pc_flat("anomaly_mastery", 60)]})
        assert 99 in result

    def test_4pc_am_excluded(self):
        result = build_am_2pc_sets({99: [_mod_4pc_am(60)]})
        assert 99 not in result

    def test_non_am_2pc_excluded(self):
        """Freedom Blues 2pc (AP) must not appear in AM sets."""
        result = build_am_2pc_sets({12345: [_mod_2pc_non_am()]})
        assert 12345 not in result

    def test_empty_returns_empty(self):
        assert build_am_2pc_sets({}) == {}

    def test_mixed_set_only_2pc_am_returned(self):
        mods = {
            33000: [_mod_2pc_pct(800), _mod_4pc_am(300)],  # only pct survives
            12345: [_mod_2pc_non_am()],
        }
        result = build_am_2pc_sets(mods)
        assert 33000 in result
        assert 12345 not in result
        assert len(result[33000]) == 1  # 4pc excluded


# ---------------------------------------------------------------------------
# resolve_coarse_am
# ---------------------------------------------------------------------------


class TestResolveCoarseAm:
    def test_no_am_sources_returns_base(self):
        discs = [_Disc(slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_id=100)]
        assert resolve_coarse_am(114, discs, {}) == 114

    def test_slot6_am_main_adds_main_stat_value(self):
        discs = [_Disc(slot=6, main_stat_type="anomaly_mastery", main_stat_value=9200, set_id=100)]
        assert resolve_coarse_am(100, discs, {}) == 9300  # 100 + 9200

    def test_slot6_non_am_main_does_not_add(self):
        discs = [_Disc(slot=6, main_stat_type="atk_pct", main_stat_value=3000, set_id=100)]
        assert resolve_coarse_am(100, discs, {}) == 100

    def test_2pc_flat_from_two_locked(self):
        am_sets = build_am_2pc_sets({33000: [_mod_2pc_flat("anomaly_mastery", 60)]})
        discs = [
            _Disc(slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_id=33000),
            _Disc(slot=2, main_stat_type="atk", main_stat_value=316, set_id=33000),
        ]
        assert resolve_coarse_am(100, discs, am_sets) == 160  # 100 + 60

    def test_phaethons_melody_2pc_pct_formula(self):
        """Phaethon's Melody 2pc: +8% (800 bp) applies to base agent AM only."""
        am_sets = {33000: [_mod_2pc_pct(800)]}
        discs = [
            _Disc(slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_id=33000),
            _Disc(slot=2, main_stat_type="atk", main_stat_value=316, set_id=33000),
        ]
        # floor(100 * 10800 / 10000) = 108; no slot-6 AM → 108 total
        assert resolve_coarse_am(100, discs, am_sets) == 108

    def test_2pc_active_from_one_locked_plus_candidate(self):
        """1 locked + candidate in same discs list → 2pc active."""
        am_sets = build_am_2pc_sets({33000: [_mod_2pc_flat("anomaly_mastery", 60)]})
        discs = [
            _Disc(slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_id=33000),
            _Disc(slot=6, main_stat_type="atk_pct", main_stat_value=3000, set_id=33000),
        ]
        assert resolve_coarse_am(100, discs, am_sets) == 160

    def test_two_locked_of_am_set_regardless_of_candidate(self):
        """2 locked already → 2pc active even if candidate is a different set."""
        am_sets = build_am_2pc_sets({33000: [_mod_2pc_flat("anomaly_mastery", 60)]})
        discs = [
            _Disc(slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_id=33000),
            _Disc(slot=2, main_stat_type="atk", main_stat_value=316, set_id=33000),
            _Disc(slot=6, main_stat_type="atk_pct", main_stat_value=3000, set_id=99999),
        ]
        assert resolve_coarse_am(100, discs, am_sets) == 160

    def test_2pc_not_active_with_one_disc(self):
        am_sets = build_am_2pc_sets({33000: [_mod_2pc_flat("anomaly_mastery", 60)]})
        discs = [_Disc(slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_id=33000)]
        assert resolve_coarse_am(100, discs, am_sets) == 100

    def test_two_am_sets_sum(self):
        am_sets = {
            33000: [_mod_2pc_flat("anomaly_mastery", 60)],
            44000: [_mod_2pc_flat("anomaly_mastery", 30)],
        }
        discs = [
            _Disc(slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_id=33000),
            _Disc(slot=2, main_stat_type="atk", main_stat_value=316, set_id=33000),
            _Disc(slot=3, main_stat_type="def", main_stat_value=184, set_id=44000),
            _Disc(slot=4, main_stat_type="atk_pct", main_stat_value=3000, set_id=44000),
        ]
        assert resolve_coarse_am(100, discs, am_sets) == 190  # 100 + 60 + 30

    def test_non_am_set_adds_zero(self):
        """Freedom Blues (AP 2pc) produces empty am_2pc_sets → no contribution."""
        am_sets = build_am_2pc_sets({12345: [_mod_2pc_non_am()]})  # filtered out
        discs = [
            _Disc(slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_id=12345),
            _Disc(slot=2, main_stat_type="atk", main_stat_value=316, set_id=12345),
        ]
        assert resolve_coarse_am(100, discs, am_sets) == 100

    def test_plainbuilddisc_set_hakushin_id_attribute(self):
        """PlainBuildDisc uses set_hakushin_id — helper must handle both attr names."""
        am_sets = {33000: [_mod_2pc_pct(800)]}
        discs = [
            _PlainDisc(
                slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_hakushin_id=33000
            ),
            _PlainDisc(slot=2, main_stat_type="atk", main_stat_value=316, set_hakushin_id=33000),
        ]
        assert resolve_coarse_am(100, discs, am_sets) == 108  # floor(100 * 10800 / 10000)

    def test_slot6_am_plus_pct_set_combined(self):
        """Slot-6 AM main + Phaethon's 2pc: flat part adds after pct on base."""
        am_sets = {33000: [_mod_2pc_pct(800)]}
        discs = [
            _Disc(slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_id=33000),
            _Disc(slot=2, main_stat_type="atk", main_stat_value=316, set_id=33000),
            _Disc(slot=6, main_stat_type="anomaly_mastery", main_stat_value=9200, set_id=99),
        ]
        # floor(100 * 10800 / 10000) + 9200 = 108 + 9200 = 9308
        assert resolve_coarse_am(100, discs, am_sets) == 9308


# ---------------------------------------------------------------------------
# resolve_coarse_am_from_counts — equivalence with resolve_coarse_am
# ---------------------------------------------------------------------------


class TestResolveCoarseAmFromCounts:
    """Verify the count-based variant produces identical results to resolve_coarse_am."""

    def test_no_am_sources(self):
        discs = [_Disc(slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_id=100)]
        set_counts = {100: 1}
        expected = resolve_coarse_am(114, discs, {})
        assert resolve_coarse_am_from_counts(114, 0, set_counts, {}) == expected

    def test_slot6_am_main_on(self):
        discs = [_Disc(slot=6, main_stat_type="anomaly_mastery", main_stat_value=9200, set_id=100)]
        set_counts = {100: 1}
        am_sets: dict = {}
        expected = resolve_coarse_am(100, discs, am_sets)
        assert resolve_coarse_am_from_counts(100, 9200, set_counts, am_sets) == expected

    def test_am_2pc_set_active(self):
        am_sets = build_am_2pc_sets({33000: [_mod_2pc_flat("anomaly_mastery", 60)]})
        discs = [
            _Disc(slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_id=33000),
            _Disc(slot=2, main_stat_type="atk", main_stat_value=316, set_id=33000),
            _Disc(slot=6, main_stat_type="atk_pct", main_stat_value=3000, set_id=99),
        ]
        set_counts = {33000: 2, 99: 1}
        expected = resolve_coarse_am(100, discs, am_sets)
        assert resolve_coarse_am_from_counts(100, 0, set_counts, am_sets) == expected

    def test_slot6_am_plus_2pc_set(self):
        am_sets = {33000: [_mod_2pc_pct(800)]}
        discs = [
            _Disc(slot=1, main_stat_type="hp_pct", main_stat_value=3000, set_id=33000),
            _Disc(slot=2, main_stat_type="atk", main_stat_value=316, set_id=33000),
            _Disc(slot=6, main_stat_type="anomaly_mastery", main_stat_value=9200, set_id=99),
        ]
        set_counts = {33000: 2, 99: 1}
        expected = resolve_coarse_am(100, discs, am_sets)
        assert resolve_coarse_am_from_counts(100, 9200, set_counts, am_sets) == expected
