"""G.5 — reading a GOOD export, and refusing the parts that are not real.

The rule this file is mostly about: **reject, do not coerce.** Genshin Optimizer's schema
defaults an unknown slot to `flower` and an unknown stat to `hp`, which is right for a UI
that must never lose a user's inventory. It is wrong feeding an optimizer, where a
defaulted artifact gets scored as though it existed and a user is recommended a build around
a piece they do not own.
"""

from __future__ import annotations

import pytest

from app.data.importers.good_importer import (
    MAX_LEVEL_BY_RARITY,
    GoodImportError,
    parse_good,
    slot_main_stat_keys,
)
from app.data.snapshot import main_stat_pools
from app.models.enums import ArtifactSlot, Rarity


def _export(*artifacts: dict) -> dict:
    return {
        "format": "GOOD",
        "version": 1,
        "source": "Inventory Kamera",
        "artifacts": list(artifacts),
    }


def _artifact(**overrides) -> dict:
    base = {
        "setKey": "DeepwoodMemories",
        "slotKey": "goblet",
        "level": 20,
        "rarity": 5,
        "mainStatKey": "dendro_dmg_",
        "location": "Nahida",
        "lock": True,
        "substats": [
            {"key": "critRate_", "value": 10.5},
            {"key": "atk_", "value": 9.9},
            {"key": "eleMas", "value": 40},
            {"key": "", "value": 0},
        ],
    }
    return {**base, **overrides}


# ---- The happy path -------------------------------------------------------

def test_a_scanned_artifact_arrives_in_this_repos_vocabulary():
    result = parse_good(_export(_artifact()))
    (artifact,) = result.artifacts

    assert artifact.slot is ArtifactSlot.GOBLET
    assert artifact.rarity is Rarity.FIVE_STAR
    assert artifact.main_stat == "FIGHT_PROP_GRASS_ADD_HURT"
    assert artifact.set_key == "DeepwoodMemories"
    assert artifact.location == "Nahida"
    assert result.ok


def test_percentages_become_fractions_and_flat_stats_do_not():
    """GOOD writes `10.5` for 10.5%; everything here is a fraction. Elemental Mastery is
    flat and must not be divided — a 40 EM substat read as 0.4 is invisible."""
    (artifact,) = parse_good(_export(_artifact())).artifacts
    substats = {entry["stat"]: entry["value"] for entry in artifact.substats}

    assert substats["FIGHT_PROP_CRITICAL"] == pytest.approx(0.105)
    assert substats["FIGHT_PROP_ATTACK_PERCENT"] == pytest.approx(0.099)
    assert substats["FIGHT_PROP_ELEMENT_MASTERY"] == pytest.approx(40.0)


def test_an_empty_substat_slot_is_dropped_rather_than_imported_as_a_stat():
    """A scan of an unupgraded artifact pads its list; GOOD's schema defaults the key to ''."""
    (artifact,) = parse_good(_export(_artifact())).artifacts

    assert len(artifact.substats) == 3
    assert all(entry["stat"] for entry in artifact.substats)


def test_the_source_and_version_survive():
    result = parse_good(_export(_artifact()))

    assert result.source == "Inventory Kamera"
    assert result.version == 1


# ---- Reject, do not coerce ------------------------------------------------

def test_an_unknown_slot_is_rejected_rather_than_defaulted_to_flower():
    result = parse_good(_export(_artifact(slotKey="cape")))

    assert result.artifacts == ()
    assert "unknown slot key 'cape'" in str(result.rejected[0])
    assert not result.ok


def test_an_unknown_main_stat_is_rejected_rather_than_defaulted_to_hp():
    result = parse_good(_export(_artifact(mainStatKey="lunar_dmg_")))

    assert result.artifacts == ()
    assert "unknown main stat key" in str(result.rejected[0])


def test_an_unknown_substat_is_rejected():
    result = parse_good(_export(_artifact(substats=[{"key": "luck_", "value": 5}])))

    assert "unknown substat key 'luck_'" in str(result.rejected[0])


def test_the_rejection_names_the_artifact_and_keeps_the_record():
    """A user with 800 artifacts needs to find the two that failed."""
    result = parse_good(_export(_artifact(), _artifact(slotKey="cape")))

    (rejected,) = result.rejected
    assert rejected.index == 1
    assert rejected.record["slotKey"] == "cape"


def test_one_bad_artifact_does_not_cost_the_user_the_rest():
    result = parse_good(_export(_artifact(), _artifact(slotKey="cape"), _artifact()))

    assert len(result.artifacts) == 2
    assert len(result.rejected) == 1


# ---- Ranges and shapes ----------------------------------------------------

@pytest.mark.parametrize(("rarity", "maximum"), sorted(MAX_LEVEL_BY_RARITY.items()))
def test_the_level_cap_depends_on_rarity(rarity: int, maximum: int):
    """`artMaxLevel`: a 3-star stops at +12 and a 1-star at +4. A +20 three-star is not a
    thing the game can produce, and clamping it would import a fictional piece."""
    ok = parse_good(_export(_artifact(rarity=rarity, level=maximum, mainStatKey="hp_")))
    too_high = parse_good(
        _export(_artifact(rarity=rarity, level=maximum + 1, mainStatKey="hp_")),
    )

    assert ok.ok
    assert "out of range" in str(too_high.rejected[0])


