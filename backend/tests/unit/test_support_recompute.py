"""Unit tests for ORM-free support recompute kit (Phase 3 — R3.13).

Verifies that recompute_set_counts and recompute_total_hp produce values
identical to _count_disc_sets / _support_total_hp on an equivalent ORM mock.
Also verifies pickle round-trip for process-pool safety.
"""

from __future__ import annotations

import pickle
from types import SimpleNamespace

import pytest

from app.services.modifiers import (
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.rank_pipeline import PlainBuildDisc
from app.services.snapshot_builder import _count_disc_sets, _support_total_hp
from app.services.support_recompute import (
    SupportRecomputeKit,
    build_support_recompute_kit,
    recompute_set_counts,
    recompute_total_hp,
)


def _orm_disc(
    slot: int,
    set_id: int,
    main_stat_type: str = "atk",
    main_stat_value: int = 0,
    substats: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        slot=SimpleNamespace(value=slot),
        main_stat_type=SimpleNamespace(value=main_stat_type),
        main_stat_value=main_stat_value,
        substats=substats or [],
        disc_set=SimpleNamespace(hakushin_id=set_id),
    )


def _mock_build(
    discs: list,
    *,
    base_hp: int = 10000,
    agent_level: int = 60,
    w_engine: object = None,
) -> SimpleNamespace:
    agent = SimpleNamespace(
        hakushin_id=0,
        name="TestAgent",
        specialty=SimpleNamespace(value="support"),
        element=SimpleNamespace(value="electric"),
        base_hp=base_hp,
        hp_growth=0,
        promotion_stats=None,
        core_stats=None,
        base_atk=800,
        atk_growth=0,
        base_def=500,
        def_growth=0,
    )
    return SimpleNamespace(
        agent=agent,
        agent_level=agent_level,
        core_skill_level=None,
        mindscape_level=0,
        disabled_buffs=[],
        discs=discs,
        w_engine=w_engine,
        w_engine_refinement=1,
        w_engine_level=60,
    )


def _plain_disc(
    slot: int,
    set_id: int,
    main_stat_type: str = "atk",
    main_stat_value: int = 0,
    substats: list | None = None,
) -> PlainBuildDisc:
    return PlainBuildDisc(
        slot=slot,
        main_stat_type=main_stat_type,
        main_stat_value=main_stat_value,
        substats=substats or [],
        set_hakushin_id=set_id,
    )


@pytest.fixture
def standard_orm_discs():
    """6-disc loadout: 4x set 100 (4pc), 2x set 200 (2pc). Slot 1 has flat HP."""
    return [
        _orm_disc(1, 100, "hp", 2000),
        _orm_disc(2, 100, "atk_pct", 1000),
        _orm_disc(3, 100, "def_pct", 1600),
        _orm_disc(4, 100, "crit_rate", 800),
        _orm_disc(5, 200, "hp_pct", 3000),
        _orm_disc(6, 200, "atk_pct", 1000),
    ]


@pytest.fixture
def standard_plain_discs():
    """PlainBuildDisc equivalents of standard_orm_discs."""
    return [
        _plain_disc(1, 100, "hp", 2000),
        _plain_disc(2, 100, "atk_pct", 1000),
        _plain_disc(3, 100, "def_pct", 1600),
        _plain_disc(4, 100, "crit_rate", 800),
        _plain_disc(5, 200, "hp_pct", 3000),
        _plain_disc(6, 200, "atk_pct", 1000),
    ]


class TestRecomputeSetCounts:
    def test_matches_orm_count_disc_sets(self, standard_orm_discs, standard_plain_discs):
        orm_counts = _count_disc_sets(standard_orm_discs)
        plain_counts = recompute_set_counts(standard_plain_discs)
        assert plain_counts == orm_counts

    def test_empty_loadout(self):
        assert recompute_set_counts([]) == {}

    def test_six_different_sets(self):
        discs = [_plain_disc(i, i * 100) for i in range(1, 7)]
        counts = recompute_set_counts(discs)
        assert all(v == 1 for v in counts.values())
        assert len(counts) == 6

    def test_all_same_set(self):
        discs = [_plain_disc(i, 100) for i in range(1, 7)]
        assert recompute_set_counts(discs) == {100: 6}


class TestRecomputeTotalHp:
    def test_matches_support_total_hp_no_wengine(self, standard_orm_discs, standard_plain_discs):
        mock_build = _mock_build(standard_orm_discs)
        kit = build_support_recompute_kit(mock_build, standard_plain_discs)

        expected = _support_total_hp(mock_build)
        result = recompute_total_hp(kit, standard_plain_discs)

        assert result == expected

    def test_flat_hp_from_disc_is_added(self):
        """Flat HP disc main stat reaches total HP."""
        discs = [_plain_disc(1, 100, "hp", 5000)]
        kit = SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={},
            build_discs=discs,
        )
        # initial_hp = 10000 * 1.0 + 5000 = 15000; combat factor = 1.0
        assert recompute_total_hp(kit, discs) == 15000

    def test_hp_pct_from_disc_multiplies_base(self):
        """HP% disc main stat scales agent base HP."""
        discs = [_plain_disc(5, 200, "hp_pct", 3000)]
        kit = SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={},
            build_discs=discs,
        )
        # initial_hp = int(10000 * 1.3 + 0) = 13000
        assert recompute_total_hp(kit, discs) == 13000

    def test_changed_disc_loadout_changes_hp(self, standard_plain_discs):
        """Swapping the HP disc changes the total."""
        kit = SupportRecomputeKit(
            agent_base_hp=10000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={},
            build_discs=standard_plain_discs,
        )
        base_hp = recompute_total_hp(kit, standard_plain_discs)

        swapped = [_plain_disc(1, 100, "atk", 500), *standard_plain_discs[1:]]
        swapped_hp = recompute_total_hp(kit, swapped)

        assert swapped_hp < base_hp


class TestPickleRoundTrip:
    def test_kit_survives_pickle(self, standard_plain_discs):
        mod = Modifier(
            stat="hp_pct",
            value=1000,
            source=ModifierSource.DISC_SET_2PC,
            source_label="2pc bonus",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
            max_stacks=1,
        )
        kit = SupportRecomputeKit(
            agent_base_hp=44300,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={100: [mod], 200: []},
            build_discs=standard_plain_discs,
        )
        restored: SupportRecomputeKit = pickle.loads(pickle.dumps(kit))

        assert restored.agent_base_hp == kit.agent_base_hp
        assert restored.disc_set_modifiers.keys() == kit.disc_set_modifiers.keys()
        assert len(restored.build_discs) == len(kit.build_discs)
        assert recompute_total_hp(restored, restored.build_discs) == recompute_total_hp(
            kit, kit.build_discs
        )

    def test_builder_output_pickles(self, standard_orm_discs, standard_plain_discs):
        mock_build = _mock_build(standard_orm_discs)
        kit = build_support_recompute_kit(mock_build, standard_plain_discs)
        restored = pickle.loads(pickle.dumps(kit))
        assert restored.agent_base_hp == kit.agent_base_hp
