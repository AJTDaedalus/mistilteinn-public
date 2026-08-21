"""D.5 — the artifact-set mapping. Offline, against the committed payload."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.data.importers.nanoka_gi_mappings import (
    NanokaMappingError,
    artifact_affix_rows,
    artifact_set_fields,
)

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"


@pytest.fixture
def deepwood() -> dict:
    return json.loads((_FIX / "artifact_15025.json").read_text())


def test_set_fields_map_the_scalar_columns(deepwood):
    fields = artifact_set_fields("15025", deepwood)

    assert fields["nanoka_id"] == 15025
    assert fields["piece_thresholds"] == [2, 4]
    assert fields["available_ranks"] == [4, 5]
    assert fields["icon"] == "UI_RelicIcon_15025_4"


def test_the_set_name_comes_from_its_affixes(deepwood):
    """There is no top-level name; all 65 sets have one distinct name across their affixes."""
    assert artifact_set_fields("15025", deepwood)["name"] == "Deepwood Memories"


def test_a_set_with_no_affixes_raises_rather_than_being_stored_nameless():
    with pytest.raises(NanokaMappingError, match="no affix rows"):
        artifact_set_fields("15025", {"need": [], "rank": [5]})


def test_a_one_piece_set_is_data_not_an_anomaly():
    """The five "Prayers" circlets (15009-15013) publish `need: [1]` and a single affix."""
    payload = {
        "need": [1],
        "rank": [4],
        "icon": "UI_RelicIcon_15009_3",
        "affix": [{"level": 0, "name": "Prayers for Illumination", "desc": "x"}],
    }

    assert artifact_set_fields("15009", payload)["piece_thresholds"] == [1]
    assert [row["pieces_required"] for row in artifact_affix_rows("15009", payload)] == [1]


def test_affixes_pair_positionally_with_the_piece_thresholds(deepwood):
    rows = artifact_affix_rows("15025", deepwood)

    assert [(row["position"], row["pieces_required"]) for row in rows] == [(0, 2), (1, 4)]
    assert rows[0]["description"] == "Dendro DMG Bonus +15%."


def test_both_add_props_and_param_list_survive(deepwood):
    """324 affix rows across the 65 sets have add_props entirely FIGHT_PROP_NONE (C.5)."""
    two_piece, four_piece = artifact_affix_rows("15025", deepwood)

    assert two_piece["add_props"][0] == {
        "prop_type": "FIGHT_PROP_GRASS_ADD_HURT", "value": 0.15,
    }
    # The 4-piece is conditional, so it has no static prop at all — its numbers are only
    # in param_list and in `<color=…>` markup.
    assert {prop["prop_type"] for prop in four_piece["add_props"]} == {"FIGHT_PROP_NONE"}
    assert four_piece["param_list"][:2] == [0.3, 8]


def test_a_threshold_count_that_does_not_match_the_affixes_raises(deepwood):
    """Pairing is positional; a mismatch would silently marry 4pc text to a 2pc threshold."""
    broken = copy.deepcopy(deepwood)
    broken["need"] = [2]

    with pytest.raises(NanokaMappingError, match="piece thresholds"):
        artifact_affix_rows("15025", broken)


def test_an_affix_declaring_the_wrong_level_raises(deepwood):
    broken = copy.deepcopy(deepwood)
    broken["affix"][1]["level"] = 3

    with pytest.raises(NanokaMappingError, match="declares level 3"):
        artifact_affix_rows("15025", broken)
