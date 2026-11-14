"""Math-fallback P2, task 11 — sheets for the characters gcsim cannot run, and the format
extensions they needed.

The GO agreement of each sheet's main effect is `test_go_formula_fixtures.py`'s job (one fixture
per sheet, `formula:verify` holding the browser to it). This file checks what a fixture does not:
that the list of sheets is the list of ungated characters, and that each extension resolves —
and refuses — as the DESIGN says (§2.6).

Numbers are the sheets' own pins (the seeded lists, nanoka 7.2.51), read back through
`Sheet.pins` rather than retyped, so a re-pin moves these tests with the sheets.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.formula.builder import const
from app.formula.genshin import sheets, tags
from app.pando.calculator import NodeRegistry
from app.services import gcsim_keys

COVERAGE = Path(__file__).resolve().parents[1] / "fixtures" / "gcsim_character_coverage.json"

UNGATED = {
    "10000100": "kachina", "10000122": "nefer", "10000129": "lohen", "10000130": "linnea",
    "10000136": "mitya", "10000137": "valeriy", "10000140": "vodyanitsa", "10000143": "vesna",
}
#: The Traveler bodies with no element and no kit (`skills: []`): nothing to write a sheet from.
NO_KIT = {"10000134", "10000135"}


def _sheet(slug: str) -> sheets.Sheet:
    [sheet] = [s for s in sheets.all_sheets().values() if s.slug == slug]
    return sheet


def _giver(sheet: sheets.Sheet, *, constellation: int = 0, ascension: int = 6,
           talent_levels: dict[str, int] | None = None,
           talent_rows: dict[tuple[str, int], sheets.TalentRow] | None = None,
           **stats: float) -> sheets.Giver:
    registry = NodeRegistry()
    for quantity, value in stats.items():
        registry.register(tags.stat_tag(quantity), const(value))
    return sheets.Giver(
        name=sheet.character, nanoka_id=sheet.nanoka_id, constellation=constellation,
        ascension_phase=ascension, talent_levels=talent_levels or {},
        talent_rows=talent_rows or {},
        constellation_params={n: list(v) for n, v in sheet.pins.constellations.items()},
        passive_params={n: list(v) for n, v in sheet.pins.passives.items()},
        registry=registry,
    )


def _by_stat(kit: sheets.ResolvedKit) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for e in kit.bonus.effects:
        out.setdefault(e.stat, []).append(e.value)
    return out


# ── the list ────────────────────────────────────────────────────────────────────────────


def test_every_ungated_character_has_a_sheet_and_gcsim_has_none_of_them():
    """The list is derived, not typed: each sheet's character has no gcsim key at the pin, and
    every released, non-mannequin character in the committed coverage list with a kit has a
    sheet. (The coverage file predates the 7.1/7.2 re-pins, so Mitya and Valeriy are checked
    by the key lookup rather than by it.)"""
    by_id = {s.nanoka_id: s for s in sheets.all_sheets().values()}
    for nanoka_id, slug in UNGATED.items():
        sheet = by_id[nanoka_id]
        assert sheet.slug == slug
        with pytest.raises(gcsim_keys.GcsimKeyError):
            gcsim_keys.character_key(nanoka_id, sheet.character, None)
    listed = json.loads(COVERAGE.read_text(encoding="utf-8"))["unimplemented"]
    for entry in listed:
        if entry["name"] in ("Manekin", "Manekina") or entry["nanoka_id"] in NO_KIT:
            continue
        assert entry["nanoka_id"] in by_id, entry


def test_every_ungated_sheet_is_verified_by_a_fixture_and_cites_go():
    for slug in UNGATED.values():
        sheet = _sheet(slug)
        assert sheet.verified_by, slug
        assert sheet.gcsim is None, slug
        assert sheet.gcsim_commit is None, slug
        for boost in sheet.talent_boosts:
            assert "ConfigTalent_" in boost.go, (slug, boost.constellation)


def test_talent_boosts_follow_the_game_data_where_gos_files_disagree():
    """GO's WR sheets and its pando port disagree for three characters; the game data's
    `ConfigTalent_<name>.json` (talent index 1 normal, 2 skill, 9 burst) sides with WR."""
    def table(slug: str) -> dict[int, str]:
        return {b.constellation: b.talent for b in _sheet(slug).talent_boosts}
    assert table("mitya") == {3: "elemental_skill", 5: "normal_attack"}
    assert table("valeriy") == {3: "normal_attack", 5: "elemental_skill"}
    assert table("vesna") == {3: "elemental_skill", 5: "elemental_burst"}
    assert table("vodyanitsa") == {3: "elemental_skill", 5: "elemental_burst"}


# ── the extensions ──────────────────────────────────────────────────────────────────────


def test_per_travels_with_the_effect_and_its_condition_is_offered():
    """Mitya's A1 is 30 EM per Beacon (GO `prod(a1Beacons, passive1.eleMas)`): the value is the
    per-stack amount and the browser multiplies by the stacks condition."""
    mitya = _sheet("mitya")
    kit = sheets.resolve(mitya, _giver(mitya), giver_is_subject=False)
    [a1] = [e for e in kit.bonus.effects if e.stat == "elemental_mastery"]
    assert (a1.value, a1.per) == (pytest.approx(mitya.pins.passives[1][0]), "a1_beacons")
    beacons = next(c for c in kit.bonus.conditions if c.key == "a1_beacons")
    assert (beacons.default, beacons.default_reason) == (4, "teammate")
    own = sheets.resolve(mitya, _giver(mitya), giver_is_subject=True)
    beacons = next(c for c in own.bonus.conditions if c.key == "a1_beacons")
    assert (beacons.default, beacons.default_reason) == (4, "self")


def test_a_reduction_published_positive_is_negated():
    vody = _sheet("vodyanitsa")
    labels = list(vody.pins.talent_rows["elemental_skill"])
    row = sheets.TalentRow(["Skill DMG|{param1:F2P} Max HP", *labels],
                           [0.058896, 0, 0, 0, 0, 0, 0, 0.3])
    kit = sheets.resolve(vody, _giver(vody, talent_levels={"elemental_skill": 10},
                                      talent_rows={("elemental_skill", 10): row}),
                         giver_is_subject=False)
    res = {e.elements: e.value for e in kit.bonus.effects if e.stat == "enemy_res"}
    assert res[("hydro", "cryo")] == pytest.approx(-0.3)
    assert res[("anemo",)] == pytest.approx(-vody.pins.passives[1][0])


def test_a_receiver_element_gate_reaches_only_those_elements():
    """Linnea's C2 CRIT DMG reaches Hydro and Geo party members (GO `target.char.ele`)."""
    linnea = _sheet("linnea")
    for element, reached in (("hydro", True), ("geo", True), ("pyro", False)):
        # A giver's registry is one resolution's (pass 1 builds it fresh per request).
        giver = _giver(linnea, constellation=2, base_def=900.0, def_pct=1.0)
        kit = sheets.resolve(linnea, giver, giver_is_subject=False, receiver_element=element)
        assert ("crit_dmg" in _by_stat(kit)) is reached, element


