"""D.3 — the character mapping, against the committed payloads and nothing else.

Offline by construction: these call the mapping functions directly, so there is no
session, no transport and no event loop. What they pin is the set of rules the D.2 sweep
established — the ones a single payload could not have shown.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.data.importers.nanoka_gi_mappings import (
    NanokaMappingError,
    ascension_stat_type,
    burst_energy_cost,
    character_fields,
    classify_talent,
    constellation_rows,
    passive_rows,
    talent_rows,
)
from app.models.enums import Element, Rarity, StatType, TalentType, WeaponType

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"


def _payload(name: str) -> dict:
    return json.loads((_FIX / f"{name}.json").read_text())


@pytest.fixture
def ayaka() -> dict:
    return _payload("character_10000002")


@pytest.fixture
def traveler() -> dict:
    """Pyro Traveler — index key `10000005-2`, one of the 28 string-keyed entries."""
    return _payload("character_10000005-2")


def test_character_fields_map_the_scalar_columns(ayaka):
    fields = character_fields("10000002", ayaka)

    assert fields["nanoka_id"] == "10000002"
    assert fields["name"] == "Kamisato Ayaka"
    assert fields["element"] is Element.CRYO
    assert fields["weapon_type"] is WeaponType.SWORD
    assert fields["rarity"] is Rarity.FIVE_STAR
    assert fields["region"] == "ASSOC_TYPE_INAZUMA"
    assert fields["release_date"] == "2021-07-21 00:00:00"
    assert fields["base_hp"] == pytest.approx(1000.986)
    assert fields["icon"] == "UI_AvatarIcon_Ayaka"


def test_a_traveler_variant_keeps_its_suffixed_key(traveler):
    """The whole reason `characters.nanoka_id` is a string (D.1)."""
    fields = character_fields("10000005-2", traveler)

    assert fields["nanoka_id"] == "10000005-2"
    assert fields["name"] == "Traveler"
    assert fields["element"] is Element.PYRO


def test_weapon_type_goes_through_the_parser(ayaka):
    """Raw passthrough writes `ITEM_TPS_WEAPON` on the weapon side and loses joins (C.9)."""
    assert isinstance(character_fields("10000002", ayaka)["weapon_type"], WeaponType)


def test_the_ascension_stat_is_the_one_key_that_is_not_a_base_prop(ayaka):
    fields = character_fields("10000002", ayaka)

    assert fields["ascension_stat_type"] is StatType.CRIT_DMG
    assert len(fields["ascension_stats"]) == 6


def test_a_travelers_ascension_stat_is_atk_percent(traveler):
    assert character_fields("10000005-2", traveler)["ascension_stat_type"] is StatType.ATK_PCT


def test_two_candidate_ascension_stats_raise_rather_than_pick_one():
    """All 150 payloads have exactly one. Two means the shape changed; choosing is a guess."""
    rows = [{
        "fight_prop_base_hp": 1.0,
        "fight_prop_critical_hurt": 0.2,
        "fight_prop_attack_percent": 0.1,
    }]

    with pytest.raises(NanokaMappingError, match="exactly one non-base ascension prop"):
        ascension_stat_type("10000002", rows)


def test_no_ascension_rows_yields_no_stat_rather_than_an_error():
    assert ascension_stat_type("10000002", []) is None


def test_burst_energy_cost_is_parsed_out_of_the_burst_description(ayaka):
    """It is a row of `promote["0"].desc` — `"Energy Cost|{param5:I}"` — not a field."""
    assert burst_energy_cost(ayaka) == 80


def test_a_character_with_no_skills_has_no_burst_cost():
    """Two Traveler bodies ship with `skills: []`; four characters have no Energy Cost row."""
    assert burst_energy_cost({"skills": []}) is None


def test_an_energy_cost_row_pointing_past_the_param_list_yields_none(caplog):
    payload = {
        "skills": [
            {
                "id": 1,
                "promote": {
                    "0": {
                        "level": 1,
                        "icon": "Skill_E_Test",
                        "desc": ["Energy Cost|{param9:I}"],
                        "param": [1, 2],
                    },
                },
            },
        ],
    }

    assert burst_energy_cost(payload) is None
    assert "only 2 params exist" in caplog.text


def test_talents_are_classified_by_icon_and_promote_ladder(ayaka):
    """Ayaka has four `skills[]`, two of them `Skill_S_*`. Position classifies nothing."""
    rows = talent_rows("10000002", ayaka)

    assert [(row["name"], row["talent_type"]) for row in rows] == [
        ("Kamisato Art: Kabuki", TalentType.NORMAL_ATTACK),
        ("Kamisato Art: Hyouka", TalentType.ELEMENTAL_SKILL),
        ("Kamisato Art: Senho", TalentType.ALTERNATE_SPRINT),
        ("Kamisato Art: Soumetsu", TalentType.ELEMENTAL_BURST),
    ]


def test_the_alternate_sprint_is_the_one_level_skill_s_entry():
    """Both carry `Skill_S_*`; only the ladder separates them."""
    skill = {"promote": {"0": {"icon": "Skill_S_Ayaka_02", "level": 1}}}
    real = {"promote": {str(i): {"icon": "Skill_S_Ayaka_01", "level": i + 1} for i in range(15)}}

    assert classify_talent(skill) is TalentType.ALTERNATE_SPRINT
    assert classify_talent(real) is TalentType.ELEMENTAL_SKILL


def test_an_unclassifiable_icon_raises_rather_than_dropping_the_talent():
    """A character silently missing its burst is a wrong build, not a missing row."""
    payload = {"skills": [{"id": 1, "name": "Mystery", "promote": {"0": {"icon": "Skill_Q_X"}}}]}

    with pytest.raises(NanokaMappingError, match="unclassifiable icon"):
        talent_rows("10000002", payload)


def test_talent_scalings_carry_every_published_level_verbatim(ayaka):
    rows = talent_rows("10000002", ayaka)
    normal_attack = rows[0]

    assert [scaling["level"] for scaling in normal_attack["scalings"]] == list(range(1, 16))
    first = normal_attack["scalings"][0]
    assert first["labels"][0] == "1-Hit DMG|{param1:F1P}"
    assert first["params"][0] == pytest.approx(0.457253)
    # The sprint publishes one level, and that is data rather than a truncation.
    assert len(rows[2]["scalings"]) == 1


def test_constellations_are_positioned_by_ordinal_not_by_payload_id(ayaka, traveler):
    """Ayaka's ids are 21-26 and the Traveler's 51-56 — contiguous but arbitrary."""
    ayaka_rows = constellation_rows(ayaka)
    traveler_rows = constellation_rows(traveler)

    assert [row["position"] for row in ayaka_rows] == [1, 2, 3, 4, 5, 6]
    assert [row["nanoka_id"] for row in ayaka_rows] == [21, 22, 23, 24, 25, 26]
    assert [row["position"] for row in traveler_rows] == [1, 2, 3, 4, 5, 6]
    assert [row["nanoka_id"] for row in traveler_rows] == [51, 52, 53, 54, 55, 56]


def test_an_integer_unlock_is_a_phase_gate(ayaka):
    rows = passive_rows(ayaka)

    assert [row["unlock_ascension"] for row in rows] == [1, 4, 0]
    assert all(row["unlock_condition_ids"] == [] for row in rows)


def test_a_list_unlock_becomes_a_condition_and_leaves_the_gate_null(traveler):
    """33 of ~460 passives across the 150 characters carry the list form."""
    rows = passive_rows(traveler)
    condition = next(row for row in rows if row["name"] == "Foreign Starfire")

    assert condition["unlock_ascension"] is None
    assert condition["unlock_condition_ids"] == [603101]
    assert [row["unlock_ascension"] for row in rows] == [1, 4, None]


def test_an_unmappable_character_rarity_raises(ayaka):
    """`Rarity.parse` warns and returns None; the mapping refuses to store the None."""
    payload = dict(ayaka)
    payload["rarity"] = "QUALITY_RAINBOW"

    with pytest.raises(NanokaMappingError, match="unmappable rarity"):
        character_fields("10000002", payload)


def test_an_energy_cost_row_with_no_param_reference_is_skipped():
    """A malformed label must not crash the whole character over one description row."""
    payload = {
        "skills": [
            {
                "id": 1,
                "promote": {
                    "0": {
                        "level": 1,
                        "icon": "Skill_E_Test",
                        "desc": ["Energy Cost", "Energy Cost|{param1:I}"],
                        "param": [40],
                    },
                },
            },
        ],
    }

    assert burst_energy_cost(payload) == 40


def test_a_skill_with_no_promote_entries_classifies_as_nothing():
    """`skills: []` exists (two Traveler bodies); an empty `promote` should not crash."""
    assert classify_talent({"id": 1, "promote": {}}) is None