def test_a_negative_level_is_rejected():
    result = parse_good(_export(_artifact(level=-1)))

    assert "out of range" in str(result.rejected[0])


def test_a_boolean_level_is_not_an_integer():
    """`True` is an `int` in Python and would sail through a naive range check as level 1."""
    result = parse_good(_export(_artifact(level=True)))

    assert "out of range" in str(result.rejected[0])


def test_an_unknown_rarity_is_rejected():
    result = parse_good(_export(_artifact(rarity=6)))

    assert "unknown rarity" in str(result.rejected[0])


def test_a_missing_set_key_is_rejected():
    result = parse_good(_export(_artifact(setKey="")))

    assert "setKey" in str(result.rejected[0])


def test_a_substat_with_no_key_but_a_value_is_rejected():
    """Neither "no substat here" nor a known one — so it is not something to guess at."""
    result = parse_good(_export(_artifact(substats=[{"key": "", "value": 12}])))

    assert "no key carries a value" in str(result.rejected[0])


def test_a_non_numeric_stat_value_is_rejected():
    result = parse_good(_export(_artifact(substats=[{"key": "atk_", "value": "9.9"}])))

    assert "must be a number" in str(result.rejected[0])


# ---- The envelope ---------------------------------------------------------

def test_a_file_that_is_not_good_is_refused_outright():
    with pytest.raises(GoodImportError, match="not a GOOD export"):
        parse_good({"format": "MONA", "version": 1})


def test_an_unsupported_version_is_refused():
    """A newer version may have changed field meanings; reading it as though it had not is
    how a silently wrong inventory gets imported."""
    with pytest.raises(GoodImportError, match="version 4 is not supported"):
        parse_good({"format": "GOOD", "version": 4})


def test_something_that_is_not_an_object_is_refused():
    with pytest.raises(GoodImportError, match="is a JSON object"):
        parse_good(["not", "an", "export"])


def test_an_export_with_no_artifacts_is_valid_and_empty():
    """A scanner that found nothing is not an error."""
    result = parse_good({"format": "GOOD", "version": 3, "source": "x"})

    assert result.artifacts == ()
    assert result.ok


def test_an_artifact_that_is_not_an_object_is_rejected_not_crashed_on():
    result = parse_good(_export("nonsense"))

    assert "expected an object" in str(result.rejected[0])


# ---- The cross-source check -----------------------------------------------

def test_genshin_optimizers_slot_pools_agree_with_the_ones_we_derived():
    """**Two independent derivations of the same table.**

    E.5 derived the per-slot main-stat pools by joining datamined config tables and
    cross-checking their cardinalities. Genshin Optimizer maintains its list by hand. They
    agree exactly — 1/1/5/12/7 — which is much stronger evidence than either alone.

    If this ever fails, one of them is wrong and it matters a great deal which: ours feeds
    the optimizer's candidate generation.
    """
    theirs = slot_main_stat_keys()
    ours = main_stat_pools()

    assert sorted(theirs) == sorted(ours)
    for slot in ours:
        assert set(theirs[slot]) == set(ours[slot]), slot


def test_a_substat_that_is_not_an_object_is_rejected_not_crashed_on():
    """A hand-edited or half-written export should produce a rejection, not a traceback."""
    result = parse_good(_export(_artifact(substats=["critRate_ 10.5"])))

    assert "substat entries must be objects" in str(result.rejected[0])


# ---- The PR #9 review's findings ------------------------------------------

def test_a_slot_that_cannot_roll_the_main_stat_is_rejected_at_import():
    """Checking the stat key against the flat vocabulary is not enough: a flower with CRIT
    DMG passes that and is not a thing.

    One scanner misread would otherwise import cleanly and then raise from inside the
    optimizer's hot loop — turning 798 good artifacts into a search that dies partway
    through, which is the failure this importer exists to prevent.
    """
    result = parse_good(_export(_artifact(slotKey="flower", mainStatKey="critDMG_")))

    assert result.artifacts == ()
    assert "cannot roll" in str(result.rejected[0])


def test_a_plume_must_carry_flat_attack():
    result = parse_good(_export(_artifact(slotKey="plume", mainStatKey="def")))

    assert "cannot roll" in str(result.rejected[0])


def test_a_legal_pair_for_every_slot_is_accepted():
    """The other side of the check: the pools it validates against are the real ones."""
    for slot, key in (
        ("flower", "hp"), ("plume", "atk"), ("sands", "enerRech_"),
        ("goblet", "pyro_dmg_"), ("circlet", "critRate_"),
    ):
        result = parse_good(_export(_artifact(slotKey=slot, mainStatKey=key)))
        assert result.ok, (slot, key, result.rejected)


def test_a_boolean_rarity_is_not_a_one_star():
    """`True == 1` in Python, so it would have imported as a one-star with a +4 cap."""
    result = parse_good(_export(_artifact(rarity=True)))

    assert "unknown rarity" in str(result.rejected[0])


def test_a_boolean_version_is_not_version_one():
    with pytest.raises(GoodImportError, match="is not supported"):
        parse_good({"format": "GOOD", "version": True})
