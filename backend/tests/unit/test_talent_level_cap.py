"""Owner ruling, 2026-11-14: a stored talent level is a base level, capped at 10.

GOOD exports the level without constellation boosts and gcsim refuses one above 10
(`character.go:163-174`). The editor used to accept 1-15, which suggested a stored level could
already include the C3/C5 boost — and #374 refuses exactly that on a boosted talent, so a 13
saved through the editor would then fail every hit read. The cap is now enforced on every
write path, and the boosted level is published beside the stored one instead of being typed
into it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.data.importers.good_importer import parse_good
from app.models.enums import MAX_STORED_TALENT_LEVEL, MAX_TALENT_LEVEL
from app.schemas.build import BuildCreate, BuildRead, BuildUpdate
from app.schemas.catalogue import CharacterSummary
from app.services import talent_boosts

STORED = {"normal_attack": 9, "elemental_skill": 9, "elemental_burst": 9}

XIANGLING = {
    "id": "c1", "nanoka_id": "10000023", "name": "Xiangling", "element": "Pyro",
    "weapon_type": "WEAPON_POLE", "rarity": "four_star",
}
NOBODY = {**XIANGLING, "nanoka_id": "99999999", "name": "Nobody In Particular"}


# ── the cap ──────────────────────────────────────────────────────────────────


def test_the_stored_cap_is_ten_and_the_boosts_fit_inside_the_scaling_table():
    """Ten base levels plus two +3 boosts is 16 — but no character is boosted twice on one
    talent, so the highest level ever read is 13, which the 15-row table covers."""
    assert MAX_STORED_TALENT_LEVEL == 10
    assert talent_boosts.BASE_TALENT_CAP == MAX_STORED_TALENT_LEVEL
    assert MAX_STORED_TALENT_LEVEL + talent_boosts.BOOST <= MAX_TALENT_LEVEL


@pytest.mark.parametrize("schema", [BuildCreate, BuildUpdate])
def test_eleven_is_refused_on_create_and_on_update(schema):
    body = {"talent_levels": {"elemental_burst": 11}}
    if schema is BuildCreate:
        body["character_id"] = "c1"

    with pytest.raises(ValidationError, match="without constellation boosts"):
        schema.model_validate(body)


@pytest.mark.parametrize("schema", [BuildCreate, BuildUpdate])
def test_ten_is_accepted(schema):
    body = {"talent_levels": {"elemental_burst": 10}}
    if schema is BuildCreate:
        body["character_id"] = "c1"

    assert schema.model_validate(body).talent_levels == {"elemental_burst": 10}


# ── the read publishes the boosted level ─────────────────────────────────────


def _read(constellation: int, character: dict | None = XIANGLING, **over) -> BuildRead:
    return BuildRead.model_validate({
        "id": "b1", "character_id": "c1", "weapon_id": None,
        "character_level": 90, "ascension_phase": 6, "weapon_level": 90,
        "refinement": 1, "constellation_level": constellation,
        "talent_levels": STORED, "character": character,
    } | over)


def test_a_c3_build_reads_its_boosted_talent_three_higher():
    read = _read(3)

    assert read.talent_levels == STORED, "the stored level is never rewritten"
    assert read.effective_talent_levels == {**STORED, "elemental_burst": 12}
    assert read.talent_boost_refusal is None


def test_a_c6_build_reads_both_boosted_talents():
    assert _read(6).effective_talent_levels == {
        **STORED, "elemental_skill": 12, "elemental_burst": 12,
    }


def test_below_c3_the_effective_levels_are_the_stored_ones():
    assert _read(2).effective_talent_levels == STORED


def test_an_uncovered_character_from_c3_is_refused_by_name_rather_than_guessed():
    """#374's rule, carried to the read: no table, no boosted number — and the reason, so the
    editor can say why there is no "→ 12" rather than showing nothing."""
    read = _read(3, character=NOBODY)

    assert read.effective_talent_levels is None
    assert read.talent_boost_refusal is not None
    assert "Nobody In Particular" in read.talent_boost_refusal


def test_a_build_with_no_character_reads_its_stored_levels():
    read = _read(6, character=None)

    assert read.effective_talent_levels == STORED
    assert read.talent_boost_refusal is None


# ── the character publishes its table, so an editor can follow a constellation edit ──


def test_a_character_publishes_which_constellation_boosts_which_talent():
    summary = CharacterSummary.model_validate(XIANGLING)

    assert summary.talent_boosts is not None
    assert [boost.model_dump() for boost in summary.talent_boosts] == [
        {"talent": "elemental_burst", "constellation": 3, "levels": 3},
        {"talent": "elemental_skill", "constellation": 5, "levels": 3},
    ], "in constellation order, so an editor can list them as they unlock"


def test_a_character_no_table_covers_publishes_none_not_an_empty_list():
    """An empty list would read as "nothing is boosted", which is a claim; `None` is "unknown"."""
    assert CharacterSummary.model_validate(NOBODY).talent_boosts is None


# ── GOOD import: an out-of-range level refuses that character's build ───────


def _export(talent: object) -> dict:
    return {
        "format": "GOOD", "version": 2, "source": "test",
        "characters": [{
            "key": "Xiangling", "level": 90, "ascension": 6, "constellation": 6,
            "talent": talent,
        }],
    }


def test_an_in_range_export_carries_its_levels_and_no_refusal():
    parsed = parse_good(_export({"auto": 9, "skill": 10, "burst": 1}))
    (character,) = parsed.characters

    assert character.talents == {
        "normal_attack": 9, "elemental_skill": 10, "elemental_burst": 1,
    }
    assert character.talent_refusal is None


@pytest.mark.parametrize("level", [11, 13, 0, -2, 9.5])
def test_an_out_of_range_level_is_refused_with_its_reason(level: object):
    """Refused, not clamped. A 13 is almost always a level read *with* the boost — clamping it
    to 10 would silently score a C3 burst at 13 again, which is the double count."""
    parsed = parse_good(_export({"auto": 9, "skill": 9, "burst": level}))
    (character,) = parsed.characters

    assert character.talent_refusal is not None
    assert "burst" in character.talent_refusal
    assert str(level) in character.talent_refusal


def test_a_level_the_export_omits_is_still_level_one():
    """Absent is "the export did not say" — the old fallback, unchanged. Only a number that is
    present and out of range is a refusal."""
    parsed = parse_good(_export({"auto": 9}))
    (character,) = parsed.characters

    assert character.talents["elemental_burst"] == 1
    assert character.talent_refusal is None
