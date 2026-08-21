"""D.6 — the monster mapping, against the two committed payloads.

Hilichurl and Ruin Guard are committed precisely because they differ in the way that
matters: one is a uniform 10% RES baseline, the other has 70% physical RES. A mapping
checked against the first alone would look correct with the resistances hardcoded.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.data.importers.nanoka_gi_mappings import (
    NanokaMappingError,
    canonical_variant,
    enemy_profile_fields,
    is_statless_monster,
)

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"


@pytest.fixture
def hilichurl() -> dict:
    return json.loads((_FIX / "monster_21010101.json").read_text())


@pytest.fixture
def ruin_guard() -> dict:
    return json.loads((_FIX / "monster_24010101.json").read_text())


def test_profile_fields_map_the_scalar_columns(hilichurl):
    fields = enemy_profile_fields("21010101", hilichurl)

    assert fields["nanoka_id"] == 21010101
    assert fields["name"] == "Hilichurl"
    assert fields["tags"] == "HILICHURL"
    assert fields["base_hp"] == pytest.approx(13.584)
    assert fields["base_def"] == pytest.approx(500)


def test_all_eight_resistance_channels_are_mapped(hilichurl):
    fields = enemy_profile_fields("21010101", hilichurl)

    channels = [
        "pyro_res", "hydro_res", "anemo_res", "cryo_res",
        "electro_res", "geo_res", "dendro_res", "physical_res",
    ]
    assert [fields[channel] for channel in channels] == [pytest.approx(0.1)] * 8


def test_resistance_is_not_a_constant(ruin_guard):
    """A Ruin Guard's armour is 70% physical RES where everything else is 10%."""
    fields = enemy_profile_fields("24010101", ruin_guard)

    assert fields["physical_res"] == pytest.approx(0.7)
    assert fields["pyro_res"] == pytest.approx(0.1)


def test_the_internal_channel_names_map_to_the_right_element(ruin_guard):
    """GRASS is Dendro, ROCK is Geo, ELEC is Electro, WATER is Hydro (C.2)."""
    payload = copy.deepcopy(ruin_guard)
    child = payload["child"]["24010101"]
    child["sub_hurt"] = {
        "fire": 0.1, "water": 0.2, "wind": 0.3, "ice": 0.4,
        "elec": 0.5, "rock": 0.6, "grass": 0.7, "physical": 0.8,
    }

    fields = enemy_profile_fields("24010101", payload)

    assert fields["pyro_res"] == pytest.approx(0.1)
    assert fields["hydro_res"] == pytest.approx(0.2)
    assert fields["anemo_res"] == pytest.approx(0.3)
    assert fields["cryo_res"] == pytest.approx(0.4)
    assert fields["electro_res"] == pytest.approx(0.5)
    assert fields["geo_res"] == pytest.approx(0.6)
    assert fields["dendro_res"] == pytest.approx(0.7)
    assert fields["physical_res"] == pytest.approx(0.8)


def test_an_unknown_resistance_channel_raises(hilichurl):
    """Eight channels are eight columns; a ninth needs one, not a silent drop."""
    payload = copy.deepcopy(hilichurl)
    payload["child"]["21010101"]["sub_hurt"]["void"] = 0.5

    with pytest.raises(NanokaMappingError, match="unmapped sub_hurt"):
        enemy_profile_fields("21010101", payload)


def test_the_canonical_variant_is_the_child_sharing_the_family_id(hilichurl):
    """True for 358 of the 360 families with children — it is the plain spawn."""
    variant_id, variant = canonical_variant("21010101", hilichurl)

    assert variant_id == "21010101"
    assert variant["monster_name"] == "Hili_None_01"


def test_a_family_that_does_not_contain_its_own_id_falls_back_to_the_lowest_child():
    """Two families are shaped this way (e.g. 22110401, whose children are …02 and …03)."""
    payload = {
        "name": "Overgrown Breacher Primus",
        "child": {
            "22110403": {"base": {"hp": 2}, "sub_hurt": {}, "prop": []},
            "22110402": {"base": {"hp": 1}, "sub_hurt": {}, "prop": []},
        },
    }

    variant_id, _ = canonical_variant("22110401", payload)

    assert variant_id == "22110402"


def test_the_chosen_variant_and_the_family_size_are_both_recorded(hilichurl):
    """189 of 360 families have children whose stats differ, so the choice must be visible."""
    fields = enemy_profile_fields("21010101", hilichurl)

    assert fields["variant_nanoka_id"] == 21010101
    assert fields["variant_count"] == 13


def test_stat_curves_are_carried_so_the_bases_can_be_evaluated(hilichurl):
    """`base_hp` is 13.584 — a curve base. Without the curve name it means nothing."""
    curves = enemy_profile_fields("21010101", hilichurl)["stat_curves"]

    assert curves == {
        "FIGHT_PROP_BASE_HP": "GROW_CURVE_HP",
        "FIGHT_PROP_BASE_ATTACK": "GROW_CURVE_ATTACK",
        "FIGHT_PROP_BASE_DEFENSE": "GROW_CURVE_DEFENSE",
    }


def test_a_none_curve_is_dropped_rather_than_stored_as_a_curve_named_none():
    payload = {
        "name": "Test Dummy",
        "child": {
            "29010101": {
                "base": {"hp": 1},
                "sub_hurt": {},
                "prop": [
                    {"type": "FIGHT_PROP_NONE", "grow_curve": "GROW_CURVE_NONE"},
                    {"type": "FIGHT_PROP_BASE_HP", "grow_curve": "GROW_CURVE_HP"},
                ],
            },
        },
    }

    curves = enemy_profile_fields("29010101", payload)["stat_curves"]

    assert curves == {"FIGHT_PROP_BASE_HP": "GROW_CURVE_HP"}


def test_a_codex_entry_with_no_children_is_recognised_as_stat_less():
    """225 of 585 entries are wildlife with no `child` map at all."""
    crab = {"codex": "CRITTER", "desc": "A crab.", "icon": "x", "name": "Golden Crab"}

    assert is_statless_monster(crab) is True


def test_a_monster_with_children_is_not_stat_less(hilichurl):
    assert is_statless_monster(hilichurl) is False


def test_taking_a_variant_from_a_childless_payload_raises():
    with pytest.raises(NanokaMappingError, match="no child entries"):
        canonical_variant("28010101", {"name": "Golden Crab"})
