"""D.4 — the weapon mapping, against the committed payload and the shapes the sweep found.

The committed detail fixture is one ordinary 5-star sword. The three *other* shapes in the
286-entry index — cosmetic skins, the TPS weapons, and the stat-less low-rarity ones — are
built here as minimal payloads, because what matters about them is the one key that makes
them different, not 10 KB of prose around it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.data.importers.nanoka_gi_mappings import (
    NanokaMappingError,
    is_weapon_skin,
    refinement_rows,
    weapon_fields,
)
from app.models.enums import Rarity, StatType, WeaponType

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"


@pytest.fixture
def aquila() -> dict:
    return json.loads((_FIX / "weapon_11501.json").read_text())


def test_weapon_fields_map_the_scalar_columns(aquila):
    fields = weapon_fields("11501", aquila)

    assert fields["nanoka_id"] == 11501
    assert fields["name"] == "Aquila Favonia"
    assert fields["weapon_type"] is WeaponType.SWORD
    assert fields["rarity"] is Rarity.FIVE_STAR
    assert fields["icon"] == "UI_EquipIcon_Sword_Falcon"


def test_base_atk_and_substat_are_split_by_prop_type_not_position(aquila):
    fields = weapon_fields("11501", aquila)

    assert fields["base_atk"] == pytest.approx(47.537)
    assert fields["base_atk_curve"] == "GROW_CURVE_ATTACK_302"
    assert fields["sub_stat_type"] is StatType.PHYSICAL_DMG_BONUS
    assert fields["sub_stat_base_value"] == pytest.approx(0.09)
    assert fields["sub_stat_curve"] == "GROW_CURVE_CRITICAL_301"


def test_the_props_are_matched_even_when_the_payload_reorders_them(aquila):
    """252 of 252 lead with base ATK today. Matching on order would trust that forever."""
    reordered = dict(aquila)
    reordered["weapon_prop"] = list(reversed(aquila["weapon_prop"]))

    assert weapon_fields("11501", reordered)["base_atk"] == pytest.approx(47.537)


def test_ascension_atk_is_kept_verbatim(aquila):
    ascension = weapon_fields("11501", aquila)["ascension_atk"]

    assert ascension["1"] == {"fight_prop_base_attack": 31.1}
    assert len(ascension) == 6


def test_a_skin_is_recognised_and_is_not_a_weapon():
    """26 entries carry `skin: true`, no stats, and sometimes no name at all."""
    skin = {
        "name": "Golden Bough of Nemorensis - Sublimation",
        "weapon_type": "WEAPON_SWORD_ONE_HAND",
        "rarity": 5,
        "tag": "TAG_TYPE_COLOR_BY_ELEMENT",
        "skin": True,
    }

    assert is_weapon_skin(skin) is True
    assert is_weapon_skin({"name": "Aquila Favonia", "rarity": 5}) is False


def test_a_tps_weapon_imports_with_null_stats_rather_than_failing():
    """224001-224008 have no weapon_prop, ascension or refinement — C.4's nullable columns."""
    tps = {
        "name": "Shatanaya's Frostsilver",
        "weapon_type": "ITEM_TPS_WEAPON",
        "rarity": 4,
        "icon": "UI_EquipIcon_AssaultRifle_Glacia",
        "skill": 11344,
        "tps": True,
    }

    fields = weapon_fields("224001", tps)

    # Folded into CROSSBOW: the character index spells the same class WEAPON_CROSSBOW (C.1).
    assert fields["weapon_type"] is WeaponType.CROSSBOW
    assert fields["base_atk"] is None
    assert fields["sub_stat_type"] is None
    assert fields["ascension_atk"] == {}
    assert refinement_rows(tps) == []


def test_a_fight_prop_none_substat_is_absent_rather_than_worth_zero():
    """Ten 1★/2★ weapons carry `FIGHT_PROP_NONE` with an `init_value` of 0 and a curve."""
    dull_blade = {
        "name": "Dull Blade",
        "weapon_type": "WEAPON_SWORD_ONE_HAND",
        "rarity": 1,
        "weapon_prop": [
            {"init_value": 23.0, "prop_type": "FIGHT_PROP_BASE_ATTACK", "type": "GROW_CURVE_A"},
            {"init_value": 0, "prop_type": "FIGHT_PROP_NONE", "type": "GROW_CURVE_CRITICAL_101"},
        ],
    }

    fields = weapon_fields("11101", dull_blade)

    assert fields["sub_stat_type"] is None
    assert fields["sub_stat_base_value"] is None
    assert fields["sub_stat_curve"] is None


def test_a_second_substat_raises_rather_than_silently_keeping_the_first():
    payload = {
        "name": "Impossible Sword",
        "weapon_type": "WEAPON_SWORD_ONE_HAND",
        "rarity": 5,
        "weapon_prop": [
            {"init_value": 47.5, "prop_type": "FIGHT_PROP_BASE_ATTACK", "type": "GROW_CURVE_A"},
            {"init_value": 0.1, "prop_type": "FIGHT_PROP_CRITICAL", "type": "GROW_CURVE_B"},
            {"init_value": 0.2, "prop_type": "FIGHT_PROP_ATTACK_PERCENT", "type": "GROW_CURVE_C"},
        ],
    }

    with pytest.raises(NanokaMappingError, match="at most one substat"):
        weapon_fields("99999", payload)


def test_refinements_are_ordered_and_keep_their_params(aquila):
    rows = refinement_rows(aquila)

    assert [row["level"] for row in rows] == [1, 2, 3, 4, 5]
    assert rows[0]["name"] == "Falcon's Defiance"
    # The numbers the description renders inside `<color=…>` markup, kept as data (C.4).
    assert rows[0]["param_list"][0] == pytest.approx(0.2)
    assert rows[4]["param_list"][0] > rows[0]["param_list"][0]


def test_a_one_level_refinement_ladder_is_data_not_a_truncation():
    """Sword of Descension, Predator and Kagotsurube Isshin cannot be refined at all."""
    payload = {"refinement": {"1": {"name": "Even-Handed", "desc": "x", "param_list": [1]}}}

    assert [row["level"] for row in refinement_rows(payload)] == [1]


def test_an_unmappable_weapon_type_raises():
    """A new weapon class must not be imported as whatever the parser fell back to."""
    payload = {"name": "Trident", "weapon_type": "WEAPON_TRIDENT", "rarity": 5}

    with pytest.raises(NanokaMappingError, match="unmappable weapon type"):
        weapon_fields("99999", payload)


def test_an_unmappable_rarity_raises():
    payload = {"name": "Impossible", "weapon_type": "WEAPON_BOW", "rarity": 9}

    with pytest.raises(NanokaMappingError, match="unmappable rarity"):
        weapon_fields("99999", payload)


def test_an_unmapped_substat_raises_rather_than_importing_as_no_substat():
    """`FIGHT_PROP_NONE` means "none"; an unknown prop means the vocabulary moved.

    Both make `stat_type_for` return None, and treating the second as "no substat" writes a
    weapon the optimizer reads as having no secondary stat — on a green seed run.
    """
    payload = {
        "name": "Patch 8.0 Sword",
        "weapon_type": "WEAPON_SWORD_ONE_HAND",
        "rarity": 5,
        "weapon_prop": [
            {"init_value": 47.5, "prop_type": "FIGHT_PROP_BASE_ATTACK", "type": "GROW_A"},
            {"init_value": 0.2, "prop_type": "FIGHT_PROP_NEW_THING", "type": "GROW_B"},
        ],
    }

    with pytest.raises(NanokaMappingError, match="not in StatType"):
        weapon_fields("11599", payload)
