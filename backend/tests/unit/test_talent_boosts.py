"""Math-fallback 9b — constellation talent-level boosts for the optimized character's own hits.

A build stores GOOD's talent levels, which exclude the +3 a C3 and a C5 add. gcsim adds them
(`TalentLvlSkill`/`TalentLvlBurst`/`TalentLvlAttack`, `character.go:221-264`) and GO adds
them (`skillBoost: greaterEq(input.constellation, N, 3)`); the analytic chain read the stored
level, so a C6 Xiangling's Pyronado was scored at 9 where both comparators use 12.

The table is derived from both comparators' source at their pins and never written by hand;
these tests hold it to every character the committed index knows.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from app.formula.genshin import sheets
from app.services import gcsim_config, gcsim_keys, talent_boosts
from app.services.gcsim_keys import GcsimKeyError
from app.services.talent_boosts import (
    TalentBoostError,
    boosts_for,
    effective_talent_levels,
)

_INDEX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "character.json"

#: Practice mannequins and the two element-less Traveler bodies: no gcsim package, no GO
#: sheet, and not ownable as a roster character (`test_roster_excludes_only_the_mannequins`).
_NO_KIT = {"Manekin", "Manekina"}


def _character(nanoka_id: str, name: str, element: str | None) -> types.SimpleNamespace:
    return types.SimpleNamespace(nanoka_id=nanoka_id, name=name, element=element)


def _index() -> dict[str, dict]:
    return json.loads(_INDEX.read_text())


def _has_kit(nanoka_id: str, entry: dict) -> bool:
    # The index spells an element-less body's element as the string "None".
    elementless = entry.get("element") in (None, "", "None")
    return entry["en"] not in _NO_KIT and not (entry["en"] == "Traveler" and elementless)


XIANGLING = _character("10000023", "Xiangling", "Pyro")
BENNETT = _character("10000032", "Bennett", "Pyro")
NEUVILLETTE = _character("10000087", "Neuvillette", "Hydro")
STORED = {"normal_attack": 9, "elemental_skill": 9, "elemental_burst": 9}


# ── the arithmetic, on the cases the task names ─────────────────────────────


def test_a_c6_xiangling_reads_pyronado_at_twelve():
    """Her C3 raises the burst (gcsim `xiangling.go`: `c.BurstCon = 3`; GO
    `Xiangling/index.tsx:155,160`), and her C5 the skill."""
    levels = effective_talent_levels(XIANGLING, 6, STORED)

    assert levels == {"normal_attack": 9, "elemental_skill": 12, "elemental_burst": 12}


def test_a_c3_xiangling_has_only_the_burst_raised():
    assert effective_talent_levels(XIANGLING, 3, STORED)["elemental_skill"] == 9
    assert effective_talent_levels(XIANGLING, 3, STORED)["elemental_burst"] == 12


def test_a_c2_character_is_unchanged():
    assert effective_talent_levels(XIANGLING, 2, STORED) == STORED


def test_a_character_whose_c3_raises_the_skill():
    """Bennett's C3 is his skill and his C5 his burst — the other way round from Xiangling,
    which is why the table is per character."""
    levels = effective_talent_levels(BENNETT, 3, STORED)

    assert levels == {"normal_attack": 9, "elemental_skill": 12, "elemental_burst": 9}


def test_a_character_whose_c3_raises_the_normal_attack():
    """gcsim `neuvillette.go`: `c.NormalCon = 3` — a third talent the boost can land on."""
    levels = effective_talent_levels(NEUVILLETTE, 3, STORED)

    assert levels["normal_attack"] == 12
    assert levels["elemental_burst"] == 9


def test_the_stored_levels_are_not_mutated():
    stored = dict(STORED)
    effective_talent_levels(XIANGLING, 6, stored)

    assert stored == STORED


def test_a_talent_the_build_has_no_level_for_stays_absent():
    """A missing level is refused downstream (`talent_hits`), never invented here as 1+3."""
    assert effective_talent_levels(XIANGLING, 6, {"normal_attack": 9}) == {"normal_attack": 9}


def test_a_stored_level_above_the_base_cap_is_refused_when_the_boost_applies():
    """Stored levels are base levels. A 13 on a boosted talent already looks boosted, and
    adding three would count the constellation twice."""
    with pytest.raises(TalentBoostError, match="above the base cap of 10"):
        effective_talent_levels(XIANGLING, 3, {"elemental_burst": 13})


def test_an_uncovered_character_is_scored_unboosted_below_c3_and_refused_from_it():
    nobody = _character("99999999", "Nobody In Particular", "Pyro")

    assert effective_talent_levels(nobody, 2, STORED) == STORED
    with pytest.raises(TalentBoostError, match="Nobody In Particular"):
        effective_talent_levels(nobody, 3, STORED)


# ── the table covers every character, from data ─────────────────────────────


def test_every_character_with_a_kit_has_a_derived_table():
    """Every character in the committed nanoka index, Travelers per element included."""
    covered = 0
    for nanoka_id, entry in _index().items():
        if not _has_kit(nanoka_id, entry):
            continue
        boosts = boosts_for(_character(nanoka_id, entry["en"], entry.get("element")))
        assert sorted(boosts.values()) in ([3, 5], []), (entry["en"], boosts)
        assert set(boosts) <= {"normal_attack", "elemental_skill", "elemental_burst"}
        covered += 1
    assert covered == 134


def test_characters_without_a_kit_are_refused_by_name_from_c3():
    for nanoka_id, entry in _index().items():
        if _has_kit(nanoka_id, entry):
            continue
        with pytest.raises(TalentBoostError, match=entry["en"]):
            boosts_for(_character(nanoka_id, entry["en"], entry.get("element")))


def test_gcsim_and_go_agree_on_every_character_both_know_but_one():
    """The two sources are independent derivations; where both have a character they must
    agree. The one exception is Aloy: her six constellations are placeholders in the game
    data (*"The time has not yet come…"*), GO models none, and gcsim's `NewChar` sets
    `SkillCon`/`BurstCon` only because `consCheck` demands two values. She is always C0, so
    the difference cannot reach a number."""
    gcsim, go = talent_boosts.gcsim_table(), {
        k.lower(): v for k, v in talent_boosts.go_table().items()
    }
    compared, disagree = 0, set()
    for nanoka_id, entry in _index().items():
        if not _has_kit(nanoka_id, entry):
            continue
        try:
            key = gcsim_keys.character_key(nanoka_id, entry["en"], entry.get("element"))
        except GcsimKeyError:
            continue
        from_go = go.get(talent_boosts.go_key(entry["en"], entry.get("element")))
        if key not in gcsim or from_go is None:
            continue
        compared += 1
        if gcsim[key] != from_go:
            disagree.add(entry["en"])
    assert disagree == {"Aloy"}
    assert compared >= 120


def test_aloy_resolves_to_gcsims_table():
    """gcsim is read first, because the damage chain is crossvalidated against it."""
    assert boosts_for(_character("10000062", "Aloy", "Cryo")) == {
        "elemental_burst": 5, "elemental_skill": 3,
    }


def test_both_snapshots_name_their_pin():
    assert talent_boosts._go_snapshot()["go_commit"] == (
        "2c13fc40c4694fd8beae513493c4c8a7537173c6"
    )
    assert len(gcsim_keys.character_talent_boosts()) >= 128


# ── one table: the kit sheets carry the same boosts ─────────────────────────


@pytest.mark.parametrize("slug", sorted(sheets.all_sheets()))
def test_each_kit_sheet_states_the_derived_boosts(slug: str):
    """A sheet's `talent_boosts` are its citations for `effective_level`; they must say what
    the derived table says, or a giver and a subject would read the same talent at different
    levels."""
    sheet = sheets.all_sheets()[slug]
    stated = {b.talent: b.constellation for b in sheet.talent_boosts}

    assert stated == boosts_for(_character(sheet.nanoka_id, sheet.character, None))


@pytest.mark.parametrize("slug", sorted(sheets.all_sheets()))
@pytest.mark.parametrize("constellation", range(7))
def test_a_giver_and_a_subject_read_the_same_level(slug: str, constellation: int):
    """`sheets.effective_level` (a buff's giver) and `effective_talent_levels` (the optimized
    character's own hits) are the same rule at every constellation."""
    sheet = sheets.all_sheets()[slug]
    giver = sheets.Giver(
        name=sheet.character, nanoka_id=sheet.nanoka_id, constellation=constellation,
        ascension_phase=6, talent_levels=dict(STORED), talent_rows={},
        constellation_params={}, passive_params={}, registry=None,  # type: ignore[arg-type]
    )
    subject = effective_talent_levels(
        _character(sheet.nanoka_id, sheet.character, None), constellation, STORED,
    )

    for talent in STORED:
        assert sheets.effective_level(sheet, giver, talent) == subject[talent], talent


# ── the surfaces that must NOT add it ───────────────────────────────────────


def test_the_gcsim_config_emits_the_stored_level_for_a_c6_build():
    """gcsim adds the boost itself (`TalentLvlBurst`), and refuses a level above 10. Emitting
    the effective level would count C3 twice and then fail validation."""
    build = types.SimpleNamespace(
        id="b1", character=XIANGLING, weapon=None, artifacts=[], character_level=90,
        constellation_level=6, weapon_level=90, refinement=1, talent_levels=dict(STORED),
    )
    config = gcsim_config.build_config(build, actions=["burst"])

    assert "talent=9,9,9;" in config
    assert "cons=6" in config
