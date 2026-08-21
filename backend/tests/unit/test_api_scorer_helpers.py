"""Unit tests for pure helpers in the scorer endpoint (Phase 7b).

The endpoint itself is a thin controller. The interesting logic lives
in the helpers that translate between ORM shapes and the scorer's value
objects — building the hypothetical "5 other discs + target" base
snapshot, counting set pieces across that hypothetical inventory, and
filtering 2pc/4pc set modifiers.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.scorer import (
    _resolve_crit_mode,
    _result_to_schema,
)
from app.services.build_damage_service import BuildSnapshot
from app.services.damage_calculator import CritMode
from app.services.disc_optimizer import DiscCandidate
from app.services.disc_scorer import DiscScoreResult
from app.services.modifiers import (
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.scorer_support import (
    _build_base_for_target,
    _disc_rarity_str,
    _disc_stat_dict,
    _hypothetical_set_counts,
    _other_disc_stats,
    _slot_value,
    applicable_set_modifiers,
)


def _mod(source: ModifierSource, *, stat: str = "atk_pct", value: int = 1000) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=source,
        source_label=source.value,
        target=ModifierTarget.SELF,
        conditions=(Condition.ALWAYS,),
        scopes=(AttackScope.ALL,),
        max_stacks=1,
    )


def _disc(
    *,
    slot: int = 1,
    set_id: int = 100,
    main_stat_type: str = "atk",
    main_stat_value: int = 0,
    substats=None,
    rarity: str = "S",
) -> SimpleNamespace:
    """ORM-shaped Disc stand-in for helper tests."""
    return SimpleNamespace(
        id=f"d-{slot}-{set_id}",
        slot=SimpleNamespace(value=slot),
        rarity=SimpleNamespace(value=rarity),
        main_stat_type=SimpleNamespace(value=main_stat_type),
        main_stat_value=main_stat_value,
        substats=substats,
        disc_set=SimpleNamespace(hakushin_id=set_id),
    )


class TestDiscStatDict:
    def test_unwraps_enum_main_stat_type(self):
        d = _disc(main_stat_type="crit_rate", main_stat_value=2400)
        assert _disc_stat_dict(d) == {
            "main_stat_type": "crit_rate",
            "main_stat_value": 2400,
            "substats": [],
        }

    def test_passes_through_string_main_stat_type(self):
        d = SimpleNamespace(
            main_stat_type="atk",
            main_stat_value=300,
            substats=[{"stat": "atk_pct", "value": 300}],
        )
        assert _disc_stat_dict(d) == {
            "main_stat_type": "atk",
            "main_stat_value": 300,
            "substats": [{"stat": "atk_pct", "value": 300}],
        }

    def test_null_substats_become_empty_list(self):
        d = SimpleNamespace(
            main_stat_type="hp",
            main_stat_value=0,
            substats=None,
        )
        assert _disc_stat_dict(d)["substats"] == []


class TestSlotValue:
    def test_unwraps_enum(self):
        assert _slot_value(SimpleNamespace(slot=SimpleNamespace(value=4))) == 4

    def test_passes_through_int(self):
        assert _slot_value(SimpleNamespace(slot=2)) == 2


class TestOtherDiscStats:
    def test_filters_target_slot(self):
        discs = [_disc(slot=1), _disc(slot=2), _disc(slot=3)]
        result = _other_disc_stats(discs, target_slot=2)
        assert len(result) == 2
        assert all(s["main_stat_type"] == "atk" for s in result)

    def test_no_target_match_returns_all(self):
        discs = [_disc(slot=1), _disc(slot=2)]
        assert len(_other_disc_stats(discs, target_slot=6)) == 2


class TestHypotheticalSetCounts:
    def test_counts_others_plus_target_set(self):
        """Target slot's existing disc must be excluded; target set added."""
        build_discs = [
            _disc(slot=1, set_id=100),
            _disc(slot=2, set_id=100),
            _disc(slot=3, set_id=200),
            _disc(slot=4, set_id=200),  # this one will be replaced
            _disc(slot=5, set_id=200),
            _disc(slot=6, set_id=300),
        ]
        target = DiscCandidate(disc_id="t", slot=4, set_id=999)
        counts = _hypothetical_set_counts(build_discs, target)
        # Slot-4 disc dropped; target's set 999 added.
        assert counts == {100: 2, 200: 2, 300: 1, 999: 1}

    def test_target_same_set_increments(self):
        """If target shares a set with kept discs, counts merge."""
        build_discs = [
            _disc(slot=1, set_id=100),
            _disc(slot=2, set_id=100),
            _disc(slot=3, set_id=100),  # replaced
        ]
        target = DiscCandidate(disc_id="t", slot=3, set_id=100)
        counts = _hypothetical_set_counts(build_discs, target)
        assert counts == {100: 3}

    def test_skips_discs_without_disc_set_relationship(self):
        d = SimpleNamespace(slot=1, disc_set=None)
        target = DiscCandidate(disc_id="t", slot=2, set_id=42)
        assert _hypothetical_set_counts([d], target) == {42: 1}


