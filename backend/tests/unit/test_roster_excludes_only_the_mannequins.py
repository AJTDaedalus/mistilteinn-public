"""The mannequin prefixes still name the mannequins, and nothing else.

`DESIGN_character_roster.md` §2.2. `services/roster.py` excludes Genshin Optimizer's practice
dummies from the roster **by nanoka id prefix**, because a name match on `"Manekin"` is fragile
across localisations — the fixture proves the point, since these rows carry `en`/`ja`/`ko`/`zh`
and no single `name` at all.

**A prefix is only safe while it still means what it meant**, and this is the check that keeps
it honest. It reads the committed nanoka 7.0.51 capture rather than the database, for the reason
`test_genshin_enums.py` does: the fixture is always present, so this gate can never pass by being
skipped — which is this repo's standing rule about checks that could not run.

The failure it exists to prevent is one-directional and quiet: a prefix that silently widened
would drop a real character off the roster, and a roster missing a character is exactly the
defect this whole design was written to fix.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.roster import (
    MANNEQUIN_ID_PREFIXES,
    MANNEQUIN_ROW_COUNT,
    is_mannequin,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "character.json"

#: What the dummies are called in the capture's English field, and the art they carry.
_EXPECTED_NAMES = {"Manekin", "Manekina"}
_EXPECTED_ICONS = {"UI_AvatarIcon_MannequinBoy", "UI_AvatarIcon_MannequinGirl"}


def _catalogue() -> dict[str, dict]:
    return json.loads(FIXTURE.read_text())


def test_the_prefixes_match_exactly_the_expected_number_of_rows() -> None:
    """Fourteen: two dummies, seven elemental variants each.

    A capture that changes this is a change in *who can be owned*, and it should stop a build
    rather than quietly alter the roster.
    """
    matched = [key for key in _catalogue() if is_mannequin(key)]

    assert len(matched) == MANNEQUIN_ROW_COUNT


def test_every_matched_row_really_is_a_mannequin() -> None:
    """The direction that matters. A widened prefix hides a real character, and a roster
    missing a character is the exact defect this design exists to fix."""
    catalogue = _catalogue()
    matched = {key: row for key, row in catalogue.items() if is_mannequin(key)}

    assert {row.get("en") for row in matched.values()} == _EXPECTED_NAMES
    assert {row.get("icon") for row in matched.values()} == _EXPECTED_ICONS


def test_no_real_character_is_excluded() -> None:
    """Named explicitly, because these three are how the owner found the bug.

    Dahlia, Yun Jin and Ningguang are three of the twelve characters that had no build and so
    no ownership record. If a prefix change ever swallowed one of them, the symptom would be
    identical to the original bug and this names it instead.
    """
    catalogue = _catalogue()
    by_name = {row.get("en"): key for key, row in catalogue.items()}

    for name in ("Dahlia", "Yun Jin", "Ningguang", "Amber", "Traveler"):
        key = by_name.get(name)
        assert key is not None, f"{name} is missing from the capture"
        assert not is_mannequin(key), f"{name} was excluded as a mannequin"


def test_the_prefixes_are_disjoint_from_every_other_id() -> None:
    """No non-mannequin id may start with one of these, which is the property that makes a
    prefix a safe way to name a set of rows at all."""
    catalogue = _catalogue()
    non_mannequins = [
        key for key, row in catalogue.items() if row.get("en") not in _EXPECTED_NAMES
    ]

    assert not [
        key for key in non_mannequins if key.startswith(MANNEQUIN_ID_PREFIXES)
    ]
