"""GOOD's optional `materials` map reaches the planner.

The importer read `artifacts`, `characters` and `weapons` and ignored `materials` — measured
on the owner's own Irminsul export, which carries **1,384** material entries. This is what
finally reads it.
"""

from __future__ import annotations

import pytest

from app.data.importers.good_importer import parse_good
from app.services.good_import_service import set_lookup_key


def _envelope(**extra: object) -> dict:
    return {"format": "GOOD", "version": 3, "source": "test", "artifacts": [], **extra}


def test_materials_are_parsed_when_present() -> None:
    result = parse_good(_envelope(materials={"HerosWit": 204, "CrownOfInsight": 23}))
    assert result.materials == {"HerosWit": 204, "CrownOfInsight": 23}


def test_an_export_without_materials_is_still_valid() -> None:
    """Plenty of scanners write artifacts only; that is a GOOD file, not a broken one."""
    assert parse_good(_envelope()).materials == {}


@pytest.mark.parametrize("value", [0, -3, "12", 1.5, True, None])
def test_nonsense_counts_are_dropped_not_refused(value: object) -> None:
    """A single odd entry must not cost the user an import of 2,370 artifacts."""
    result = parse_good(_envelope(materials={"HerosWit": value}))
    assert result.materials == {}


def test_the_apostrophe_rule_is_what_lookup_key_already_handles() -> None:
    """GOOD drops the apostrophe **without capitalising the next letter**.

    `Hero's Wit` is `HerosWit`, not `HeroSWit`. A hand-written probe using the wrong rule
    reported the EXP books absent from the owner's export and nearly became a finding that
    scanners do not export them; they hold 204 and 860 respectively. `set_lookup_key`
    normalises both sides and never had the problem.
    """
    assert set_lookup_key("HerosWit") == set_lookup_key("Hero's Wit")
    assert set_lookup_key("AdventurersExperience") == set_lookup_key("Adventurer's Experience")
    assert set_lookup_key("MysticEnhancementOre") == set_lookup_key("Mystic Enhancement Ore")
