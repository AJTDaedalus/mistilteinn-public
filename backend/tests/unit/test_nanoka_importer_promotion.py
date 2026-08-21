"""Unit tests for F-30: import `promotion_stats` from nanoka's `level` dict.

nanoka's `character/<id>.json` `level` dict carries the exact per-tier
promotion bonuses (1-indexed tiers "1".."6"); the model's `promotion_stats`
column is a 0-indexed list of `{hp, atk, def}` bonuses. Previously this data
was never imported, leaving `promotion_stats` NULL and every agent's
level-scaled stats on the median-ratio fallback in `snapshot_builder.py`.
"""

from __future__ import annotations

from app.data.importers.nanoka_importer import _extract_promotion_stats

# Real nanoka `character/1221.json` `level` dict (Yanagi), fetched 2026-07-05.
_YANAGI_LEVEL_DATA = {
    "1": {"hp_max": 0, "attack": 0, "defence": 0},
    "2": {"hp_max": 430, "attack": 45, "defence": 34},
    "3": {"hp_max": 859, "attack": 90, "defence": 68},
    "4": {"hp_max": 1289, "attack": 134, "defence": 101},
    "5": {"hp_max": 1719, "attack": 179, "defence": 135},
    "6": {"hp_max": 2149, "attack": 224, "defence": 169},
}


class TestExtractPromotionStats:
    def test_tier_six_matches_source(self) -> None:
        # Tier 6 -> index 5: +224 ATK / +2149 HP / +169 DEF (F-30 evidence).
        stats = _extract_promotion_stats(_YANAGI_LEVEL_DATA)
        assert stats is not None
        assert stats[5] == {"hp": 2149, "atk": 224, "def": 169}

    def test_all_six_tiers_mapped_in_order(self) -> None:
        stats = _extract_promotion_stats(_YANAGI_LEVEL_DATA)
        assert stats == [
            {"hp": 0, "atk": 0, "def": 0},
            {"hp": 430, "atk": 45, "def": 34},
            {"hp": 859, "atk": 90, "def": 68},
            {"hp": 1289, "atk": 134, "def": 101},
            {"hp": 1719, "atk": 179, "def": 135},
            {"hp": 2149, "atk": 224, "def": 169},
        ]

    def test_returns_six_entries(self) -> None:
        assert len(_extract_promotion_stats(_YANAGI_LEVEL_DATA)) == 6

    def test_missing_tier_defaults_to_zero(self) -> None:
        partial = {"6": {"hp_max": 2149, "attack": 224, "defence": 169}}
        stats = _extract_promotion_stats(partial)
        assert stats is not None
        assert stats[0] == {"hp": 0, "atk": 0, "def": 0}
        assert stats[5] == {"hp": 2149, "atk": 224, "def": 169}

    def test_empty_level_data_returns_none(self) -> None:
        assert _extract_promotion_stats({}) is None
