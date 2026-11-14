"""Per-row moves and row-scoped kit buffs (owner ruling 2026-11-14, `DECISIONS.md` §40 (iv)).

A talent row's move (attack type) comes from its character's sheet where GO declares one that
is not the talent's own (`sheets.RowMove`), and `/hits` reports it; the browser's label-based
guess remains for every row a sheet does not name. A buff GO adds inside one row's formula is
scoped to that row (`rows`), so it cannot reach an ordinary attack of the same move."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.formula.genshin import sheets


def _sheet(slug: str) -> sheets.Sheet:
    return next(s for s in sheets.all_sheets().values() if s.slug == slug)


@pytest.mark.parametrize(("nanoka_id", "talent", "label", "move"), [
    # Skirk's Seven-Phase Flash: skill-talent rows GO deals as Normal/Charged/Plunging Attacks.
    ("10000114", "elemental_skill", "1-Hit DMG|{param1:F1P}", "normal"),
    ("10000114", "elemental_skill", "Charged Attack DMG|{param8:F1P}\u00d73", "charged"),
    ("10000114", "elemental_skill", "Low/High Plunge DMG|{param11:P}/{param12:P}", "plunge"),
    # Mavuika's Flamestrider, Clorinde's Night Vigil, Cyno's Pactsworn, Lohen's skill attacks.
    ("10000106", "elemental_skill", "Flamestrider Normal Attack 3-Hit DMG", "normal"),
    ("10000106", "elemental_skill", "Flamestrider Charged Attack Final DMG", "charged"),
    ("10000106", "elemental_skill", "Flamestrider Plunge DMG", "plunge"),
    ("10000098", "elemental_skill", "Swift Hunt DMG", "normal"),
    ("10000071", "elemental_burst", "5-Hit DMG", "normal"),
    ("10000129", "elemental_skill", "Charged Attack DMG", "charged"),
])
def test_a_sheet_names_the_move_of_a_row_whose_move_is_not_its_talents(
        nanoka_id, talent, label, move):
    assert sheets.row_move(nanoka_id, talent, label) == move


@pytest.mark.parametrize(("nanoka_id", "talent", "label"), [
    ("10000114", "normal_attack", "1-Hit DMG"),          # her ordinary attack: the label decides
    ("10000114", "elemental_skill", "Max Serpent's Subtlety"),
    ("10000106", "elemental_skill", "Flamestrider Sprint DMG"),  # a skill hit, as its talent
    ("10000002", "normal_attack", "Charged Attack DMG"),  # Ayaka has no row moves
    ("99999999", "normal_attack", "1-Hit DMG"),           # no sheet at all
])
def test_a_row_no_sheet_names_is_left_to_the_label_guess(nanoka_id, talent, label):
    assert sheets.row_move(nanoka_id, talent, label) is None


def test_a_row_move_names_a_known_talent_and_move_and_a_row_has_one_move():
    with pytest.raises(ValidationError, match="is not one of"):
        sheets.RowMove(talent="elemental_skill", labels=("1-Hit DMG",), move="dash", go="x")
    with pytest.raises(ValidationError, match="is not one of"):
        sheets.RowMove(talent="passive", labels=("1-Hit DMG",), move="normal", go="x")
    skirk = _sheet("skirk").model_dump(by_alias=True)
    skirk["row_moves"] = [*skirk["row_moves"], {**skirk["row_moves"][0], "move": "charged"}]
    with pytest.raises(ValidationError, match="two moves"):
        sheets.Sheet.model_validate(skirk)


SKIRK_FLASH = {f"{n}-Hit DMG" for n in range(1, 6)}


@pytest.mark.parametrize(("slug", "key", "talent", "labels"), [
    ("skirk", "a4_normal_3", "elemental_skill", SKIRK_FLASH),
    ("skirk", "c2_atk", "elemental_skill",
     SKIRK_FLASH | {"Charged Attack DMG", "Plunge DMG", "Low/High Plunge DMG"}),
    ("neuvillette", "a1_judgment_3", "normal_attack", {"Charged Attack: Equitable Judgment"}),
    ("neuvillette", "c2_crit", "normal_attack", {"Charged Attack: Equitable Judgment"}),
    ("mavuika", "burst_flame_charged", "elemental_skill",
     {"Flamestrider Charged Attack Cyclic DMG", "Flamestrider Charged Attack Final DMG"}),
    ("ganyu", "a1_crit", "normal_attack", {"Frostflake Arrow DMG", "Frostflake Arrow Bloom DMG"}),
    ("navia", "c2_rate", "elemental_skill", {"Rosula Shardshot Base DMG"}),
    ("lohen", "c6_etch_crit", "elemental_skill", {"Etched Into Bone and Soul DMG"}),
    ("linnea", "c2_lumi_crit", "elemental_skill", {"Lumi Million Ton Crush DMG"}),
    ("valeriy", "c6_shell", "elemental_burst", {"Thunderburst Shell DMG"}),
    ("xiangling", "c6_pyro_swing", "elemental_burst", {"3-Hit Swing DMG"}),
])
def test_a_buff_go_adds_inside_some_rows_is_scoped_to_those_rows_and_no_move(
        slug, key, talent, labels):
    """By row, not by move: an ordinary Normal Attack (a `normal_attack` row with the same
    label as a Seven-Phase Flash one) is not one of them."""
    effect = next(e for e in _sheet(slug).effects if e.key == key)
    assert effect.moves is None
    assert {(r.talent, r.label) for r in effect.rows or ()} == {(talent, lab) for lab in labels}


def test_skirks_void_rift_bonus_stays_on_every_normal_attack_as_gos_does():
    """GO adds it to `premod.dmg_.normal` (pando:Skirk.ts:289): by move, so it reaches her
    Seven-Phase Flash rows through their row move, and her ordinary ones too."""
    void = [e for e in _sheet("skirk").effects if e.key.startswith("void_")]
    assert {(e.moves, e.rows) for e in void} == {(("normal",), None)}


def test_every_row_scoped_effect_names_a_row_its_sheet_can_offer():
    """A row label in `rows` is a label `/hits` names: the part before `|`, never the whole."""
    for sheet in sheets.all_sheets().values():
        for effect in sheet.effects:
            for row in effect.rows or ():
                assert "|" not in row.label, (sheet.slug, effect.key)
        for move in sheet.row_moves:
            assert all("|" not in label for label in move.labels), sheet.slug


# ── Vodyanitsa's A4: a threshold on a value, and a cap (DECISIONS §40 (vi)) ─────────────────


def _vodyanitsa(hp: float) -> sheets.Giver:
    from tests.unit.test_go_formula_fixtures import _pinned, _ungated_giver
    cons, pas = _pinned("10000140")
    return _ungated_giver("Vodyanitsa", "10000140", cons=cons, passives=pas,
                          stats={"base_hp": hp, "hp_pct": 0.0, "flat_hp": 0.0})


@pytest.mark.parametrize(("hp", "want"), [
    (30000.0, 0.0),                 # below the threshold: nothing, not a negative bonus
    (52000.0, 12 * 140.0),          # 12 thousands above 40,000 at 140 each
    (90000.0, 3500.0),              # past the cap
])
def test_her_a4_reaches_a_teammate_as_a_number_through_its_threshold_and_cap(hp, want):
    kit = sheets.resolve(_sheet("vodyanitsa"), _vodyanitsa(hp), giver_is_subject=False)
    [a4] = [e for e in kit.bonus.effects if e.stat == "flat_damage"]
    assert (a4.value, a4.elements) == (pytest.approx(want), ("hydro", "cryo"))
    assert [w.condition for w in a4.when] == ["a4_lead_vocal"]


def test_on_herself_her_a4_is_a_capped_thresholded_conversion_priced_per_build():
    kit = sheets.resolve(_sheet("vodyanitsa"), _vodyanitsa(15000.0), giver_is_subject=True)
    [a4] = [e for e in kit.bonus.effects if e.stat == "flat_damage_from_hp"]
    assert (a4.value, a4.threshold, a4.cap) == (pytest.approx(0.14), 40000.0, 3500.0)
