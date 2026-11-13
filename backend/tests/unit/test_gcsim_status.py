"""Task 3 of the formula fallback: gcsim status on catalogue entries, computed on read.

The statuses are checked against the reviewed coverage list
(`tests/fixtures/gcsim_character_coverage.json`) rather than against themselves: `none` must be
**exactly** the characters that fixture lists, so the badge and the L6 successor test cannot
disagree about who gcsim can simulate.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from app.models.enums import WeaponType
from app.schemas.catalogue import ArtifactSetRead, CharacterSummary, WeaponSummary
from app.services import gcsim_keys, gcsim_status
from app.services.gcsim_status import GcsimSupport

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
COVERAGE = json.loads((FIXTURES / "gcsim_character_coverage.json").read_text())
CHARACTERS = json.loads((FIXTURES / "nanoka_gi" / "character.json").read_text())
WEAPONS = json.loads((FIXTURES / "nanoka_gi" / "weapon.json").read_text())


def _status(nanoka_id: str) -> gcsim_status.GcsimStatus:
    body = CHARACTERS[nanoka_id]
    return gcsim_status.for_character(nanoka_id, body["en"], body.get("element"), body["weapon"])


def _all() -> dict[str, gcsim_status.GcsimStatus]:
    return {nanoka_id: _status(nanoka_id) for nanoka_id in CHARACTERS}


def test_none_is_exactly_the_reviewed_coverage_list():
    none = {k for k, s in _all().items() if s.status is GcsimSupport.NONE}
    assert none == {entry["nanoka_id"] for entry in COVERAGE["unimplemented"]}


def test_the_coverage_list_is_at_the_same_pin_as_the_answer():
    assert {s.pin for s in _all().values()} == {COVERAGE["pinned_commit_sha"]}


def test_the_distribution_at_the_pin():
    """Pinned so a re-pin that moves anyone is a diff someone reads.

    Before the owner's plunge ruling (2026-11-13) this was 39 / 89 / 22, and 70 of the 89 lacked
    only `high_plunge`/`low_plunge`. Those 70, plus 5 lacking one plunge, are `full` now: 14
    `partial` characters remain, every one missing a charged attack.
    """
    assert Counter(s.status for s in _all().values()) == {
        GcsimSupport.FULL: 114, GcsimSupport.PARTIAL: 14, GcsimSupport.NONE: 22,
    }
    plunges_only = sum(
        1 for s in _all().values() if s.missing_actions == ("high_plunge", "low_plunge")
    )
    assert plunges_only == 70


def test_none_carries_gcsims_refusal_and_no_key():
    for status in _all().values():
        if status.status is GcsimSupport.NONE:
            assert status.key is None
            assert "gcsim has no" in (status.reason or "")
            assert status.missing_actions == ()


def test_full_and_partial_carry_the_key_and_no_reason():
    for status in _all().values():
        if status.status is not GcsimSupport.NONE:
            assert status.key
            assert status.reason is None
            core_missing = gcsim_status.CORE_ACTIONS.intersection(status.missing_actions)
            assert bool(core_missing) == (status.status is GcsimSupport.PARTIAL)


def test_missing_plunges_alone_are_full_but_still_listed():
    """Owner, 2026-11-13: partial only for a missing normal, charged/aimed, skill or burst.

    The plunges stay in `missing_actions`, so the tooltip still says gcsim cannot plunge.
    """
    plunge_only = [
        s for s in _all().values()
        if s.missing_actions and set(s.missing_actions) <= {"high_plunge", "low_plunge"}
    ]
    assert len(plunge_only) == 75
    assert {s.status for s in plunge_only} == {GcsimSupport.FULL}


def test_diluc_lacking_a_charged_attack_and_plunges_is_partial():
    statuses = [s for s in _all().values() if "charge" in s.missing_actions]
    assert statuses
    assert {s.status for s in statuses} == {GcsimSupport.PARTIAL}


def test_a_sword_user_is_not_partial_for_want_of_an_aimed_shot():
    """Taken literally, every non-bow character would lack `aim`. Ayaka lacks nothing."""
    ayaka = _status("10000002")
    assert (ayaka.status, ayaka.key, ayaka.missing_actions) == (
        GcsimSupport.FULL, "kamisatoayaka", (),
    )


def test_a_bow_user_is_not_partial_for_want_of_a_charged_attack():
    """A bow's charged attack *is* `aim`. Ganyu's gap is her plunges, not `charge`."""
    ganyu = next(k for k, b in CHARACTERS.items() if b["en"] == "Ganyu")
    assert "charge" not in _status(ganyu).missing_actions
    assert "aim" not in gcsim_status.expected_actions(WeaponType.SWORD)
    assert "charge" not in gcsim_status.expected_actions(WeaponType.BOW)
    assert "aim" in gcsim_status.expected_actions(WeaponType.BOW)


def test_a_claymore_without_a_charged_attack_is_partial_and_says_so():
    diluc = next(k for k, b in CHARACTERS.items() if b["en"] == "Diluc")
    assert _status(diluc).missing_actions == ("charge",)


def test_a_traveler_resolves_by_element():
    pyro = _status("10000005-2")
    assert pyro.key == "aetherpyro"


def test_weapons_take_two_statuses_and_agree_with_the_key_lookup():
    seen = Counter()
    for body in WEAPONS.values():
        name = body.get("en") or ""
        status = gcsim_status.for_weapon(name)
        seen[status.status] += 1
        try:
            assert status.key == gcsim_keys.weapon_key(name)
        except gcsim_keys.GcsimKeyError:
            assert status.status is GcsimSupport.NONE
    assert GcsimSupport.PARTIAL not in seen
    assert seen[GcsimSupport.FULL] > seen[GcsimSupport.NONE] > 0


def test_a_set_gcsim_has_and_one_it_does_not():
    assert gcsim_status.for_artifact_set("Blizzard Strayer").key == "blizzardstrayer"
    assert gcsim_status.for_artifact_set("Adventurer").status is GcsimSupport.NONE


@pytest.mark.parametrize(
    ("schema", "fields"),
    [
        (
            CharacterSummary,
            {"id": "x", "nanoka_id": "10000002", "name": "Kamisato Ayaka", "element": "Cryo",
             "weapon_type": WeaponType.SWORD, "rarity": "five_star"},
        ),
        (
            WeaponSummary,
            {"id": "x", "nanoka_id": 11501, "name": "Aquila Favonia",
             "weapon_type": WeaponType.SWORD, "rarity": "five_star"},
        ),
        (ArtifactSetRead, {"id": "x", "nanoka_id": 15003, "name": "Blizzard Strayer"}),
    ],
)
def test_the_block_is_on_the_wire(schema, fields):
    dumped = schema(**fields).model_dump(mode="json")
    assert dumped["gcsim"] == {
        "status": "full",
        "key": dumped["gcsim"]["key"],
        "pin": gcsim_keys.pinned_commit(),
        "missing_actions": [],
        "reason": None,
    }
    assert dumped["gcsim"]["key"]
