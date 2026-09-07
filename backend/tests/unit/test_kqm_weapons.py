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

#: For the one comprehension that reads a guide it has already asserted is present.
_EMPTY = kqm_weapons.CharacterGuide(character="", url="", retrieved_at="", weapons=())


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
    """The capture refuses a name it cannot resolve rather than guessing at it, so every row
    here names a weapon the catalogue holds. A recommendation naming one that does not exist
    would be unactionable *and* unfalsifiable.

    **`assert weapon.weapon_id` used to be this test**, and it could not return a second
    answer: any string, from any database or none, passed it. It passed for months while the
    ids it was checking existed in exactly one database.
    """
    for nanoka_id in kqm_weapons.captured_characters():
        guide = kqm_weapons.for_character(nanoka_id)
        assert guide is not None
        for weapon in guide.weapons:
            assert isinstance(weapon.weapon_nanoka_id, int)
            assert weapon.weapon_name


#: What a `uuid7` primary key looks like. Not a general UUID pattern — the point is to
#: recognise *this repo's own row ids*, which is what got committed.
_ROW_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")


def test_no_id_in_the_snapshot_is_a_row_id_from_somebody_s_database() -> None:
    """**The check on the class of mistake, not on the instance.**

    `weapon_id` and `set_id` held `uuid7` primary keys until 2026-09-04. `models/base.py` mints
    those per insert, so the file described whichever database the capture happened to run
    against — **zero of the 205 weapon ids and zero of the 32 set ids existed in production**,
    and every recommendation silently missed. Nothing errored; both pickers just looked like
    pickers with no guide.

    A committed snapshot must not carry a primary key from anybody's database. Asserting the
    ids are *ints* would pass a re-capture that reintroduced a row id under a new field name;
    this fails on the shape wherever it appears.
    """
    raw = json.loads(_SNAPSHOT.read_text())
    offenders = [
        (nanoka_id, key, value)
        for nanoka_id, entry in raw["characters"].items()
        for row in [*entry["weapons"], *entry.get("sets", [])]
        for key, value in row.items()
        if isinstance(value, str) and _ROW_ID.match(value)
    ]

    assert offenders == []


def test_a_named_set_is_not_filed_as_a_stat_description() -> None:
    """`kind` separates a set from a *kind* of two-piece, and the distinction is load-bearing —
    `2pc HP% / ER` names every set granting HP%, not a set, and resolving it would invent a
    name KQM never wrote.

    But a trailing qualifier used to sink the row: `4pc Emblem of Severed Fate (EoSF)` matched
    nothing and was filed `stat` along with 46 others, so a quarter of the set half named a set
    and did not say so.

    The signature is narrow on purpose. A cell naming *several* sets — Albedo's
    `4pc Tenacity of the Millelith (4ToM), 4pc Noblesse Oblige (4NO), or 4pc Instructor (4IN)` —
    is correctly a `stat` row, because it resolves to no single set. What must not survive is a
    `stat` row whose whole text is **one** set this snapshot elsewhere names outright.
    """
    named = {
        entry.set_name
        for nanoka_id in kqm_weapons.captured_characters()
        for entry in (kqm_weapons.for_character(nanoka_id) or _EMPTY).sets
        if entry.set_name
    }
    strip = re.compile(r"^(?:[24]pc(?:\s*/\s*[24]pc)?)\s+|\s*\([^)]*\)\s*$")

    for nanoka_id in kqm_weapons.captured_characters():
        guide = kqm_weapons.for_character(nanoka_id)
        assert guide is not None
        for entry in guide.sets:
            if entry.kind != "stat":
                continue
            bare = strip.sub("", strip.sub("", entry.as_written)).strip()

            assert bare not in named, (
                f"{entry.as_written!r} on {guide.character} is filed as a stat description "
                f"while {bare!r} is a set this snapshot names elsewhere"
            )


def test_a_set_row_carries_an_id_exactly_when_it_names_a_set() -> None:
    """`kind` and `set_nanoka_id` must agree: a `set` row resolves to one, a `stat` row does
    not. They are written together and could drift apart in a re-capture."""
    for nanoka_id in kqm_weapons.captured_characters():
        guide = kqm_weapons.for_character(nanoka_id)
        assert guide is not None
        for entry in guide.sets:
            assert (entry.set_nanoka_id is not None) == (entry.kind == "set"), entry.as_written


#: The committed nanoka 7.0.51 capture, read rather than the database **so this check can
#: never pass by being skipped** — the rule `test_roster_excludes_only_the_mannequins.py`
#: follows, and the one this bug spent months on the wrong side of.
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi"


def test_every_id_resolves_against_the_catalogue() -> None:
    """**The check that would have caught it.**

    Nothing joined this snapshot to the catalogue, so an id that meant nothing anywhere looked
    exactly like one that meant something. Against production it meant nothing: 0 of 205 weapon
    ids and 0 of 32 set ids resolved, and both pickers rendered as though no guide existed.

    Reading the committed fixtures rather than a seeded database is deliberate — an
    integration test guarded on a database is a test that reports "could not check" as a pass,
    which is the exact state the bug lived in.
    """
    weapons = {int(key) for key in json.loads((_FIXTURES / "weapon.json").read_text())}
    sets = {int(key) for key in json.loads((_FIXTURES / "artifact.json").read_text())}

    unresolved = []
    for nanoka_id in kqm_weapons.captured_characters():
        guide = kqm_weapons.for_character(nanoka_id)
        assert guide is not None
        unresolved += [
            f"{guide.character}: weapon {w.weapon_nanoka_id} ({w.weapon_name})"
            for w in guide.weapons if w.weapon_nanoka_id not in weapons
        ]
        unresolved += [
            f"{guide.character}: set {e.set_nanoka_id} ({e.set_name})"
            for e in guide.sets
            if e.set_nanoka_id is not None and e.set_nanoka_id not in sets
        ]

    assert unresolved == []


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


def test_a_set_row_position_is_not_a_unique_key() -> None:
    """`position` repeats within a character's set rows, and a client keying on it breaks.

    **This asserts the mess rather than tidying it, because the mess is KQM's and correct.**
    A guide lists the same advice under each playstyle it applies to and the position is
    per-section, so Hu Tao carries 16 stat rows across 8 positions. That is their table read
    faithfully; renumbering it here would be this repo imposing an order on someone else's
    page.

    It exists because the optimizer's advice list was written as
    `@for (advice of setAdvice(); track advice.position)`, and Angular throws **NG0955** on a
    duplicated track key — so the panel rendered for the 93 characters whose positions happen
    not to collide and threw for the other 9. No unit test saw it: every spec on that page
    reads the computed and none render the template.

    So the guard is here, on the property that made it possible, rather than on a template
    nothing in this suite renders.
    """
    repeated = []
    for nanoka_id in kqm_weapons.captured_characters():
        guide = kqm_weapons.for_character(nanoka_id)
        assert guide is not None
        positions = [entry.position for entry in guide.sets]
        if len(positions) != len(set(positions)):
            repeated.append(guide.character)

    assert repeated, (
        "No captured guide repeats a set-row position any more. If a re-capture really did "
        "make them unique, this test should be deleted deliberately rather than relaxed — and "
        "the clients that track by index are still correct."
    )
