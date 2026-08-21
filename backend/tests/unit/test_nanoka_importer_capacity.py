"""Unit tests for F-14: enemy anomaly-capacity key lookup (rarity-4 bosses).

`_get_capacity` (nested in `_import_one_enemy`) previously built its lookup key
from `rarity * 10000 + curve_id % 100`, which only happens to work when the
curve's own tier prefix (1xxxx/2xxxx/3xxxx) matches the monster's rarity. For
rarity-4 bosses using boss-tier (3xxxx) curves, the key never matched and the
importer silently fell back to the rarity-1 (normal-tier) gauge.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.data.importers.nanoka_importer import NanokaImporter


def _make_importer() -> tuple[NanokaImporter, MagicMock]:
    session = MagicMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    importer = NanokaImporter.__new__(NanokaImporter)
    importer.session = session
    return importer, session


def _make_monster_data(rarity: int, fire_curve: int, element_abnormal: dict) -> dict:
    return {
        "id": 30021,
        "name": "Pompey",
        "rarity": rarity,
        "tag": [],
        "monster_info": {
            "0": {
                "stats": {
                    "hp": 100000,
                    "attack": 1000,
                    "defence": 500,
                    "fire_buildup_curve": fire_curve,
                    "stun": 6762,
                }
            }
        },
        "element_abnormal": element_abnormal,
    }


class TestGetCapacityRarityFourBoss:
    @pytest.mark.asyncio
    async def test_boss_tier_curve_resolves_to_boss_gauge(self) -> None:
        """Pompey (rarity 4): fire curve 30012 must resolve to the 3000 boss
        gauge directly keyed by the curve id, not the buggy 600 fallback."""
        importer, _ = _make_importer()
        data = _make_monster_data(
            rarity=4,
            fire_curve=30012,
            element_abnormal={"10012": 600, "20012": 1150, "30012": 3000},
        )
        enemy = await importer._import_one_enemy(data)
        assert enemy is not None
        assert enemy.anomaly_capacity_fire == 3000

    @pytest.mark.asyncio
    async def test_missing_curve_falls_back_by_tier_not_rarity(self) -> None:
        """If the exact curve id is absent, the fallback must still derive the
        tier from the curve's own prefix, not from monster rarity."""
        importer, _ = _make_importer()
        data = _make_monster_data(
            rarity=4,
            fire_curve=30012,
            element_abnormal={"30099": 9999},  # exact key absent
        )
        enemy = await importer._import_one_enemy(data)
        assert enemy is not None
        # No matching tier-3 key at all -> default, never the rarity-1 (600) trap.
        assert enemy.anomaly_capacity_fire == 100

    @pytest.mark.asyncio
    async def test_no_curve_id_returns_default(self) -> None:
        importer, _ = _make_importer()
        data = _make_monster_data(rarity=1, fire_curve=0, element_abnormal={"10012": 600})
        data["monster_info"]["0"]["stats"].pop("fire_buildup_curve")
        enemy = await importer._import_one_enemy(data)
        assert enemy is not None
        assert enemy.anomaly_capacity_fire == 100


class TestGetCapacitySanityTiers:
    """Sanity data points from F-14: suffix 04 = physical, suffix 06 = wind."""

    @pytest.mark.asyncio
    async def test_physical_suffix_04_all_tiers(self) -> None:
        element_abnormal = {"10004": 720, "20004": 2700, "30004": 3600}
        for tier, expected in ((1, 720), (2, 2700), (3, 3600)):
            importer, _ = _make_importer()
            data = _make_monster_data(rarity=tier, fire_curve=0, element_abnormal=element_abnormal)
            data["monster_info"]["0"]["stats"]["physical_buildup_curve"] = tier * 10000 + 4
            data["monster_info"]["0"]["stats"].pop("fire_buildup_curve")
            enemy = await importer._import_one_enemy(data)
            assert enemy.anomaly_capacity_physical == expected

    @pytest.mark.asyncio
    async def test_wind_suffix_06_all_tiers(self) -> None:
        element_abnormal = {"10006": 300, "20006": 1150, "30006": 1500}
        for tier, expected in ((1, 300), (2, 1150), (3, 1500)):
            importer, _ = _make_importer()
            data = _make_monster_data(rarity=tier, fire_curve=0, element_abnormal=element_abnormal)
            data["monster_info"]["0"]["stats"]["wind_buildup_curve"] = tier * 10000 + 6
            data["monster_info"]["0"]["stats"].pop("fire_buildup_curve")
            enemy = await importer._import_one_enemy(data)
            assert enemy.anomaly_capacity_wind == expected
