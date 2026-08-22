"""B.3 — mapping this repo's catalogue onto gcsim's config keys.

The failure this guards is not a crash. A wrong-but-plausible key makes gcsim simulate **a
different character** and return a number that looks entirely reasonable — which is worse
than an error, and is why every unmatched name is refused rather than guessed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services.gcsim_keys import (
    GcsimKeyError,
    artifact_set_key,
    character_key,
    normalise,
    pinned_commit,
    weapon_key,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi"


def test_the_snapshot_is_at_the_declared_pin():
    """One pin, from the one document that owns it — see `test_gcsim_pin_is_single.py`."""
    doc = (Path(__file__).resolve().parents[3] / "docs" / "CROSSVAL_gcsim.md").read_text()
    declared = re.search(r"^\| \*\*Commit\*\* \| `([0-9a-f]{40})`", doc, re.M)

    assert declared is not None
    assert pinned_commit() == declared.group(1)


# ---- Normalisation ---------------------------------------------------------

def test_punctuation_and_spacing_are_all_that_differ():
    assert normalise("Gladiator's Finale") == "gladiatorsfinale"
    assert normalise("Kamisato Ayaka") == "kamisatoayaka"


def test_the_key_vocabulary_is_injective_over_the_seeded_catalogue():
    """Two names reducing to one key would bind the wrong entity, invisibly.

    Same property `good_import_service` needs for GOOD's `setKey`, and asserted the same way:
    over the real committed catalogue, not a sample.
    """
    sets = json.loads((FIXTURES / "artifact.json").read_text())
    names = [next(iter(entry["set"].values()))["name"]["en"] for entry in sets.values()]
    collisions = {n for n in names if sum(normalise(m) == normalise(n) for m in names) > 1}

    assert collisions == set()


# ---- Characters ------------------------------------------------------------

def test_a_full_name_resolves():
    """gcsim's *package* is `ayaka`; its *key* is `kamisatoayaka`.

    Reading directory names instead of `pkg/core/keys/*.dm.go` is exactly the mistake the
    first pass at this made — and it would have refused every surname-prefixed character
    while claiming they needed aliases.
    """
    assert character_key("10000002", "Kamisato Ayaka") == "kamisatoayaka"
    assert character_key("10000016", "Kaedehara Kazuha") == "kaedeharakazuha"


def test_a_traveler_is_resolved_from_its_body_and_element():
    """Structured, not aliased: nanoka calls every variant "Traveler" and only the id says
    which body it is."""
    assert character_key("10000005-2", "Traveler", "Pyro") == "aetherpyro"
    assert character_key("10000007-3", "Traveler", "Hydro") == "luminehydro"


def test_a_traveler_without_an_element_is_refused():
    """Picking one would silently simulate a different character."""
    with pytest.raises(GcsimKeyError, match=r"[Ww]ithout the element"):
        character_key("10000005-2", "Traveler")


def test_the_cryo_traveler_is_refused_because_gcsim_has_six_elements():
    with pytest.raises(GcsimKeyError, match="six Traveler elements"):
        character_key("10000005-4", "Traveler", "Cryo")


def test_a_character_newer_than_the_pin_is_refused_naming_it():
    """Not a mapping failure — gcsim cannot simulate what it does not implement, and a
    re-pin is what changes that."""
    with pytest.raises(GcsimKeyError, match="Nefer"):
        character_key("10000122", "Nefer")


# ---- Weapons and sets ------------------------------------------------------

def test_weapons_and_sets_resolve():
    assert weapon_key("Mistsplitter Reforged") == "mistsplitterreforged"
    assert artifact_set_key("Blizzard Strayer") == "blizzardstrayer"
    assert artifact_set_key("Gladiator's Finale") == "gladiatorsfinale"


def test_a_set_gcsim_does_not_implement_is_refused():
    """The five one-piece "Prayers" circlets are real sets that gcsim has no key for."""
    with pytest.raises(GcsimKeyError, match="Prayers for Illumination"):
        artifact_set_key("Prayers for Illumination")


def test_the_refusal_names_the_pin_so_a_re_pin_is_the_obvious_fix():
    with pytest.raises(GcsimKeyError, match=pinned_commit()[:12]):
        weapon_key("Weapon Released After The Pin")
