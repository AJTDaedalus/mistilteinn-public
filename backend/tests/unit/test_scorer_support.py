"""Unit tests for scorer_support helpers (Phase 2 — R2.2).

Mirrors test_api_scorer_helpers.py but imports from the service module
directly, proving helpers are accessible without going through the API layer.
Also verifies that BuildSnapshot (the key output type) survives a
pickle round-trip — required for process-pool use in the rank pipeline.
"""

from __future__ import annotations

import pickle
from types import SimpleNamespace

from app.services.build_damage_service import BuildSnapshot
from app.services.disc_optimizer import DiscCandidate
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
    return SimpleNamespace(
        id=f"d-{slot}-{set_id}",
        slot=SimpleNamespace(value=slot),
        rarity=SimpleNamespace(value=rarity),
        main_stat_type=SimpleNamespace(value=main_stat_type),
        main_stat_value=main_stat_value,
        substats=substats,
        disc_set=SimpleNamespace(hakushin_id=set_id),
    )


class TestPicklability:
    def test_build_snapshot_pickle_round_trip(self):
        stripped = BuildSnapshot(
            agent_base_atk=900,
            disc_stats=[],
            modifiers=[_mod(ModifierSource.CORE_SKILL)],
        )
        build_discs = [_disc(slot=1, set_id=100), _disc(slot=2, set_id=100)]
        target = DiscCandidate(disc_id="t", slot=4, set_id=100)
        result = _build_base_for_target(
            stripped=stripped,
            build_discs=build_discs,
            target=target,
            disc_set_modifiers={100: [_mod(ModifierSource.DISC_SET_2PC)]},
        )
        # Must survive a pickle round-trip for process-pool use.
        restored = pickle.loads(pickle.dumps(result))
        assert restored.agent_base_atk == result.agent_base_atk
        assert len(restored.disc_stats) == len(result.disc_stats)
        assert len(restored.modifiers) == len(result.modifiers)

    def test_disc_candidate_pickle_round_trip(self):
        candidate = DiscCandidate(disc_id="x", slot=3, set_id=42)
        restored = pickle.loads(pickle.dumps(candidate))
        assert restored.disc_id == "x"
        assert restored.slot == 3
        assert restored.set_id == 42


class TestDiscStatDict:
    def test_unwraps_enum_main_stat_type(self):
        d = _disc(main_stat_type="crit_rate", main_stat_value=2400)
        assert _disc_stat_dict(d) == {
            "main_stat_type": "crit_rate",
            "main_stat_value": 2400,
            "substats": [],
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


class TestHypotheticalSetCounts:
    def test_counts_others_plus_target_set(self):
        build_discs = [
            _disc(slot=1, set_id=100),
            _disc(slot=2, set_id=100),
            _disc(slot=3, set_id=200),
            _disc(slot=4, set_id=200),
            _disc(slot=5, set_id=200),
            _disc(slot=6, set_id=300),
        ]
        target = DiscCandidate(disc_id="t", slot=4, set_id=999)
        counts = _hypothetical_set_counts(build_discs, target)
        assert counts == {100: 2, 200: 2, 300: 1, 999: 1}

    def test_skips_discs_without_disc_set_relationship(self):
        d = SimpleNamespace(slot=1, disc_set=None)
        target = DiscCandidate(disc_id="t", slot=2, set_id=42)
        assert _hypothetical_set_counts([d], target) == {42: 1}


class TestApplicableSetModifiers:
    def test_2pc_threshold(self):
        mods_map = {100: [_mod(ModifierSource.DISC_SET_2PC)]}
        assert applicable_set_modifiers({100: 1}, mods_map) == []
        assert len(applicable_set_modifiers({100: 2}, mods_map)) == 1

    def test_4pc_threshold(self):
        mods_map = {100: [_mod(ModifierSource.DISC_SET_2PC), _mod(ModifierSource.DISC_SET_4PC)]}
        assert len(applicable_set_modifiers({100: 2}, mods_map)) == 1
        assert len(applicable_set_modifiers({100: 4}, mods_map)) == 2


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
        assert len(base.disc_stats) == 2
        sources = [m.source for m in base.modifiers]
        assert ModifierSource.CORE_SKILL in sources
        assert ModifierSource.DISC_SET_2PC in sources

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
