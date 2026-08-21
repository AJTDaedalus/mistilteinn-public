"""Every Genshin enum is asserted against the committed nanoka fixtures (C.2).

The point of these tests is not that the enums parse — it is that they match the payload
the importer will actually be handed. Each assertion reads
`backend/tests/fixtures/nanoka_gi/`, never the network: a test that fetches nanoka goes red
on patch day and on a machine with no network, and a test allowed to skip in those cases
stops proving anything at all. Upstream change arrives here as a failing assertion against a
reviewable fixture diff.
"""

import json
import logging
from pathlib import Path

import pytest

from app.models.enums import (
    ArtifactSlot,
    DamageType,
    Element,
    Rarity,
    StatType,
    TalentType,
    WeaponType,
    stat_type_for,
)

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi"


def _load(name: str) -> dict:
    return json.loads((_FIX / name).read_text())


# ── Element ───────────────────────────────────────────────────────────────────


def test_element_covers_every_vision_in_the_character_index():
    seen = {v["element"] for v in _load("character.json").values()}
    visions = seen - {"None"}
    assert visions == {e.value for e in Element}


def test_element_excludes_physical():
    """Physical is a damage type, not a vision — the ZZZ-shaped trap DESIGN §2.6 names."""
    assert "Physical" not in {e.value for e in Element}
    assert DamageType.PHYSICAL.value == "physical"


def test_the_literal_none_element_is_handled_not_mapped():
    """Two characters carry element "None". It must not become an Element member."""
    counts = [v["element"] for v in _load("character.json").values()]
    assert counts.count("None") == 2
    assert Element.parse("None") is None
    assert Element.parse("Cryo") is Element.CRYO


# ── WeaponType ────────────────────────────────────────────────────────────────


def test_weapon_type_covers_the_character_index():
    seen = {v["weapon"] for v in _load("character.json").values()}
    assert {WeaponType.parse(v) for v in seen} == set(WeaponType)


def test_weapon_type_covers_the_weapon_index_including_its_different_crossbow_spelling():
    """The two indexes disagree: characters say WEAPON_CROSSBOW, weapons say ITEM_TPS_WEAPON."""
    seen = {v["type"] for v in _load("weapon.json").values()}
    assert "ITEM_TPS_WEAPON" in seen
    assert "WEAPON_CROSSBOW" not in seen
    assert WeaponType.parse("ITEM_TPS_WEAPON") is WeaponType.CROSSBOW
    assert WeaponType.parse("WEAPON_CROSSBOW") is WeaponType.CROSSBOW
    assert {WeaponType.parse(v) for v in seen} == set(WeaponType)


def test_there_are_six_weapon_types():
    assert len(WeaponType) == 6


# ── Rarity ────────────────────────────────────────────────────────────────────


def test_rarity_normalises_the_character_quality_strings():
    seen = {v["rank"] for v in _load("character.json").values()}
    assert seen == {"QUALITY_ORANGE", "QUALITY_PURPLE", "QUALITY_ORANGE_SP"}
    assert Rarity.parse("QUALITY_ORANGE") is Rarity.FIVE_STAR
    assert Rarity.parse("QUALITY_ORANGE_SP") is Rarity.FIVE_STAR
    assert Rarity.parse("QUALITY_PURPLE") is Rarity.FOUR_STAR


def test_quality_orange_sp_is_not_a_singleton():
    """DESIGN called it "Aloy-class special"; the index has 15 of them."""
    counts = [v["rank"] for v in _load("character.json").values()]
    assert counts.count("QUALITY_ORANGE_SP") == 15


def test_rarity_normalises_the_weapon_integer_ranks():
    seen = {v["rank"] for v in _load("weapon.json").values()}
    assert seen == {1, 2, 3, 4, 5}
    assert {Rarity.parse(v) for v in seen} == set(Rarity)
    assert Rarity.parse(5) is Rarity.FIVE_STAR
    assert Rarity.FIVE_STAR.stars == 5


# ── ArtifactSlot ──────────────────────────────────────────────────────────────


def test_artifact_slot_matches_the_detail_payload_part_keys():
    parts = _load("detail/artifact_15025.json")["parts"]
    assert {s.value for s in ArtifactSlot} == set(parts)
    assert len(ArtifactSlot) == 5


def test_artifact_slot_is_a_str_enum_not_an_int_enum():
    """Genshin's slots are named, not ordered — DESIGN §3 Chunk C."""
    assert ArtifactSlot.FLOWER == "equip_bracer"
    assert isinstance(ArtifactSlot.FLOWER, str)


# ── StatType ──────────────────────────────────────────────────────────────────


def test_stat_type_covers_every_weapon_substat_in_the_index():
    seen = {v.get("sub") for v in _load("weapon.json").values()}
    for raw in seen:
        assert stat_type_for(raw) is not None or raw in (None, "FIGHT_PROP_NONE")


def test_absent_substat_has_two_encodings_and_both_mean_none():
    seen = [v.get("sub") for v in _load("weapon.json").values()]
    assert seen.count(None) == 34
    assert seen.count("FIGHT_PROP_NONE") == 10
    assert stat_type_for(None) is None
    assert stat_type_for("FIGHT_PROP_NONE") is None


def test_stat_type_covers_every_artifact_affix_prop():
    vocab = _load("fight_prop_vocabulary.json")["affix_prop_counts"]
    unmapped = [k for k in vocab if k != "FIGHT_PROP_NONE" and stat_type_for(k) is None]
    assert unmapped == []


def test_elemental_dmg_bonus_props_map_to_the_element_the_payload_names():
    """`GRASS` is Dendro, `ROCK` is Geo, … — read off the affix desc text, not from memory."""
    pairs = _load("fight_prop_vocabulary.json")["element_dmg_bonus"]
    assert pairs, "fixture lost its element pairings"
    for prop, elements in pairs.items():
        assert len(elements) == 1
        assert StatType.dmg_bonus_for(Element(elements[0])).value == prop


def test_every_element_has_a_dmg_bonus_stat():
    for element in Element:
        assert StatType.dmg_bonus_for(element) in set(StatType)


def test_an_unmapped_key_warns_and_never_drops_silently(caplog):
    with caplog.at_level(logging.WARNING):
        assert stat_type_for("FIGHT_PROP_INVENTED_BY_A_FUTURE_PATCH") is None
    assert "FIGHT_PROP_INVENTED_BY_A_FUTURE_PATCH" in caplog.text


@pytest.mark.parametrize("known", ["FIGHT_PROP_NONE", None])
def test_known_absent_values_do_not_warn(caplog, known):
    """Warning on the 44 legitimately-absent substats would train everyone to ignore the log."""
    with caplog.at_level(logging.WARNING):
        stat_type_for(known)
    assert caplog.text == ""


# ── TalentType ────────────────────────────────────────────────────────────────


def test_talent_type_classifies_the_skill_icons_in_the_character_payload():
    """`Skill_A_*` normal attack, `Skill_S_*` skill/sprint, `Skill_E_*` burst."""
    skills = _load("detail/character_10000002.json")["skills"]
    icons = [s["promote"]["0"]["icon"] for s in skills]
    assert [TalentType.from_skill_icon(i) for i in icons] == [
        TalentType.NORMAL_ATTACK,
        TalentType.ELEMENTAL_SKILL,
        TalentType.ELEMENTAL_SKILL,
        TalentType.ELEMENTAL_BURST,
    ]


def test_ayaka_has_four_skills_so_the_list_is_not_positional():
    """Most characters have three; an alternate sprint makes four. Never index by position."""
    assert len(_load("detail/character_10000002.json")["skills"]) == 4
