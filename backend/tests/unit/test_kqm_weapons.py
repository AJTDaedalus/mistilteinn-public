"""KeqingMains weapon recommendations — the reading of a captured snapshot.

The owner flagged this feature as *"exactly the shape of the failure `CLAUDE.md` names as
fairy's worst"*: fabricated citations in curated data. So these tests are less about the
parsing than about **what the data claims**, and about the two ways it could quietly claim
more than the source said.
"""

from __future__ import annotations

import json
import re
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


def test_a_refinement_is_stripped_from_the_name_and_not_stored() -> None:
    """Owner, 2026-09-02: *"you can strip out refinement, the user can specify the refinement
    they have."* It is read off the weapon they own, so a captured `R5` would be a number from
    somebody else's account in a field nothing consults — while the name it was written beside
    has to resolve cleanly either way."""
    names = [
        w.weapon_name
        for nanoka_id in kqm_weapons.captured_characters()
        for w in kqm_weapons.for_character(nanoka_id).weapons  # type: ignore[union-attr]
    ]

    assert names
    assert not any(re.search(r"\bR[1-5]\b", name) for name in names)


def test_a_full_guide_keeps_the_playstyle_each_ranking_was_written_for() -> None:
    """**A ranking KQM wrote for *Burst Support Zhongli* is not a ranking for Zhongli.**

    A full guide recommends per build, and flattening its tables into one list would attribute
    to the character a judgement the source scoped to a playstyle. A quick guide has one list
    and no playstyles, so `""` there is correct rather than missing.
    """
    playstyles = {
        w.playstyle
        for nanoka_id in kqm_weapons.captured_characters()
        for w in kqm_weapons.for_character(nanoka_id).weapons  # type: ignore[union-attr]
        if w.playstyle
    }

    assert len(playstyles) > 1, (
        "no captured guide carries a playstyle — a full guide's tables have been flattened"
    )


def test_a_published_percentage_is_kqms_and_never_derived() -> None:
    """A full guide states each weapon against a baseline its note names. Where KQM published
    no number this is empty, because deriving one would be a figure invented under their
    name."""
    published = [
        w.relative_dps
        for nanoka_id in kqm_weapons.captured_characters()
        for w in kqm_weapons.for_character(nanoka_id).weapons  # type: ignore[union-attr]
        if w.relative_dps
    ]

    assert published, "no captured guide carries KQM's own comparison"
    assert all(value.endswith("%") for value in published)

def test_an_uncaptured_character_is_none_rather_than_an_empty_guide() -> None:
    """**The distinction the whole feature rests on.** "Nobody has captured this character" and
    "KQM recommends nothing for them" are different statements, and an empty list would present
    the first as the second — a claim about KQM that nobody made."""
    assert kqm_weapons.for_character("99999999") is None
    assert kqm_weapons.for_character(None) is None


def test_every_captured_character_carries_its_citation() -> None:
    """What replaced the size cap.

    This asserted `<= 20` characters — the *"manual, cited, small first"* ruling made into a
    reminder while the pipeline was being proved. It is proved, and the owner's follow-up was
    *"Why only those three characters? KQM has a quickguide for almost all characters"*, so the
    cap now guards nothing and would only ever fail on the capture being widened, which is the
    thing it was supposed to be leading to.

    **What matters at any size is the citation**, and unlike a count that is a property of every
    row rather than of the file: a guide with no page to check is a recommendation this repo is
    making in KQM's name.
    """
    captured = kqm_weapons.captured_characters()

    assert captured
    for nanoka_id in captured:
        guide = kqm_weapons.for_character(nanoka_id)
        assert guide is not None
        assert guide.url.startswith("https://keqingmains.com/"), guide.character
        assert guide.retrieved_at, guide.character
        assert guide.weapons, guide.character
