"""Unit tests for the ZOD scanner importer.

The pure helpers (parse, draft conversion, hash) are exercised directly.
The async DB-touching ``import_zod_payload`` is covered by an integration
test against the references ZOD file.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.data.importers.scanner_importer import (
    _MAX_STRING_LEN,
    _MAX_SUBSTATS,
    _MAX_UPGRADES,
    _RARITY_INT_MAP,
    _SUBSTAT_MAP,
    MAX_DISC_COUNT,
    _content_hash,
    _normalize_set_key,
    _substat_value_from_exact,
    _zod_disc_to_draft,
    parse_zod_payload,
)
from app.models.enums import DiscSlot, Rarity, StatType


def test_normalize_set_key_strips_punct_and_case():
    assert _normalize_set_key("Phaethon's Melody") == "phaethonsmelody"
    assert _normalize_set_key("Branch & Blade Song") == "branchbladesong"
    assert _normalize_set_key("MoonlightLullaby") == "moonlightlullaby"


def test_parse_rejects_wrong_format():
    with pytest.raises(ValueError, match="Expected format=ZOD"):
        parse_zod_payload({"format": "GOOD", "discs": []})


def test_parse_rejects_missing_discs():
    with pytest.raises(ValueError, match="missing 'discs'"):
        parse_zod_payload({"format": "ZOD"})


def test_parse_accepts_string_payload():
    raw = '{"format":"ZOD","version":1,"discs":[]}'
    out = parse_zod_payload(raw)
    assert out["discs"] == []


def _disc_set(name: str, set_id: str = "set-1") -> SimpleNamespace:
    return SimpleNamespace(id=set_id, name=name)


def _zod_disc(**kw) -> dict:
    base = {
        "setKey": "MoonlightLullaby",
        "slotKey": "1",
        "level": 15,
        "rarity": "S",
        "mainStatKey": "hp",
        "substats": [
            {"key": "crit_", "upgrades": 2},
            {"key": "atk_", "upgrades": 3},
            {"key": "def_", "upgrades": 3},
            {"key": "atk", "upgrades": 1},
        ],
    }
    base.update(kw)
    return base


class TestDraftConversion:
    def setup_method(self):
        self.lookup = {"moonlightlullaby": _disc_set("Moonlight Lullaby")}

    def test_resolves_set_and_main_stat(self):
        draft = _zod_disc_to_draft(_zod_disc(), set_lookup=self.lookup)
        assert draft.disc_set_id == "set-1"
        assert draft.slot == DiscSlot.ONE
        assert draft.rarity == Rarity.S
        assert draft.level == 15
        assert draft.main_stat_type == StatType.HP
        assert draft.main_stat_value == 2200  # max-level S slot-1 HP

    def test_substats_have_value_per_roll(self):
        draft = _zod_disc_to_draft(_zod_disc(), set_lookup=self.lookup)
        # crit_=240 base × 2 rolls = 480; atk_=300 × 3 = 900; def_=480 × 3 = 1440;
        # atk (flat) = 19 × 1 = 19.
        by_stat = {s["stat"]: s["value"] for s in draft.substats}
        assert by_stat["crit_rate"] == 480
        assert by_stat["atk_pct"] == 900
        assert by_stat["def_pct"] == 1440
        assert by_stat["atk"] == 19
        # Roll counts preserved.
        rolls = {s["stat"]: s["rolls"] for s in draft.substats}
        assert rolls["crit_rate"] == 2
        assert rolls["atk"] == 1

    def test_substat_pen_is_flat_not_ratio(self):
        """ZOD substat 'pen' (no underscore) is flat PEN; main 'pen_' is %."""
        draft = _zod_disc_to_draft(
            _zod_disc(substats=[{"key": "pen", "upgrades": 4}]),
            set_lookup=self.lookup,
        )
        sub = draft.substats[0]
        assert sub["stat"] == "pen_flat"
        assert sub["value"] == 36  # 9 × 4

    def test_unknown_set_returns_skip_reason(self):
        outcome = _zod_disc_to_draft(
            _zod_disc(setKey="MadeUpSet"),
            set_lookup=self.lookup,
        )
        assert isinstance(outcome, tuple)
        _, reason = outcome
        assert "unknown set" in reason

    def test_invalid_rarity_returns_skip(self):
        outcome = _zod_disc_to_draft(
            _zod_disc(rarity="Z"),
            set_lookup=self.lookup,
        )
        assert isinstance(outcome, tuple)
        _, reason = outcome
        assert "invalid rarity" in reason

    def test_a_rank_main_stat_is_scaled(self):
        """A-rank max-main is ~80% of S-rank for the same slot/stat."""
        draft = _zod_disc_to_draft(
            _zod_disc(rarity="A", level=12),
            set_lookup=self.lookup,
        )
        assert draft.main_stat_value == int(2200 * 0.80)

    def test_partial_level_scales_main_proportionally(self):
        draft = _zod_disc_to_draft(
            _zod_disc(level=0),
            set_lookup=self.lookup,
        )
        # Level 0 floors to ~10% of max so the value isn't zero.
        assert 0 < draft.main_stat_value < 2200

    def test_element_dmg_main_stat(self):
        """Slot 5 with fire_dmg_ resolves to FIRE_DMG and 30% max."""
        draft = _zod_disc_to_draft(
            _zod_disc(slotKey="5", mainStatKey="fire_dmg_"),
            set_lookup=self.lookup,
        )
        assert draft.main_stat_type == StatType.FIRE_DMG
        assert draft.main_stat_value == 3000

    def test_wind_element_dmg_main_stat(self):
        """Slot 5 with wind_dmg_ resolves to WIND_DMG and 30% max (Velina-era Wind discs)."""
        draft = _zod_disc_to_draft(
            _zod_disc(slotKey="5", mainStatKey="wind_dmg_"),
            set_lookup=self.lookup,
        )
        assert draft.main_stat_type == StatType.WIND_DMG
        assert draft.main_stat_value == 3000


class TestContentHash:
    def setup_method(self):
        self.lookup = {"moonlightlullaby": _disc_set("Moonlight Lullaby")}

    def test_identical_drafts_collide(self):
        a = _zod_disc_to_draft(_zod_disc(), set_lookup=self.lookup)
        b = _zod_disc_to_draft(_zod_disc(), set_lookup=self.lookup)
        assert _content_hash(a) == _content_hash(b)

    def test_substat_order_does_not_matter(self):
        a = _zod_disc_to_draft(_zod_disc(), set_lookup=self.lookup)
        # Reverse the substat order in the ZOD input.
        flipped = _zod_disc()
        flipped["substats"] = list(reversed(flipped["substats"]))
        b = _zod_disc_to_draft(flipped, set_lookup=self.lookup)
        assert _content_hash(a) == _content_hash(b)

    def test_different_levels_diverge(self):
        a = _zod_disc_to_draft(_zod_disc(), set_lookup=self.lookup)
        b = _zod_disc_to_draft(_zod_disc(level=12), set_lookup=self.lookup)
        assert _content_hash(a) != _content_hash(b)


class TestParseHardening:
    """parse_zod_payload input-validation guards."""

    def test_rejects_malformed_json_string(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_zod_payload("{not valid json")

    def test_rejects_malformed_json_bytes(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_zod_payload(b"[1, 2, 3")

    def test_rejects_json_array_at_top_level(self):
        with pytest.raises(TypeError, match="JSON object"):
            parse_zod_payload("[]")

    def test_rejects_discs_not_a_list(self):
        with pytest.raises(ValueError, match="missing 'discs'"):
            parse_zod_payload({"format": "ZOD", "discs": "not-a-list"})

    def test_rejects_too_many_discs(self):
        oversized = {"format": "ZOD", "discs": [{}] * (MAX_DISC_COUNT + 1)}
        with pytest.raises(ValueError, match="exceeds maximum"):
            parse_zod_payload(oversized)

    def test_accepts_exactly_max_discs(self):
        payload = {"format": "ZOD", "discs": [{}] * MAX_DISC_COUNT}
        result = parse_zod_payload(payload)
        assert len(result["discs"]) == MAX_DISC_COUNT


class TestDraftHardening:
    """_zod_disc_to_draft per-disc input-validation guards."""

    def setup_method(self):
        self.lookup = {"moonlightlullaby": _disc_set("Moonlight Lullaby")}

    def _skip_reason(self, raw: dict | object) -> str:
        outcome = _zod_disc_to_draft(raw, set_lookup=self.lookup)
        assert isinstance(outcome, tuple), "Expected a skip tuple, got a draft"
        _, reason = outcome
        return reason

    def test_rejects_non_dict_disc(self):
        reason = self._skip_reason("just a string")
        assert "not an object" in reason

    def test_rejects_non_dict_disc_list(self):
        reason = self._skip_reason([1, 2, 3])
        assert "not an object" in reason

    def test_rejects_overlong_set_key(self):
        reason = self._skip_reason(_zod_disc(setKey="A" * (_MAX_STRING_LEN + 1)))
        assert "setKey" in reason

    def test_rejects_overlong_main_stat_key(self):
        reason = self._skip_reason(_zod_disc(mainStatKey="x" * (_MAX_STRING_LEN + 1)))
        assert "mainStatKey" in reason

    def test_rejects_non_string_set_key(self):
        reason = self._skip_reason(_zod_disc(setKey=12345))
        assert "setKey" in reason

    def test_rejects_non_numeric_level(self):
        reason = self._skip_reason(_zod_disc(level="notanumber"))
        assert "invalid level" in reason

    def test_rejects_too_many_substats(self):
        many_subs = [{"key": "atk_", "upgrades": 1}] * (_MAX_SUBSTATS + 1)
        reason = self._skip_reason(_zod_disc(substats=many_subs))
        assert "too many substats" in reason

    def test_rejects_non_list_substats(self):
        reason = self._skip_reason(_zod_disc(substats={"key": "atk_", "upgrades": 1}))
        assert "substats must be an array" in reason

    def test_rejects_non_dict_substat_entry(self):
        reason = self._skip_reason(_zod_disc(substats=["not_a_dict"]))
        assert "not an object" in reason

    def test_rejects_non_numeric_upgrades(self):
        reason = self._skip_reason(_zod_disc(substats=[{"key": "atk_", "upgrades": "abc"}]))
        assert "invalid upgrades" in reason

    def test_rejects_upgrades_above_max(self):
        reason = self._skip_reason(
            _zod_disc(substats=[{"key": "atk_", "upgrades": _MAX_UPGRADES + 1}])
        )
        assert "rolls" in reason
        assert str(_MAX_UPGRADES + 1) in reason

    def test_rejects_overlong_substat_key(self):
        reason = self._skip_reason(
            _zod_disc(substats=[{"key": "x" * (_MAX_STRING_LEN + 1), "upgrades": 2}])
        )
        assert "substat key" in reason

    def test_accepts_max_upgrades(self):
        """S-rank substats can legitimately roll _MAX_UPGRADES times."""
        draft = _zod_disc_to_draft(
            _zod_disc(substats=[{"key": "atk_", "upgrades": _MAX_UPGRADES}]),
            set_lookup=self.lookup,
        )
        assert draft.substats[0]["rolls"] == _MAX_UPGRADES

    def test_accepts_max_substats(self):
        subs = [
            {"key": "atk_", "upgrades": 1},
            {"key": "hp_", "upgrades": 1},
            {"key": "crit_", "upgrades": 1},
            {"key": "atk", "upgrades": 1},
        ]
        assert len(subs) == _MAX_SUBSTATS
        draft = _zod_disc_to_draft(_zod_disc(substats=subs), set_lookup=self.lookup)
        assert len(draft.substats) == _MAX_SUBSTATS


class TestReferencesFile:
    """Smoke checks against the actual ZOD export in references/."""

    def test_references_file_parses_and_has_discs(self):
        path = Path(__file__).parents[3] / "references"
        zods = list(path.glob("*.ZOD.json"))
        if not zods:
            pytest.skip("no ZOD reference file checked in")
        data = json.loads(zods[0].read_text())
        parsed = parse_zod_payload(data)
        assert parsed["format"] == "ZOD"
        assert len(parsed["discs"]) > 0


class TestEzodHelpers:
    """Shared helpers introduced for the eZOD exact-value path."""

    def test_percent_substat_converts_to_bp(self):
        assert _substat_value_from_exact(StatType.ATK_PCT, 9.0) == 900
        assert _substat_value_from_exact(StatType.CRIT_RATE, 2.4) == 240
        assert _substat_value_from_exact(StatType.CRIT_DMG, 4.8) == 480
        assert _substat_value_from_exact(StatType.HP_PCT, 3.0) == 300
        assert _substat_value_from_exact(StatType.DEF_PCT, 4.8) == 480

    def test_flat_substat_stays_int(self):
        assert _substat_value_from_exact(StatType.PEN_FLAT, 27.0) == 27
        assert _substat_value_from_exact(StatType.ANOMALY_PROFICIENCY, 9.0) == 9
        assert _substat_value_from_exact(StatType.ATK, 19.0) == 19
        assert _substat_value_from_exact(StatType.HP, 112.0) == 112

    def test_empty_key_not_in_substat_map(self):
        """Empty-key substats (eZOD padding for <4 real substats) are silently skipped."""
        assert _SUBSTAT_MAP.get("") is None

    def test_rarity_int_map_covers_all_ranks(self):
        assert _RARITY_INT_MAP[4] == Rarity.S
        assert _RARITY_INT_MAP[3] == Rarity.A
        assert _RARITY_INT_MAP[2] == Rarity.B
        assert set(_RARITY_INT_MAP.keys()) == {4, 3, 2}
