"""Unit tests for pure helpers in the optimizer endpoint (Phase 6.3d).

The endpoint itself is a thin controller; what's worth testing without
a DB is the translation between ORM / schema shapes and the optimizer's
value objects — stripping disc contribution from a base snapshot, mapping
DB ``Disc`` models to ``DiscCandidate``, and loading set modifiers for
the inventory's unique sets.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.services.build_damage_service import BuildSnapshot
from app.services.disc_optimizer import DiscCandidate
from app.services.modifiers import (
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.optimizer_pipeline import (
    _disc_to_candidate,
    _disc_to_summary,
    _load_set_modifiers,
    _make_am_variant,
    _strip_disc_contribution,
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


class TestStripDiscContribution:
    def test_removes_disc_stats_and_set_modifiers(self):
        """Base snapshot must not carry prior disc contributions."""
        snap = BuildSnapshot(
            agent_base_atk=900,
            disc_stats=[{"main_stat_type": "atk", "main_stat_value": 100}],
            modifiers=[
                _mod(ModifierSource.CORE_SKILL),
                _mod(ModifierSource.DISC_SET_2PC),
                _mod(ModifierSource.DISC_SET_4PC),
                _mod(ModifierSource.WENGINE_PASSIVE),
            ],
        )
        stripped = _strip_disc_contribution(snap)
        assert stripped.disc_stats == []
        sources = {m.source for m in stripped.modifiers}
        assert ModifierSource.DISC_SET_2PC not in sources
        assert ModifierSource.DISC_SET_4PC not in sources
        # Non-disc sources survive.
        assert ModifierSource.CORE_SKILL in sources
        assert ModifierSource.WENGINE_PASSIVE in sources

    def test_preserves_other_fields(self):
        """Stripping discs must leave agent/W-engine fields intact."""
        snap = BuildSnapshot(
            agent_base_atk=900,
            agent_base_hp=10000,
            wengine_base_atk=600,
            agent_element="ice",
        )
        stripped = _strip_disc_contribution(snap)
        assert stripped.agent_base_atk == 900
        assert stripped.agent_base_hp == 10000
        assert stripped.wengine_base_atk == 600
        assert stripped.agent_element == "ice"


class TestDiscToCandidate:
    def test_translates_enum_and_stringifies_id(self):
        disc_set = SimpleNamespace(hakushin_id=31000)
        disc = SimpleNamespace(
            id="abc-123",
            slot=SimpleNamespace(value=4),  # DiscSlot enum shape
            main_stat_type=SimpleNamespace(value="crit_rate"),
            main_stat_value=2400,
            substats=[{"stat": "atk_pct", "value": 300}],
            disc_set=disc_set,
        )
        cand = _disc_to_candidate(disc)
        assert cand == DiscCandidate(
            disc_id="abc-123",
            slot=4,
            set_id=31000,
            main_stat_type="crit_rate",
            main_stat_value=2400,
            substats=[{"stat": "atk_pct", "value": 300}],
        )

    def test_accepts_plain_ints_and_strings(self):
        """When slot / main_stat_type are not enums, values pass through."""
        disc = SimpleNamespace(
            id=42,  # non-string id should stringify cleanly
            slot=3,
            main_stat_type="def",
            main_stat_value=0,
            substats=None,
            disc_set=SimpleNamespace(hakushin_id=31010),
        )
        cand = _disc_to_candidate(disc)
        assert cand.disc_id == "42"
        assert cand.slot == 3
        assert cand.main_stat_type == "def"
        assert cand.substats == []

    def test_null_substats_become_empty_list(self):
        disc = SimpleNamespace(
            id="d",
            slot=1,
            main_stat_type="hp",
            main_stat_value=0,
            substats=None,
            disc_set=SimpleNamespace(hakushin_id=1),
        )
        assert _disc_to_candidate(disc).substats == []


class TestDiscOptimizeRequestValidator:
    def test_combo_id_only_valid(self):
        from app.schemas.optimizer import DiscOptimizeRequest

        req = DiscOptimizeRequest(combo_id="abc", enemy_profile_id="xyz")
        assert req.combo_id == "abc"
        assert req.combo_ids is None

    def test_combo_ids_only_valid(self):
        from app.schemas.optimizer import DiscOptimizeRequest

        req = DiscOptimizeRequest(combo_ids=["a", "b"], enemy_profile_id="xyz")
        assert req.combo_ids == ["a", "b"]
        assert req.combo_id is None

    def test_both_provided_raises(self):
        import pytest
        from pydantic import ValidationError

        from app.schemas.optimizer import DiscOptimizeRequest

        with pytest.raises(ValidationError):
            DiscOptimizeRequest(combo_id="a", combo_ids=["b"], enemy_profile_id="xyz")

    def test_neither_provided_raises(self):
        import pytest
        from pydantic import ValidationError

        from app.schemas.optimizer import DiscOptimizeRequest

        with pytest.raises(ValidationError):
            DiscOptimizeRequest(enemy_profile_id="xyz")


class TestLoadSetModifiers:
    def test_loads_unique_sets_once(self):
        inventory = [
            DiscCandidate(disc_id="d1", slot=1, set_id=100),
            DiscCandidate(disc_id="d2", slot=2, set_id=100),
            DiscCandidate(disc_id="d3", slot=3, set_id=200),
        ]
        sentinel = _mod(ModifierSource.DISC_SET_2PC)
        with patch(
            "app.services.optimizer_pipeline.load_disc_set_modifiers",
            return_value=[sentinel],
        ) as loader:
            result = _load_set_modifiers(inventory)
        assert set(result.keys()) == {100, 200}
        # Each unique set asks the loader exactly once.
        assert loader.call_count == 2
        loader.assert_any_call("100")
        loader.assert_any_call("200")

    def test_empty_inventory_produces_empty_map(self):
        assert _load_set_modifiers([]) == {}


def _make_disc(**kwargs):
    """Build a SimpleNamespace disc with sensible defaults."""
    disc_set = SimpleNamespace(
        hakushin_id=kwargs.pop("set_id", 31000),
        name=kwargs.pop("set_name", "Woodpecker Electro"),
        icon_path=kwargs.pop("icon_path", "icon/disc/33000.png"),
    )
    defaults = {
        "id": "disc-1",
        "slot": SimpleNamespace(value=4),
        "rarity": SimpleNamespace(value="S"),
        "main_stat_type": SimpleNamespace(value="crit_rate"),
        "main_stat_value": 2400,
        "substats": [],
        "disc_set": disc_set,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestDiscToSummary:
    def test_basic_fields(self):
        disc = _make_disc()
        s = _disc_to_summary(disc)
        assert s.disc_id == "disc-1"
        assert s.slot == 4
        assert s.set_id == 31000
        assert s.set_name == "Woodpecker Electro"
        assert s.main_stat_type == "crit_rate"
        assert s.main_stat_value == 2400
        assert s.rarity == "S"
        assert s.icon_path == "icon/disc/33000.png"
        assert s.score is None

    def test_substats_populated(self):
        disc = _make_disc(
            substats=[
                {"stat": "crit_dmg", "value": 480, "rolls": 1},
                {"stat": "atk_pct", "value": 600, "rolls": 2},
            ]
        )
        s = _disc_to_summary(disc)
        assert len(s.substats) == 2
        assert s.substats[0].stat_type == "crit_dmg"
        assert s.substats[0].value == 480
        assert s.substats[0].rolls == 1
        assert s.substats[1].stat_type == "atk_pct"
        assert s.substats[1].value == 600
        assert s.substats[1].rolls == 2

    def test_substats_none_becomes_empty(self):
        disc = _make_disc(substats=None)
        assert _disc_to_summary(disc).substats == []

    def test_rolls_fallback_from_constants(self):
        """When 'rolls' key absent, rolls derived from SUBSTAT_BASE_PER_ROLL."""
        disc = _make_disc(substats=[{"stat": "crit_dmg", "value": 960}])
        s = _disc_to_summary(disc)
        assert s.substats[0].rolls == 2  # 960 / 480 = 2

    def test_icon_path_empty_string_on_missing(self):
        disc = _make_disc(icon_path="")
        assert _disc_to_summary(disc).icon_path == ""


class TestMakeAmVariant:
    """_make_am_variant must layer extra_am on top of existing disc_stats, not replace them."""

    def _base_build(self) -> BuildSnapshot:
        return BuildSnapshot(
            agent_anomaly_mastery=114,
            disc_stats=[
                {"main_stat_type": "anomaly_mastery", "main_stat_value": 30},
                {"main_stat_type": "crit_rate", "main_stat_value": 2400},
            ],
        )

    def test_zero_extra_am_leaves_disc_stats_unchanged(self):
        base = self._base_build()
        variant = _make_am_variant(base, 0)
        assert variant.disc_stats == base.disc_stats

    def test_extra_am_is_additive_bonus_not_replacement(self):
        from app.services.stat_calculator import accumulate_disc_stats

        base = self._base_build()
        variant = _make_am_variant(base, 30)
        disc = accumulate_disc_stats(variant.disc_stats)
        # Base disc has 30 AM + bonus 30 = 60 total disc AM
        assert disc.anomaly_mastery == 60

    def test_agent_am_is_preserved(self):
        base = self._base_build()
        variant = _make_am_variant(base, 30)
        assert variant.agent_anomaly_mastery == 114

    def test_resolved_total_am_equals_agent_plus_disc_plus_bonus(self):
        from app.services.stat_calculator import accumulate_disc_stats

        base = self._base_build()
        for extra_am in [0, 30, 60, 90]:
            variant = _make_am_variant(base, extra_am)
            disc = accumulate_disc_stats(variant.disc_stats)
            # base disc AM=30, agent AM=114; total = 114 + 30 + extra_am
            resolved = variant.agent_anomaly_mastery + disc.anomaly_mastery
            expected = 144 + extra_am
            assert resolved == expected, (
                f"extra_am={extra_am}: expected {expected}, got {resolved}"
            )

    def test_non_am_disc_stats_preserved(self):
        from app.services.stat_calculator import accumulate_disc_stats

        base = self._base_build()
        variant = _make_am_variant(base, 30)
        disc = accumulate_disc_stats(variant.disc_stats)
        assert disc.crit_rate == 2400


class TestEnumerateCoarseAmValues:
    """enumerate_coarse_am_values covers all (slot-6 AM on/off) × (2pc set active/not) combos."""

    def _pm_mod(self) -> Modifier:
        """Phaethon's Melody 2pc: +8% AM (800 bp)."""
        return Modifier(
            stat="anomaly_mastery_pct",
            value=800,
            source=ModifierSource.DISC_SET_2PC,
            source_label="2pc: AM",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
            max_stacks=1,
        )

    def _candidate(
        self,
        slot: int,
        set_id: int,
        main_stat_type: str = "",
        main_stat_value: int = 0,
    ) -> DiscCandidate:
        return DiscCandidate(
            disc_id=f"d-{slot}-{set_id}",
            slot=slot,
            set_id=set_id,
            main_stat_type=main_stat_type,
            main_stat_value=main_stat_value,
        )

    def test_empty_inventory_returns_only_base(self):
        from app.services.am_variants import enumerate_coarse_am_values

        result = enumerate_coarse_am_values(100, [], {})
        assert result == [100]

    def test_slot6_am_disc_adds_second_value(self):
        from app.services.am_variants import enumerate_coarse_am_values

        inventory = [
            self._candidate(
                slot=6,
                set_id=999,
                main_stat_type="anomaly_mastery",
                main_stat_value=60,
            ),
        ]
        result = enumerate_coarse_am_values(100, inventory, {})
        assert result == [100, 160]

    def test_achievable_am_2pc_set_adds_second_value(self):
        from app.services.am_variants import enumerate_coarse_am_values

        pm_id = 33000
        am_2pc_sets = {pm_id: [self._pm_mod()]}
        # Two PM discs in inventory → 2pc is achievable.
        inventory = [
            self._candidate(slot=1, set_id=pm_id),
            self._candidate(slot=2, set_id=pm_id),
        ]
        result = enumerate_coarse_am_values(100, inventory, am_2pc_sets)
        # floor(100 * 10800 / 10000) = floor(108) = 108
        assert result == [100, 108]

    def test_phaethon_plus_slot6_gives_four_values(self):
        import math

        from app.services.am_variants import enumerate_coarse_am_values

        pm_id = 33000
        am_2pc_sets = {pm_id: [self._pm_mod()]}
        inventory = [
            self._candidate(slot=1, set_id=pm_id),
            self._candidate(slot=2, set_id=pm_id),
            self._candidate(
                slot=6,
                set_id=999,
                main_stat_type="anomaly_mastery",
                main_stat_value=60,
            ),
        ]
        base = 100
        result = enumerate_coarse_am_values(base, inventory, am_2pc_sets)
        expected = sorted(
            {
                base,  # no s6, no pm
                base + 60,  # s6=60, no pm
                math.floor(base * 10800 / 10000),  # no s6, pm active
                math.floor(base * 10800 / 10000) + 60,  # s6=60, pm active
            }
        )
        assert result == expected

    def test_non_am_2pc_set_adds_no_variant(self):
        from app.services.am_variants import enumerate_coarse_am_values

        # A set with CRIT DMG 2pc — not in am_2pc_sets at all.
        inventory = [
            self._candidate(slot=1, set_id=32700),
            self._candidate(slot=2, set_id=32700),
        ]
        result = enumerate_coarse_am_values(100, inventory, {})  # empty am_2pc_sets
        assert result == [100]

    def test_dedup_collapses_identical_coarse_values(self):
        from app.services.am_variants import enumerate_coarse_am_values

        # Two slot-6 AM discs with the same value → only one extra scenario.
        inventory = [
            self._candidate(
                slot=6, set_id=999, main_stat_type="anomaly_mastery", main_stat_value=60
            ),
            self._candidate(
                slot=6, set_id=888, main_stat_type="anomaly_mastery", main_stat_value=60
            ),
        ]
        result = enumerate_coarse_am_values(100, inventory, {})
        assert result == [100, 160]

    def test_only_one_pm_disc_not_achievable(self):
        from app.services.am_variants import enumerate_coarse_am_values

        pm_id = 33000
        am_2pc_sets = {pm_id: [self._pm_mod()]}
        inventory = [self._candidate(slot=1, set_id=pm_id)]  # only 1 disc → not achievable
        result = enumerate_coarse_am_values(100, inventory, am_2pc_sets)
        assert result == [100]


class TestDiscOptimizeRequestNewKnobs:
    """Defaults and validation for prefilter_top_k and energy-gating fields."""

    def _req(self, **kw):
        from app.schemas.optimizer import DiscOptimizeRequest

        return DiscOptimizeRequest(combo_id="abc", enemy_profile_id="xyz", **kw)

    def test_defaults_are_inert(self):
        req = self._req()
        assert req.prefilter_top_k is None
        assert req.rotation_energy_cost is None
        assert req.rotation_duration_s == 0.0

    def test_valid_values_accepted(self):
        req = self._req(prefilter_top_k=8, rotation_energy_cost=120.0, rotation_duration_s=15.0)
        assert req.prefilter_top_k == 8
        assert req.rotation_energy_cost == 120.0
        assert req.rotation_duration_s == 15.0

    def test_prefilter_top_k_must_be_positive(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._req(prefilter_top_k=0)

    def test_rotation_energy_cost_must_be_positive(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._req(rotation_energy_cost=0)

    def test_rotation_duration_must_be_non_negative(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._req(rotation_duration_s=-1.0)