def test_an_effect_needing_the_receiver_is_withheld_without_it():
    linnea = _sheet("linnea")
    kit = sheets.resolve(linnea, _giver(linnea, constellation=2), giver_is_subject=False)
    assert "crit_dmg" not in _by_stat(kit)
    assert any("receiver's element" in u.reason for u in kit.bonus.unmodelled)


def test_a_team_element_count_multiplies_and_a_second_param_scales():
    """Vesna's A4: 6% ATK per Anemo/Cryo member; C4 adds the same again × its 2.0."""
    vesna = _sheet("vesna")
    a4 = vesna.pins.passives[4]
    c4 = vesna.pins.constellations[4][0]
    team = ["anemo", "cryo", "cryo", "geo"]
    kit = sheets.resolve(vesna, _giver(vesna, constellation=4), giver_is_subject=True,
                         receiver_element="anemo", team_elements=team)
    stats = _by_stat(kit)
    assert stats["atk_pct"][:2] == [pytest.approx(a4[0] * 3), pytest.approx(a4[0] * 3 * c4)]
    assert stats["elemental_mastery"] == [pytest.approx(a4[1] * 1), pytest.approx(a4[1] * c4)]


def test_a_team_count_of_zero_drops_the_effect_and_no_team_withholds_it():
    vesna = _sheet("vesna")
    kit = sheets.resolve(vesna, _giver(vesna), giver_is_subject=True,
                         receiver_element="anemo", team_elements=["anemo", "pyro"])
    assert [e.value for e in kit.bonus.effects if e.stat == "elemental_mastery"] == [
        pytest.approx(vesna.pins.passives[4][1])]
    blind = sheets.resolve(vesna, _giver(vesna), giver_is_subject=True)
    assert blind.bonus.effects == ()
    assert any("team's elements" in u.reason for u in blind.bonus.unmodelled)


