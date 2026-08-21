"""E.5/E.6 — the committed YuanShenResources snapshot, and that nothing fetches it at run time.

These are the tests that make the snapshot a contract rather than a cache. Everything here
reads the committed files; **nothing here touches the network**, which is also what
`test_no_module_fetches_at_import` is about.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.artifact import MAIN_STAT_POOL, main_stats_for
from app.models.enums import ArtifactSlot, StatType

_SNAPSHOT = Path(__file__).resolve().parents[2] / "app" / "data" / "yuanshen" / "snapshot"
_SCHEMA = Path(__file__).resolve().parents[2] / "app" / "data" / "yuanshen" / "schema"

_FILES = (
    "artifact_main_stat_pools",
    "artifact_main_stat_values",
    "artifact_substat_values",
    "growth_curves",
)


def _load(name: str) -> dict:
    return json.loads((_SNAPSHOT / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", _FILES)
def test_every_snapshot_file_is_committed_and_names_its_commit(name: str):
    """A snapshot that is not committed is a cache, and a cache is not a citation."""
    payload = _load(name)
    pinned = json.loads((_SCHEMA / "provenance.json").read_text(encoding="utf-8"))

    assert payload["pinned_commit_sha"] == pinned["pinned_commit_sha"]
    assert payload["sources"], "a snapshot must name the tables it came from"


def test_the_snapshot_and_the_table_catalog_agree_on_their_commit():
    catalog = json.loads((_SCHEMA / "table_catalog.json").read_text(encoding="utf-8"))
    pinned = json.loads((_SCHEMA / "provenance.json").read_text(encoding="utf-8"))

    assert catalog["pinned_commit_sha"] == pinned["pinned_commit_sha"]
    assert catalog["table_count"] > 1000, "the tree read must have followed its pagination"


def test_every_slot_has_a_main_stat_pool():
    """C.5 left this empty; if it is empty again, the snapshot went missing."""
    assert set(MAIN_STAT_POOL) == set(ArtifactSlot)
    assert all(pool for pool in MAIN_STAT_POOL.values())


def test_the_fixed_main_stat_slots_are_fixed():
    """Flower and plume are the two pools derivable without any id mapping at all."""
    assert main_stats_for(ArtifactSlot.FLOWER) == (StatType.HP_FLAT,)
    assert main_stats_for(ArtifactSlot.PLUME) == (StatType.ATK_FLAT,)


def test_the_rolled_pools_have_the_sizes_the_source_declares():
    """The cardinalities the two scheme tables agree on: 1, 1, 5, 12, 7."""
    sizes = {slot: len(main_stats_for(slot)) for slot in ArtifactSlot}

    assert sizes == {
        ArtifactSlot.FLOWER: 1,
        ArtifactSlot.PLUME: 1,
        ArtifactSlot.SANDS: 5,
        ArtifactSlot.GOBLET: 12,
        ArtifactSlot.CIRCLET: 7,
    }


def test_no_pool_contains_a_stat_that_slot_cannot_roll():
    """The depot lists are supersets; these are the entries the derivation had to remove.

    A sands' depot contains all seven RES-shred props and flat HP/ATK/DEF, and a goblet's
    and circlet's contain the flats. Taking the depot union would have produced pools that
    look sourced and let the optimizer build a sands with Pyro RES as its main stat.
    """
    for slot in (ArtifactSlot.SANDS, ArtifactSlot.GOBLET, ArtifactSlot.CIRCLET):
        pool = main_stats_for(slot)
        assert StatType.HP_FLAT not in pool
        assert StatType.ATK_FLAT not in pool
        assert StatType.DEF_FLAT not in pool
    assert StatType.PYRO_RES not in main_stats_for(ArtifactSlot.SANDS)
    assert StatType.ELECTRO_RES not in main_stats_for(ArtifactSlot.SANDS)


def test_only_the_goblet_rolls_elemental_damage_bonuses():
    for element_stat in (StatType.PYRO_DMG_BONUS, StatType.DENDRO_DMG_BONUS):
        assert element_stat in main_stats_for(ArtifactSlot.GOBLET)
        assert element_stat not in main_stats_for(ArtifactSlot.CIRCLET)
        assert element_stat not in main_stats_for(ArtifactSlot.SANDS)


def test_only_the_circlet_rolls_crit():
    for crit in (StatType.CRIT_RATE, StatType.CRIT_DMG):
        assert crit in main_stats_for(ArtifactSlot.CIRCLET)
        assert crit not in main_stats_for(ArtifactSlot.GOBLET)
        assert crit not in main_stats_for(ArtifactSlot.SANDS)


def test_only_the_sands_rolls_energy_recharge():
    assert StatType.ENERGY_RECHARGE in main_stats_for(ArtifactSlot.SANDS)
    assert StatType.ENERGY_RECHARGE not in main_stats_for(ArtifactSlot.GOBLET)
    assert StatType.ENERGY_RECHARGE not in main_stats_for(ArtifactSlot.CIRCLET)


def test_the_growth_curves_cover_what_the_seeded_enemies_reference():
    """D.6 stored curve *names* on `enemy_profiles`; this is the table they resolve against."""
    curves = _load("growth_curves")["curves"]

    for name in ("GROW_CURVE_HP", "GROW_CURVE_ATTACK", "GROW_CURVE_DEFENSE"):
        entry = curves["monster"][name]
        assert entry["arith"] in {"ARITH_MULTI", "ARITH_ADD"}
        assert entry["levels"]["1"] > 0
        # 200 monster levels are published; a Hilichurl's curve base is only usable with them.
        assert len(entry["levels"]) == 200


def test_a_curve_records_its_arithmetic_rather_than_assuming_multiplication():
    """`GROW_CURVE_STRIKE` is ARITH_ADD — found by asserting uniformity and watching it fail."""
    curves = _load("growth_curves")["curves"]

    assert curves["monster"]["GROW_CURVE_STRIKE"]["arith"] == "ARITH_ADD"
    assert curves["avatar"]["GROW_CURVE_HP_S5"]["arith"] == "ARITH_MULTI"


def test_the_artifact_value_tables_cover_five_star_level_twenty():
    """The values Chunk G scores a build with."""
    values = _load("artifact_main_stat_values")["values"]

    assert values["5"]["21"]["FIGHT_PROP_CRITICAL_HURT"] > 0
    assert len(values["5"]) == 21  # levels 1..21 inclusive of the +0 row