class TestApplicableSetModifiers:
    def test_2pc_active_only_when_count_at_least_two(self):
        mods_map = {
            100: [_mod(ModifierSource.DISC_SET_2PC)],
        }
        assert applicable_set_modifiers({100: 1}, mods_map) == []
        assert len(applicable_set_modifiers({100: 2}, mods_map)) == 1
        assert len(applicable_set_modifiers({100: 4}, mods_map)) == 1

    def test_4pc_active_only_when_count_at_least_four(self):
        mods_map = {
            100: [
                _mod(ModifierSource.DISC_SET_2PC),
                _mod(ModifierSource.DISC_SET_4PC),
            ],
        }
        assert len(applicable_set_modifiers({100: 2}, mods_map)) == 1  # 2pc only
        assert len(applicable_set_modifiers({100: 4}, mods_map)) == 2  # both

    def test_unknown_set_id_silently_ignored(self):
        mods_map = {100: [_mod(ModifierSource.DISC_SET_2PC)]}
        assert applicable_set_modifiers({999: 4}, mods_map) == []

    def test_other_modifier_sources_excluded(self):
        """Only DISC_SET_2PC / DISC_SET_4PC sources gate on piece counts."""
        mods_map = {100: [_mod(ModifierSource.WENGINE_PASSIVE)]}
        assert applicable_set_modifiers({100: 4}, mods_map) == []


class TestDiscRarityStr:
    def test_unwraps_enum(self):
        d = SimpleNamespace(rarity=SimpleNamespace(value="A"))
        assert _disc_rarity_str(d) == "A"

    def test_passes_through_string(self):
        d = SimpleNamespace(rarity="B")
        assert _disc_rarity_str(d) == "B"


class TestBuildBaseForTarget:
    def test_replaces_disc_stats_and_appends_set_modifiers(self):
        stripped = BuildSnapshot(
            agent_base_atk=900,
            disc_stats=[],
            modifiers=[_mod(ModifierSource.CORE_SKILL)],
        )
        build_discs = [_disc(slot=1, set_id=100), _disc(slot=2, set_id=100)]
        target = DiscCandidate(disc_id="t", slot=4, set_id=100)
        sentinel = _mod(ModifierSource.DISC_SET_2PC, stat="crit_rate", value=800)
        base = _build_base_for_target(
            stripped=stripped,
            build_discs=build_discs,
            target=target,
            disc_set_modifiers={100: [sentinel]},
        )
        # 2 other discs feed in.
        assert len(base.disc_stats) == 2
        # Original modifier preserved + 2pc applied (3 pieces of set 100 in
        # the hypothetical: slot1 + slot2 + target).
        sources = [m.source for m in base.modifiers]
        assert ModifierSource.CORE_SKILL in sources
        assert ModifierSource.DISC_SET_2PC in sources

    def test_below_threshold_drops_set_modifier(self):
        stripped = BuildSnapshot(agent_base_atk=900)
        build_discs = [_disc(slot=1, set_id=100)]
        target = DiscCandidate(disc_id="t", slot=4, set_id=200)
        # Only one piece of set 100 and one piece of set 200 — neither
        # reaches 2pc, so neither bonus should apply.
        mods_map = {
            100: [_mod(ModifierSource.DISC_SET_2PC)],
            200: [_mod(ModifierSource.DISC_SET_2PC)],
        }
        base = _build_base_for_target(
            stripped=stripped,
            build_discs=build_discs,
            target=target,
            disc_set_modifiers=mods_map,
        )
        assert all(m.source != ModifierSource.DISC_SET_2PC for m in base.modifiers)

    def test_preserves_other_snapshot_fields(self):
        stripped = BuildSnapshot(
            agent_base_atk=900,
            agent_base_hp=10000,
            wengine_base_atk=600,
            agent_element="ice",
        )
        target = DiscCandidate(disc_id="t", slot=4, set_id=100)
        base = _build_base_for_target(
            stripped=stripped,
            build_discs=[],
            target=target,
            disc_set_modifiers={},
        )
        assert base.agent_base_atk == 900
        assert base.agent_base_hp == 10000
        assert base.wengine_base_atk == 600
        assert base.agent_element == "ice"


class TestResolveCritMode:
    def test_known_modes(self):
        assert _resolve_crit_mode("expected") == CritMode.EXPECTED
        assert _resolve_crit_mode("crit") == CritMode.CRIT
        assert _resolve_crit_mode("no_crit") == CritMode.NO_CRIT

    def test_unknown_raises_422(self):
        with pytest.raises(HTTPException) as exc:
            _resolve_crit_mode("garbage")
        assert exc.value.status_code == 422


class TestResultToSchema:
    def _result(self):
        return DiscScoreResult(
            current_damage=100.0,
            baseline_damage=95.0,
            max_improvement=20.0,
            mean_improvement=10.0,
            stddev_improvement=3.0,
            p10=2.0,
            p50=10.0,
            p90=18.0,
            distribution=[(2.0, 0.2), (10.0, 0.6), (18.0, 0.2)],
            rolls_used=4,
            remaining_rolls=5,
        )

    def test_excludes_distribution_when_flag_off(self):
        schema = _result_to_schema("d-1", self._result(), include_distribution=False)
        assert schema.distribution is None
        assert schema.current_damage == 100.0
        assert schema.rolls_used == 4
        assert schema.remaining_rolls == 5

    def test_includes_distribution_when_flag_on(self):
        schema = _result_to_schema("d-1", self._result(), include_distribution=True)
        assert schema.distribution == [(2.0, 0.2), (10.0, 0.6), (18.0, 0.2)]

    def test_carries_summary_stats_through(self):
        schema = _result_to_schema("xyz", self._result(), include_distribution=False)
        assert schema.disc_id == "xyz"
        assert schema.current_damage == 100.0
        assert schema.baseline_damage == 95.0
        assert schema.max_improvement == 20.0
        assert schema.mean_improvement == 10.0
        assert schema.stddev_improvement == 3.0
        assert schema.p10 == 2.0
        assert schema.p50 == 10.0
        assert schema.p90 == 18.0
