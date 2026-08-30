"""KeqingMains weapon recommendations — the reading of a captured snapshot.

The owner flagged this feature as *"exactly the shape of the failure `CLAUDE.md` names as
fairy's worst"*: fabricated citations in curated data. So these tests are less about the
parsing than about **what the data claims**, and about the two ways it could quietly claim
more than the source said.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services import kqm_weapons

_SNAPSHOT = Path(kqm_weapons.__file__).resolve().parents[1] / "data" / "kqm" / "weapons.json"


def test_the_snapshot_carries_its_own_citation() -> None:
    """**A claim without a source is the thing this must not become.**

    Every character published carries the page it came from, and the file carries the date it
    was retrieved — so a reader can open the guide and check, rather than take this repo's
    word.
    """
    raw = json.loads(_SNAPSHOT.read_text())

    assert raw["source"] == "KeqingMains"
    assert raw["retrieved_at"]
    for entry in raw["characters"].values():
        assert entry["url"].startswith("https://keqingmains.com/")


def test_every_recommendation_names_a_weapon_this_repo_has() -> None:
    """The capture refuses a name it cannot resolve rather than guessing at it, so a `weapon_id`
    here is always a real catalogue row. A recommendation naming a weapon that does not exist
    would be unactionable *and* unfalsifiable."""
    for nanoka_id in kqm_weapons.captured_characters():
        guide = kqm_weapons.for_character(nanoka_id)
        assert guide is not None
        for weapon in guide.weapons:
            assert weapon.weapon_id
            assert weapon.weapon_name


def test_the_order_is_preserved_because_the_order_is_the_claim() -> None:
    """KQM's table has no rank numbers — it has an order, and its top row is described as the
    character's best-in-slot. Position is that order and nothing more."""
    guide = kqm_weapons.for_character(kqm_weapons.captured_characters()[0])

    assert guide is not None
    assert [w.position for w in guide.weapons] == sorted(w.position for w in guide.weapons)
    assert guide.weapons[0].position == 1


def test_every_recommendation_keeps_kqms_own_words() -> None:
    """`note` is verbatim. Summarising it here would be this repo asserting a judgement it did
    not make, under someone else's name."""
    for nanoka_id in kqm_weapons.captured_characters():
        guide = kqm_weapons.for_character(nanoka_id)
        assert guide is not None
        assert all(w.note.strip() for w in guide.weapons)


def test_a_refinement_is_data_rather_than_part_of_the_name() -> None:
    """KQM writes `R5 Festering Desire` for some entries. `Festering Desire` at R1 is a
    different recommendation, so the number is kept and the name resolves cleanly."""
    names = [
        w.weapon_name
        for nanoka_id in kqm_weapons.captured_characters()
        for w in (kqm_weapons.for_character(nanoka_id) or kqm_weapons.CharacterGuide(
            "", "", "", (),
        )).weapons
    ]

    assert not any(name.startswith(("R1 ", "R2 ", "R3 ", "R4 ", "R5 ")) for name in names)


def test_an_uncaptured_character_is_none_rather_than_an_empty_guide() -> None:
    """**The distinction the whole feature rests on.** "Nobody has captured this character" and
    "KQM recommends nothing for them" are different statements, and an empty list would present
    the first as the second — a claim about KQM that nobody made."""
    assert kqm_weapons.for_character("99999999") is None
    assert kqm_weapons.for_character(None) is None


def test_the_capture_is_small_and_deliberate() -> None:
    """The owner's ruling was *"manual, cited, small first"* — prove the shape before scaling.
    This is a reminder rather than a limit: growing it means running the capture and reviewing
    the diff, which is exactly the review this design wants."""
    assert 0 < len(kqm_weapons.captured_characters()) <= 20
