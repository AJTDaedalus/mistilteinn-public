"""Task B2 — F-29: scanner main-stat progression includes the 25% base."""

from __future__ import annotations

from types import SimpleNamespace

from app.data.importers.scanner_importer import _zod_disc_to_draft
from app.models.enums import StatType


def _disc_set(name: str, set_id: str = "set-1") -> SimpleNamespace:
    return SimpleNamespace(id=set_id, name=name)


def _zod_disc(**kw) -> dict:
    base = {
        "setKey": "MoonlightLullaby",
        "slotKey": "4",
        "level": 15,
        "rarity": "S",
        "mainStatKey": "anomProf",
        "substats": [],
    }
    base.update(kw)
    return base


class TestMainStatProgression:
    def setup_method(self):
        self.lookup = {"moonlightlullaby": _disc_set("Moonlight Lullaby")}

    def _main_value(self, level: int) -> int:
        draft = _zod_disc_to_draft(_zod_disc(level=level), set_lookup=self.lookup)
        assert draft.main_stat_type == StatType.ANOMALY_PROFICIENCY
        return draft.main_stat_value

    def test_plus_0_is_25_pct_of_max(self):
        assert self._main_value(0) == 23  # 0.25 * 92

    def test_plus_3(self):
        assert self._main_value(3) == 36

    def test_plus_9(self):
        assert self._main_value(9) == 64

    def test_plus_15_is_max(self):
        assert self._main_value(15) == 92
