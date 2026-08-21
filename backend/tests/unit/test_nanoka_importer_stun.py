"""Unit tests for F-15: `stun_threshold` imported from the wrong field.

`_import_one_enemy` previously mapped `stun_threshold = stats["break_stun"]`,
but `break_stun` is 0 for every monster in the source data. The actual daze
gauge max lives under the `stun` key (e.g. Pompey `stun = 6762`).
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


def _make_monster_data(stun: int, break_stun: int) -> dict:
    return {
        "id": 30021,
        "name": "Pompey",
        "rarity": 4,
        "tag": [],
        "monster_info": {
            "0": {
                "stats": {
                    "hp": 100000,
                    "attack": 1000,
                    "defence": 500,
                    "stun": stun,
                    "break_stun": break_stun,
                }
            }
        },
        "element_abnormal": {},
    }


class TestStunThreshold:
    @pytest.mark.asyncio
    async def test_stun_threshold_reads_stun_field(self) -> None:
        importer, _ = _make_importer()
        data = _make_monster_data(stun=6762, break_stun=0)
        enemy = await importer._import_one_enemy(data)
        assert enemy is not None
        assert enemy.stun_threshold == 6762

    @pytest.mark.asyncio
    async def test_stun_threshold_ignores_break_stun(self) -> None:
        """`break_stun` is 0 for every monster; it must no longer be the source."""
        importer, _ = _make_importer()
        data = _make_monster_data(stun=4200, break_stun=999)
        enemy = await importer._import_one_enemy(data)
        assert enemy is not None
        assert enemy.stun_threshold == 4200

    @pytest.mark.asyncio
    async def test_stun_threshold_defaults_to_zero_when_missing(self) -> None:
        importer, _ = _make_importer()
        data = _make_monster_data(stun=0, break_stun=0)
        data["monster_info"]["0"]["stats"].pop("stun")
        enemy = await importer._import_one_enemy(data)
        assert enemy is not None
        assert enemy.stun_threshold == 0
