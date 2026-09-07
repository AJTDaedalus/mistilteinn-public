"""The levelling bills are read off the pinned payloads correctly.

These costs sat unread in `tests/fixtures/nanoka_gi/` from Chunk D until the planner, so
there is no prior behaviour to regress against — these tests are the first statement of what
the payloads mean.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.data.importers.nanoka_gi_mappings import (
    NanokaMappingError,
    character_ascension_cost_rows,
    character_fields,
    material_rows,
    talent_cost_rows,
    weapon_ascension_cost_rows,
    weapon_fields,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"


def _payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ayaka() -> dict:
    return _payload("character_10000002.json")


@pytest.fixture(scope="module")
def aquila() -> dict:
    return _payload("weapon_11501.json")


def test_ascension_costs_are_six_phases_in_ladder_order(ayaka: dict) -> None:
    rows = character_ascension_cost_rows(ayaka)
    assert [row["phase"] for row in rows] == [1, 2, 3, 4, 5, 6]
    assert rows[0]["mora"] == 20000
    assert rows[5]["mora"] == 120000
    assert {"id": 104161, "count": 1} in rows[0]["items"]


def test_a_seventh_ascension_entry_is_refused(ayaka: dict) -> None:
    """The phase is the entry's position, so an extra entry must not renumber the ladder."""
    grown = {**ayaka, "materials": {**ayaka["materials"],
                                    "ascensions": [*ayaka["materials"]["ascensions"], {}]}}
    with pytest.raises(NanokaMappingError, match="ascension cost entries"):
        character_ascension_cost_rows(grown)


def test_ayakas_alternate_sprint_contributes_no_talent_rows(ayaka: dict) -> None:
    """Four skills, four cost lists, and the sprint's is empty.

    `Kamisato Art: Senho` has no talent levels. Its cost list is `[]`, which is the *second*
    distinct signature in her payload — not, as an earlier note in this repo claimed, a
    second real bill. Pair the lists to the wrong skills and a real talent inherits the
    empty one, which reads as "this talent is free".
    """
    rows = talent_cost_rows("10000002", ayaka)
    assert len({row["nanoka_id"] for row in rows}) == 3
    assert len(ayaka["skills"]) == 4
    assert 10013 not in {row["nanoka_id"] for row in rows}
    assert len(rows) == 27


def test_talent_costs_run_one_to_nine_and_end_at_the_crown(ayaka: dict) -> None:
    """Nine steps take a talent to level 10; 11-15 come free from C3/C5 and have no rows."""
    rows = [row for row in talent_cost_rows("10000002", ayaka) if row["nanoka_id"] == 10019]
    assert [row["level"] for row in rows] == list(range(1, 10))
    assert 104319 in {item["id"] for item in rows[-1]["items"]}, "Crown of Insight"
    assert rows[-1]["mora"] == 700000


def test_mismatched_talent_lists_are_refused(ayaka: dict) -> None:
    """The join is positional and there is no key, so a length mismatch cannot be paired."""
    broken = {**ayaka, "materials": {**ayaka["materials"],
                                     "talents": ayaka["materials"]["talents"][:2]}}
    with pytest.raises(NanokaMappingError, match="joined by position"):
        talent_cost_rows("10000002", broken)


def test_weapon_costs_read_the_phase_key(aquila: dict) -> None:
    rows = weapon_ascension_cost_rows(aquila)
    assert [row["phase"] for row in rows] == [1, 2, 3, 4, 5, 6]
    assert rows[0]["mora"] == 10000
    assert rows[5]["mora"] == 65000


def test_exp_curves_are_carried_verbatim(ayaka: dict, aquila: dict) -> None:
    """`level_exp` is per level and not cumulative: the first 89 are the total to 90."""
    level_exp = character_fields("10000002", ayaka)["level_exp"]
    assert len(level_exp) == 90
    assert sum(level_exp[:89]) == 8_362_650
    assert len(weapon_fields("11501", aquila)["xp_requirements"]) == 90


def test_materials_are_collected_from_both_payload_shapes(ayaka: dict, aquila: dict) -> None:
    """One function serves both importers, and it carries name and rarity for each."""
    from_character = material_rows(ayaka)
    from_weapon = material_rows(aquila)
    assert from_character[104161] == {"name": "Shivada Jade Sliver", "rarity": 2}
    assert from_character[104319]["name"] == "Crown of Insight"
    assert 114001 in from_weapon
    assert len(from_character) == 14
    assert len(from_weapon) == 10