def test_flat_damage_from_the_subjects_own_def_and_atk_is_per_candidate():
    kachina = _sheet("kachina")
    kit = sheets.resolve(kachina, _giver(kachina, base_def=800.0, def_pct=1.0),
                         giver_is_subject=True)
    assert ("flat_damage_from_def", pytest.approx(kachina.pins.passives[4][0])) in [
        (e.stat, e.value) for e in kit.bonus.effects]
    valeriy = _sheet("valeriy")
    kit = sheets.resolve(valeriy, _giver(valeriy), giver_is_subject=True)
    a4 = [e for e in kit.bonus.effects if e.per == "momentum"]
    assert [(e.stat, e.value) for e in a4] == [
        ("flat_damage_from_atk", pytest.approx(valeriy.pins.passives[4][0]))]


def test_a_teammates_flat_damage_is_a_number_from_the_givers_atk():
    """Valeriy's A4 on an Electro teammate: 0.003 × Valeriy's pass-1 ATK, per Momentum."""
    valeriy = _sheet("valeriy")
    kit = sheets.resolve(valeriy, _giver(valeriy, base_atk=1000.0, atk_pct=1.0),
                         giver_is_subject=False)
    a4 = next(e for e in kit.bonus.effects if e.per == "momentum")
    assert (a4.stat, a4.value) == ("flat_damage",
                                   pytest.approx(valeriy.pins.passives[4][0] * 2000.0))
    momentum = next(c for c in kit.bonus.conditions if c.key == "momentum")
    assert (momentum.kind, momentum.default, momentum.max) == ("number", 100, 100)


def test_others_never_reach_the_giver():
    """Lohen's A4 is two effects: `notOwnBuff` to the others and `ownBuff` to himself."""
    lohen = _sheet("lohen")
    team = sheets.resolve(lohen, _giver(lohen), giver_is_subject=False)
    own = sheets.resolve(lohen, _giver(lohen), giver_is_subject=True)
    a4 = lohen.pins.passives[4]
    assert _by_stat(team)["atk_pct"] == [pytest.approx(a4[0])]
    assert _by_stat(own)["atk_pct"] == [pytest.approx(a4[1])]
    assert "elemental_mastery" not in _by_stat(own)


def test_a_choice_condition_gates_two_effects():
    mitya = _sheet("mitya")
    kit = sheets.resolve(mitya, _giver(mitya, constellation=2), giver_is_subject=False)
    core = next(c for c in kit.bonus.conditions if c.key == "c2_core_type")
    assert (core.kind, core.default, core.options) == ("choice", "", ("steady", "overloaded"))
    gated = {e.when[0].values[0] for e in kit.bonus.effects
             if e.when and e.when[0].condition == "c2_core_type"}
    assert gated == {"steady", "overloaded"}


def test_a_self_buff_from_a_stat_the_recipe_cannot_carry_is_withheld_by_name():
    """Linnea's A4 on Linnea reads her own DEF into EM; nothing carries that per candidate."""
    linnea = _sheet("linnea")
    kit = sheets.resolve(linnea, _giver(linnea), giver_is_subject=True,
                         receiver_element="geo", team_elements=["geo"])
    assert "elemental_mastery" not in _by_stat(kit)
    assert any("A4" in u.what and u.reason.startswith("withheld") for u in kit.bonus.unmodelled)


def test_every_sheet_names_what_it_does_not_model():
    for slug in UNGATED.values():
        assert _sheet(slug).unmodelled, slug
