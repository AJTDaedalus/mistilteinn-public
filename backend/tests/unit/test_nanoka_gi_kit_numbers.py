"""Task 4 of the formula fallback: the numbers the importer used to drop.

`passives[].param_list`, `constellations[].param_list`, `attack[]` and `energy[]` are in every
nanoka character payload, and until this task the importer kept the text that renders them and
threw the numbers away (`RESEARCH_math_fallback_inventory.md` §4.3). These pin that the mapping
now carries them **exactly as published**, for every committed character fixture.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.data.importers.nanoka_gi_mappings import (
    NanokaMappingError,
    attack_rows,
    constellation_rows,
    energy_rows,
    passive_rows,
)

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"
_CHARACTERS = sorted(
    path.stem.removeprefix("character_") for path in _FIX.glob("character_*.json")
)


def _payload(key: str) -> dict:
    return json.loads((_FIX / f"character_{key}.json").read_text())


def test_every_committed_character_fixture_is_swept():
    """Four at 7.0.51. A fixture added later joins every test below without an edit."""
    assert len(_CHARACTERS) == 4


@pytest.mark.parametrize("key", _CHARACTERS)
def test_passive_params_equal_the_payload(key):
    payload = _payload(key)
    rows = passive_rows(payload)
    assert [row["param_list"] for row in rows] == [
        entry["param_list"] for entry in payload["passives"]
    ]


@pytest.mark.parametrize("key", _CHARACTERS)
def test_constellation_params_equal_the_payload(key):
    payload = _payload(key)
    rows = constellation_rows(payload)
    assert [row["param_list"] for row in rows] == [
        entry["param_list"] for entry in payload["constellations"]
    ]


def test_an_ayaka_passive_reads_as_its_text_says():
    """Read by a human: "deal 30% increased DMG for 6s" is `[0.3, 6, 0, …]`."""
    first = passive_rows(_payload("10000002"))[0]
    assert first["name"] == "Amatsumi Kunitsumi Sanctification"
    assert first["param_list"][:3] == [0.3, 6, 0]
    assert len(first["param_list"]) == 25  # the payload's padding is kept, not trimmed


@pytest.mark.parametrize("key", _CHARACTERS)
def test_attack_rows_equal_the_payload(key):
    payload = _payload(key)
    rows = attack_rows(key, payload)
    assert len(rows) == len(payload["attack"])
    for position, (row, entry) in enumerate(zip(rows, payload["attack"], strict=True)):
        assert row["position"] == position
        assert row["name"] == entry["name"]
        assert row["element"] == entry["element"]
        assert row["gauge"] == entry["gauge"]
        assert row["attack_type"] == entry["attack_type"]
        assert row["strike_type"] == entry["strike_type"]
        assert row["damage_param"] == entry["damage_param"]
        assert (row["icd_tag"], row["icd_group"]) == (entry["icd"]["tag"], entry["icd"]["group"])
        poise = entry["poise"] or {}
        assert (row["poise_level"], row["poise_value"]) == (
            poise.get("level"), poise.get("value"),
        )


@pytest.mark.parametrize("key", _CHARACTERS)
def test_energy_rows_equal_the_payload(key):
    payload = _payload(key)
    rows = energy_rows(key, payload)
    assert len(rows) == len(payload["energy"])
    for position, (row, entry) in enumerate(zip(rows, payload["energy"], strict=True)):
        assert row == {"position": position, **entry, "cd_ref": None}


def test_an_energy_cd_given_as_a_parameter_name_goes_to_cd_ref():
    """Eight live entries at 7.2.51 say `"cd": "CD"`; a float column cannot hold that."""
    payload = copy.deepcopy(_payload("10000002"))
    payload["energy"][0]["cd"] = "DropBall_CD"
    row = energy_rows("10000002", payload)[0]
    assert (row["cd"], row["cd_ref"]) == (None, "DropBall_CD")


def test_an_energy_cd_of_any_other_shape_is_refused():
    payload = copy.deepcopy(_payload("10000002"))
    payload["energy"][0]["cd"] = [0.3]
    with pytest.raises(NanokaMappingError, match="cd"):
        energy_rows("10000002", payload)


def test_the_measured_counts_at_7_0_51():
    """Hand-countable from the four files, so a mapping that drops entries cannot pass."""
    counts = {key: (len(attack_rows(key, _payload(key))), len(energy_rows(key, _payload(key))))
              for key in _CHARACTERS}
    assert counts == {
        "10000002": (14, 2),
        "10000005-2": (42, 2),
        "10000022": (59, 2),
        "10000045": (10, 1),
    }


def test_the_element_is_kept_in_the_games_own_spelling():
    """`Ice`, not `Cryo`: the payload's vocabulary is not `Element`, and is not mapped here."""
    elements = {row["element"] for row in attack_rows("10000002", _payload("10000002"))}
    assert "Ice" in elements
    assert "Cryo" not in elements


def test_an_attack_entry_with_an_unknown_key_is_refused_by_name():
    payload = copy.deepcopy(_payload("10000002"))
    payload["attack"][0]["durability"] = 25
    with pytest.raises(NanokaMappingError, match="durability"):
        attack_rows("10000002", payload)


def test_an_icd_of_an_unexpected_shape_is_refused():
    payload = copy.deepcopy(_payload("10000002"))
    payload["attack"][0]["icd"] = "ExtraAttack"
    with pytest.raises(NanokaMappingError, match="icd"):
        attack_rows("10000002", payload)


def test_an_energy_entry_with_an_unknown_key_is_refused_by_name():
    payload = copy.deepcopy(_payload("10000002"))
    payload["energy"][0]["favonius"] = True
    with pytest.raises(NanokaMappingError, match="favonius"):
        energy_rows("10000002", payload)


def test_a_payload_without_the_arrays_imports_none_rather_than_failing():
    """Absent is absent: the alternate-body Travelers publish no kit at all."""
    assert attack_rows("x", {}) == []
    assert energy_rows("x", {"energy": None}) == []
